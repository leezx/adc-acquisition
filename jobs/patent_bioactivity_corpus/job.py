"""Job 13: patent bioactivity evidence corpus (Prompt.md section 17,
"JOB 13", execution order section 29).

SECOND-PASS acquisition job — Prompt.md is explicit: "It should NOT
search the entire patent universe again." Candidate identifiers come
from Job 08 (WIPO)'s and Job 10 (EPO)'s ALREADY-MATERIALIZED
wipo.parquet/epo.parquet manifests (latest version per publication_number
only — never every historical version, the rule established when Job 04
/Crossref first had to consume another job's manifest as input), not
from a new CQL search of OPS. Each candidate carries an `upstream_source`
("wipo" or "epo") so provenance and per-authority coverage stay explicit
rather than inferred from a WO/EP prefix.

ROUND-1 FIX (2026-08-18): the initial version of this job read ONLY
epo.parquet, reasoning from a single live-tested WO publication (whose
description/claims/fulltext all 404'd while its biblio succeeded) that
"EPO OPS full-text coverage is a hard EP-only limitation" and therefore
globally excluding every WIPO candidate. This was an overreach from n=1:
EPO's own OPS Reference Guide documents full-text availability for
multiple authorities INCLUDING WO, not just EP — a single 404 proves
that ONE publication/artifact combination lacks full text, not that the
whole WO authority is unsupported by OPS. Fixed: WIPO candidates are
attempted exactly the same way EPO candidates are (same `_docdb_id`
reconstruction, same fetch_description/fetch_claims calls); a 404 is
recorded as `not_available` per (publication, artifact) pair — the
already-correct mechanism for "OPS confirms this specific thing isn't
there" — rather than being used to justify excluding an entire upstream
source in code. Real per-authority coverage is now an EMPIRICAL result
of this job's own attempts ledger, not an assumption baked into which
manifests get read.

WHY USPTO (Job 09) IS STILL NOT DUPLICATED HERE: verified live that
USPTO's own already-acquired SPEC-type documents (uspto_documents.parquet,
Job 09) are the as-filed Specification PDF, which already bundles
description + claims + abstract for the original filing — exactly the
raw evidence Prompt.md wants "downstream extraction" to have. Re-
downloading that content under a different table would be pure
duplication of Job 09's own work; Job 13 exists specifically to acquire
content Jobs 08/09/10 do NOT already have via their own materialization
(WIPO/EPO only fetch bibliographic data, not full text).

Two artifact types per candidate publication, EACH its own independent
content-version manifest entry (own content_hash/version/checkpoint,
`parent_record_id` pointing back to the upstream manifest's
publication_number — same "give a secondary artifact its own lifecycle"
pattern as SEC's exhibits / Europe PMC's full text): `description` (the
specification body text — numbered paragraphs, where Prompt.md's target
sections Examples/Experimental/IC50/etc. actually live) and `claims`
(claim text). No discovery ledger (same reasoning as Crossref/SEC's CIK
level: the candidate list is read directly from already-materialized
upstream manifests, not discovered via a live query) — just
patent_bioactivity_corpus.parquet (content-version manifest) and
patent_bioactivity_corpus_attempts.parquet (attempts ledger).

MATERIALIZATION mirrors Job 10 (EPO)'s fully-hardened design, applied
proactively: own `raw_records` checkpoint namespace per (publication,
artifact_type) pair, saved to disk immediately after every raw write;
skip-by-default once an artifact is successfully materialized requires
the ledger's own most-recent status already being resolved AND that
resolved attempt's recorded version matching the raw checkpoint's
CURRENT version (a mismatch is `pending_recovery`, routed through the
ordinary per-item loop rather than trusted as a safe fast-skip);
`--refresh` opts a run into re-verifying already-successful artifacts.
A 404 (OPS confirms no full text currently exists for this specific
publication/artifact) is recorded as `not_available` — an UNRESOLVED
status like `failed`, always retried on ordinary runs, NOT treated as
permanently terminal: staying conservative per the lesson from Job 05
(SEC)'s round-3 review ("don't treat a plain HTTP 404 as terminal"
unless the source's own metadata structurally guarantees permanence,
which OPS's fulltext-inquiry endpoint does not).

Every run's THIS-RUN outcome counts (success/skipped_unchanged/
not_available/failed) are tracked explicitly per upstream_source (see
`outcome_counts` below) so the written report can show real, separate
WIPO-vs-EPO coverage — an outcome must always sum to
success + skipped_unchanged + not_available + failed for the artifacts
actually attempted or fast-skipped this run.

`--since`/`--until` filter candidate SELECTION client-side by each
upstream manifest's own `publication_or_release_date` (there's no new
discovery here to filter — unlike a job with its own search, this only
restricts which already-materialized publications are considered as
candidates this run). `--resume` is a no-op beyond default behavior, for
the same reason as Crossref: candidate selection isn't windowed by any
cursor, so there's no separate incremental narrowing to do.

OPS's free-tier data quota is 4GB **per week** (EPO's own published OPS
page, https://www.epo.org/en/searching-for-patents/data/web-services/ops
— NOT 4GB/month, an error in this job's own initial version) — a real,
if generous, constraint specifically for this job since full-text
documents (tens to 100+ KB each) are far larger than a biblio fetch.
`result.notes` reports cumulative bytes downloaded this run so usage
against that budget can be monitored; no automatic throttling beyond the
existing RetryingClient rate limiting is implemented this round.
"""

from __future__ import annotations

import argparse
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.ops_client import BIBLIO_RATE_LIMIT, SEARCH_RATE_LIMIT, OPSClient
from jobs.patent_bioactivity_corpus.report import build_report

EPO_MANIFEST_PATH = Path("DATA") / "manifests" / "epo.parquet"
WIPO_MANIFEST_PATH = Path("DATA") / "manifests" / "wipo.parquet"
EXTRA_FIELDS = ["publication_number", "artifact_type", "application_number", "upstream_source"]
LICENSE_NOTE = "EPO OPS full-text data (description/claims); WIPO (WO) and EPO (EP) publications both attempted, per-authority coverage is empirical, see report."

RAW_NAMESPACE = "raw_records"
ARTIFACT_TYPES = ("description", "claims")

ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]

UNRESOLVED_STATUSES = {"failed", "not_available"}
RESOLVED_STATUSES = {"success", "skipped_unchanged"}

_PUBLICATION_NUMBER_RE = re.compile(r"^([A-Z]{2})(\d+)([A-Z]\d*)$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _docdb_id(publication_number: str) -> str | None:
    """'EP4789684A1' -> 'EP.4789684.A1' (the dot-separated form OPS's
    full-text endpoints need); None if publication_number doesn't match
    the expected country+digits+kind shape."""
    m = _PUBLICATION_NUMBER_RE.match(publication_number)
    if not m:
        return None
    country, doc_number, kind = m.groups()
    return f"{country}.{doc_number}.{kind}"


def _artifact_id(publication_number: str, artifact_type: str) -> str:
    return f"PATENTBIO_{publication_number}_{artifact_type.upper()}"


def _query_text(artifact: dict) -> str:
    """Single source of truth for this artifact's query_text -- used by
    BOTH the fast-skip loop and the real-fetch loop, so the same
    query_id never resolves to two different query_text values across
    manifest/attempts (the exact provenance bug Job 12's round-1 review
    caught)."""
    return f"OPS {artifact['artifact_type']} fetch for {artifact['docdb_id']}"


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="patent_bioactivity_corpus", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _artifact_manifest_row(
    publication_number: str, application_number: str | None, upstream_source: str, artifact_type: str,
    source_record_id: str, query_id: str, query_text: str, raw_path: Path, content_hash: str, version: int, now: str,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="patent_bioactivity_corpus",
        source_record_id=source_record_id,
        source_record_type=f"ops_patent_{artifact_type}",
        title=f"{artifact_type} text: {publication_number}",
        url=None,
        publication_or_release_date=None,
        retrieved_at=now,
        query_id=query_id,
        query_text=query_text,
        raw_file_path=str(raw_path),
        raw_format="xml",
        content_hash=content_hash,
        download_status="success",
        http_status=200,
        license_or_access_note=LICENSE_NOTE,
        parent_record_id=publication_number,
        version=version,
        notes=None,
        publication_number=publication_number,
        artifact_type=artifact_type,
        application_number=application_number,
        upstream_source=upstream_source,
    )


def _latest_attempt_by_id(attempts_path: Path) -> dict[str, dict]:
    if not attempts_path.exists():
        return {}
    df = pd.read_parquet(attempts_path)
    if df.empty:
        return {}
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    return {
        row["source_record_id"]: {"status": row["status"], "version": row["version"], "content_hash": row["content_hash"]}
        for _, row in latest.iterrows()
    }


def _classify_artifact_ids(
    all_ids: list, latest_attempts: dict, checkpoint_store, checkpoint,
) -> tuple:
    """Same pattern as jobs/epo/job.py's _classify_publication_ids: a
    resolved attempt (success/skipped_unchanged) is only safe to
    fast-skip if its own recorded version matches RAW_NAMESPACE's CURRENT
    version -- otherwise it's pending_recovery, routed through the
    ordinary per-item loop instead of trusted as a no-request skip."""
    resolved_ids: set = set()
    pending_recovery_ids: list = []
    for rid in all_ids:
        att = latest_attempts.get(rid)
        if not att or att["status"] not in RESOLVED_STATUSES:
            continue
        raw_state = checkpoint_store.get_record_state(checkpoint, rid, namespace=RAW_NAMESPACE)
        if raw_state is None:
            continue
        if att["version"] == raw_state["version"]:
            resolved_ids.add(rid)
        else:
            pending_recovery_ids.append(rid)
    return resolved_ids, sorted(pending_recovery_ids)


def _load_candidates_from_manifest(
    manifest_path: Path, upstream_source: str, since: str | None, until: str | None,
) -> list[dict]:
    """Every publication_number in an upstream job's manifest (Job 08/
    WIPO or Job 10/EPO), latest version only (Crossref's established
    rule for consuming another job's manifest as input), optionally
    date-filtered by --since/--until against that manifest's own
    publication_or_release_date."""
    if not manifest_path.exists():
        return []
    df = pd.read_parquet(manifest_path)
    if df.empty:
        return []
    latest = df.sort_values("version").groupby("source_record_id", as_index=False).tail(1)
    if since:
        latest = latest[latest["publication_or_release_date"].fillna("") >= since]
    if until:
        latest = latest[latest["publication_or_release_date"].fillna("9999-99-99") <= until]
    return [
        dict(
            publication_number=row["publication_number"], application_number=row.get("application_number"),
            upstream_source=upstream_source,
        )
        for _, row in latest.iterrows()
    ]


class PatentBioactivityCorpusJob(AcquisitionJob):
    name = "patent_bioactivity_corpus"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--epo-manifest", type=str, default=str(EPO_MANIFEST_PATH),
            help="Path to Job 10 (EPO)'s manifest to read EP publication candidates from.",
        )
        parser.add_argument(
            "--wipo-manifest", type=str, default=str(WIPO_MANIFEST_PATH),
            help="Path to Job 08 (WIPO)'s manifest to read WO publication candidates from.",
        )
        parser.add_argument(
            "--refresh", action="store_true",
            help=(
                "Re-fetch and hash-compare EVERY candidate artifact, including ones already "
                "successfully materialized, to pick up rare post-publication corrections (run "
                "periodically, not on every incremental run)."
            ),
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        load_dotenv()
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        consumer_key = os.environ.get("OPS_CONSUMER_KEY")
        consumer_secret = os.environ.get("OPS_CONSUMER_SECRET")
        if not consumer_key or not consumer_secret:
            raise RuntimeError(
                "OPS_CONSUMER_KEY/OPS_CONSUMER_SECRET must be set (free registration at "
                "https://developers.epo.org/) — same OPS account Jobs 08/10 use."
            )
        client = OPSClient(
            search_client=RetryingClient(RateLimiter(SEARCH_RATE_LIMIT)),
            biblio_client=RetryingClient(RateLimiter(BIBLIO_RATE_LIMIT)),
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
        )

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: candidate selection isn't windowed by any "
                "cursor (every active WIPO/EPO publication in the upstream manifests is considered every "
                "run), so there's no separate incremental-window narrowing to do."
            )

        candidates = (
            _load_candidates_from_manifest(Path(args.wipo_manifest), "wipo", args.since, args.until)
            + _load_candidates_from_manifest(Path(args.epo_manifest), "epo", args.since, args.until)
        )
        if not candidates:
            raise RuntimeError(
                f"no publication candidates found in {args.wipo_manifest} or {args.epo_manifest} "
                "(have Jobs 08/WIPO and 10/EPO been run yet? or did --since/--until exclude everything?)"
            )

        now = _now_iso()
        run_id = now

        # Every candidate publication contributes up to 2 artifact ids
        # (description, claims). Publications whose publication_number
        # doesn't match the expected docdb shape are skipped with a
        # warning (should not happen for real WIPO/EPO manifest data,
        # but fail loud rather than silently, not crash the whole run).
        artifact_by_id: dict[str, dict] = {}
        for cand in candidates:
            docdb_id = _docdb_id(cand["publication_number"])
            if docdb_id is None:
                logger.warning("publication_number=%s doesn't match expected docdb shape -- skipped", cand["publication_number"])
                continue
            for artifact_type in ARTIFACT_TYPES:
                source_record_id = _artifact_id(cand["publication_number"], artifact_type)
                artifact_by_id[source_record_id] = dict(
                    publication_number=cand["publication_number"],
                    application_number=cand["application_number"],
                    upstream_source=cand["upstream_source"],
                    artifact_type=artifact_type,
                    docdb_id=docdb_id,
                )

        result.queries_run = len(candidates)
        result.records_discovered = len(artifact_by_id)

        attempts_path = output_dir / "manifests" / "patent_bioactivity_corpus_attempts.parquet"
        latest_attempts = _latest_attempt_by_id(attempts_path)
        unresolved_ids = {rid for rid, att in latest_attempts.items() if att["status"] in UNRESOLVED_STATUSES}

        all_ids = list(artifact_by_id.keys())
        resolved_ids, pending_recovery_ids = _classify_artifact_ids(all_ids, latest_attempts, checkpoint_store, checkpoint)
        pending_recovery_id_set = set(pending_recovery_ids)
        fresh_ids = sorted(
            rid for rid in all_ids
            if rid not in resolved_ids and rid not in unresolved_ids and rid not in pending_recovery_id_set
        )
        backlog_ids = sorted(rid for rid in all_ids if rid in unresolved_ids)
        already_skipped_ids = sorted(resolved_ids)

        if args.refresh:
            ordered_work = fresh_ids + backlog_ids + pending_recovery_ids + already_skipped_ids
            fast_skip_ids: list = []
        else:
            ordered_work = fresh_ids + backlog_ids + pending_recovery_ids
            fast_skip_ids = already_skipped_ids
        target_ids = ordered_work[: args.limit] if args.limit else ordered_work

        candidates_by_source = Counter(cand["upstream_source"] for cand in candidates)

        if args.dry_run:
            candidates_by_source_str = ", ".join(f"{source}: {count}" for source, count in candidates_by_source.items())
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} candidate artifacts "
                f"across {len(candidates)} publications ({candidates_by_source_str}) "
                f"({len(fresh_ids)} never attempted, {len(backlog_ids)} unresolved retries, "
                f"{len(pending_recovery_ids)} pending recovery, "
                f"{len(fast_skip_ids)} already successful and skipped with no request"
                + (", 0 refresh re-checks (--refresh not set)" if not args.refresh else "")
                + ")"
            )
            return result

        manifest_path = output_dir / "manifests" / "patent_bioactivity_corpus.parquet"
        content_rows = []
        attempt_rows = []
        bytes_downloaded_this_run = 0
        not_available_this_run = 0
        # (upstream_source, outcome) -> count, THIS run only -- lets the
        # report show real, separate WIPO-vs-EPO coverage instead of an
        # assumption baked into which manifests get read (round-1 fix).
        outcome_counts: Counter = Counter()

        already_skipped_id_set = set(already_skipped_ids)

        for source_record_id in fast_skip_ids:
            result.records_skipped_unchanged += 1
            artifact = artifact_by_id[source_record_id]
            outcome_counts[(artifact["upstream_source"], "skipped_unchanged")] += 1
            query_id = source_record_id
            query_text = _query_text(artifact)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id, namespace=RAW_NAMESPACE)
            attempt_rows.append(
                _record_row(
                    source_record_id, run_id, now, "skipped_unchanged", query_id, query_text,
                    content_hash=raw_prior_state["content_hash"] if raw_prior_state else None,
                    version=raw_prior_state["version"] if raw_prior_state else None,
                )
            )

        for source_record_id in target_ids:
            artifact = artifact_by_id[source_record_id]
            publication_number = artifact["publication_number"]
            upstream_source = artifact["upstream_source"]
            artifact_type = artifact["artifact_type"]
            docdb_id = artifact["docdb_id"]
            query_id = source_record_id
            query_text = _query_text(artifact)

            try:
                fetch_fn = client.fetch_description if artifact_type == "description" else client.fetch_claims
                raw_bytes = fetch_fn(docdb_id)
            except requests.RequestException as exc:
                logger.warning("publication=%s artifact=%s fetch failed: %s", publication_number, artifact_type, exc)
                failure_logger.info("publication=%s artifact=%s error=%s", publication_number, artifact_type, exc)
                result.records_failed += 1
                outcome_counts[(upstream_source, "failed")] += 1
                attempt_rows.append(_record_row(source_record_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if raw_bytes is None:
                logger.info("publication=%s artifact=%s: no full text available (OPS 404)", publication_number, artifact_type)
                not_available_this_run += 1
                outcome_counts[(upstream_source, "not_available")] += 1
                attempt_rows.append(
                    _record_row(source_record_id, run_id, now, "not_available", query_id, query_text, http_status=404, error="not_available")
                )
                continue

            content_hash = sha256_bytes(raw_bytes)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id, namespace=RAW_NAMESPACE)
            raw_dir = output_dir / "raw" / "patent_bioactivity_corpus" / publication_number

            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                version = raw_prior_state["version"]
                raw_path = raw_dir / f"{artifact_type}_v{version}.xml"
                if source_record_id in already_skipped_id_set:
                    result.records_skipped_unchanged += 1
                    outcome_counts[(upstream_source, "skipped_unchanged")] += 1
                    attempt_rows.append(
                        _record_row(
                            source_record_id, run_id, now, "skipped_unchanged", query_id, query_text,
                            content_hash=content_hash, version=version,
                        )
                    )
                    continue
                # Else: fresh/backlog/pending_recovery whose content
                # happens to match a PRIOR fetch that was never
                # successfully materialized -- fall through and recover,
                # reusing the existing raw file rather than rewriting it.
            else:
                version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"{artifact_type}_v{version}.xml"
                raw_path.write_bytes(raw_bytes)
                checkpoint_store.set_record_state(checkpoint, source_record_id, content_hash, version, now, namespace=RAW_NAMESPACE)
                checkpoint_store.save(checkpoint)

            bytes_downloaded_this_run += len(raw_bytes)
            result.records_downloaded += 1
            outcome_counts[(upstream_source, "success")] += 1
            attempt_rows.append(
                _record_row(source_record_id, run_id, now, "success", query_id, query_text, content_hash=content_hash, version=version)
            )
            content_rows.append(
                _artifact_manifest_row(
                    publication_number, artifact["application_number"], upstream_source, artifact_type, source_record_id,
                    query_id, query_text, raw_path, content_hash, version, now,
                )
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        result.notes.append(
            f"this run: {result.records_downloaded} success, {result.records_skipped_unchanged} skipped_unchanged, "
            f"{not_available_this_run} not_available, {result.records_failed} failed "
            f"({result.records_downloaded + result.records_skipped_unchanged + not_available_this_run + result.records_failed} "
            f"total attempted/fast-skipped outcomes)."
        )
        if bytes_downloaded_this_run:
            result.notes.append(
                f"{bytes_downloaded_this_run / (1024 * 1024):.2f} MB downloaded this run "
                "(OPS's free-tier quota is 4GB/week across ALL OPS usage, not just this job -- monitor cumulative usage)."
            )

        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / "patent_bioactivity_corpus.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(
                result, manifest_df, all_ids, fresh_ids, backlog_ids, pending_recovery_ids, fast_skip_ids,
                candidates_by_source, outcome_counts, not_available_this_run,
            ),
            encoding="utf-8",
        )

        return result
