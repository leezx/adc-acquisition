"""Job 14: publication bioactivity evidence corpus (Prompt.md section 18,
"JOB 14", execution order section 29).

SECOND-PASS literature acquisition -- Prompt.md's input list for this job
is "PMIDs / PMCIDs / DOIs / known ADC aliases", not a new literature
search: Jobs 01 (PubMed), 02 (Europe PMC) and 04 (Crossref) already own
discovery. This job reconciles DOIs already materialized by those three
jobs' own manifests (latest version per record only -- the rule
established when Job 04/Crossref first had to consume another job's
manifest as input, reused again by Job 13) and, for each one, tries to
acquire a legally-accessible open-access copy likely to contain the
bioactivity measurements Prompt.md lists (IC50/EC50/DC50, tumor
inhibition, response rate, PK/PD, toxicity, ...). DO NOT perform final
structured extraction here (Prompt.md is explicit) -- this job only
acquires raw evidence.

MECHANISM, established from research before writing any code (explicitly
to avoid repeating Job 13's round-1 mistake of generalizing from a single
test point): Europe PMC (Job 02) already fetches full-text JATS XML, but
ONLY for records ITS OWN search queries discovered AND that are flagged
is_open_access with a pmcid -- verified live that the repo's actual
europe_pmc_fulltext.parquet currently has ZERO rows (none of the small
demo set happened to be OA), and that neither PubMed's nor Crossref's own
manifests fetch full text at all (grep-confirmed: their EXTRA_FIELDS are
bibliographic/abstract only). Unpaywall (https://unpaywall.org, live-
verified free API, 100,000 calls/day, keyed by DOI, metadata-only response
naming OA locations across publisher/repository/preprint hosts) closes a
GENUINELY separate gap: DOIs Job 02 never happened to discover at all, and
DOIs where Europe PMC's own is_open_access flag is false/absent but a
legal OA copy exists elsewhere (hybrid OA, institutional repository,
etc.). Its coverage is empirically NOT a subset of Europe PMC's OA subset.

Two-stage acquisition per DOI, mirroring Job 13's "confirm absence is a
real status, don't crash on network noise" shape: (1) an Unpaywall lookup
by DOI (metadata: is_oa, oa_status, an ordered list of OA locations) --
DOI unknown to Unpaywall, or known-but-not-OA, is `not_available` (a
genuine negative, never treated as permanent, same conservatism as
Job 13's OPS 404 / Job 05/SEC's round-3 lesson); (2) a content fetch of
the actual bytes from the best OA location, falling back through the rest
of Unpaywall's location list if the first one fails (a landing page can
403 a bot while a repository mirror of the SAME work succeeds -- trying
only the single "best" location would under-count real availability,
Job 13's "attempt broadly, don't generalize from n=1" lesson applied here
too). Content fetch failures across every offered location are `failed`
(transient/access issue), NOT `not_available` (Unpaywall DID confirm an OA
copy exists somewhere; we just couldn't reach it this run).

publication_bioactivity_corpus.parquet is a content-version manifest keyed
by DOI (source_record_id == doi, same identifier scheme Crossref already
uses); publication_bioactivity_corpus_attempts.parquet is its attempts
ledger. No discovery ledger -- same reasoning as Crossref/Job 13: the
candidate list is read directly from already-materialized upstream
manifests, not discovered via a live query of this job's own.

DEDUP AGAINST JOB 02: a DOI whose Europe PMC full text is ALREADY
successfully materialized (europe_pmc_fulltext.parquet has a resolved row
for it, joined via pmcid -> europe_pmc.parquet's own doi field) is
excluded from this job's candidate set -- re-downloading the same
article's OA full text under a second table would be pure duplication of
Job 02's own work, the identical "don't re-acquire what an existing job
already legitimately has" precedent as Job 13's USPTO exclusion. This is
checked from real data (not assumed): the count of excluded DOIs is
reported every run, and is currently 0 against this repo's committed
demo manifests (europe_pmc_fulltext.parquet has zero rows there).

DOI IDENTITY: DOIs are case-insensitive by specification -- caught live
against this repo's OWN committed data before this job was ever run for
real: PubMed's manifest records one work's doi as `10.1007/BF01741596`
while Crossref's manifest records the SAME work as `10.1007/bf01741596`
(Crossref itself lowercases the doi field it returns). Every doi read from
an upstream manifest is normalized (stripped + lowercased, see
`_normalize_doi`) before it becomes a candidate identity/source_record_id
-- otherwise this job would silently fetch and store the same OA article
twice under two different manifest rows, the same "same entity, two
spellings" conflation class Job 12 (release identity) and Job 13
(publication_number assumptions) already hit.

MATERIALIZATION mirrors Job 13's fully-hardened design: own `raw_records`
checkpoint namespace, skip-by-default once a DOI's fulltext is
successfully materialized requires the ledger's own most-recent status
already being resolved AND that resolved attempt's recorded version
matching the raw checkpoint's CURRENT version (a mismatch is
`pending_recovery`); `--refresh` opts a run into re-verifying already-
successful DOIs (a re-run of BOTH the Unpaywall lookup and the content
fetch, since either could have changed).

`--since`/`--until` filter candidate SELECTION client-side by each
upstream manifest's own `publication_or_release_date` (same as Job 13;
there's no new discovery here to filter). `--resume` is a no-op beyond
default behavior for the same reason as Crossref/Job 13: candidate
selection isn't windowed by any cursor.

query_id == source_record_id == doi (one query per DOI, same scheme as
the artifact ids in Job 13); query_text is built by a single shared
`_query_text()` helper used by BOTH the fast-skip loop and the real-fetch
loop, so the same query_id never resolves to two different query_text
values across manifest/attempts -- the recurring provenance bug Job 12's
round-1 review first caught, then Job 13's round-1 review caught again.

Every run's THIS-RUN outcome counts (success/skipped_unchanged/
not_available/failed) must sum to the number of DOIs actually attempted or
fast-skipped this run -- same invariant as Job 13, applied proactively.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.html_utils import infer_raw_format
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.web_snapshot_client import WebSnapshotClient
from jobs.publication_bioactivity_corpus.client import RATE_LIMIT, UnpaywallClient
from jobs.publication_bioactivity_corpus.report import build_report

PUBMED_MANIFEST_PATH = Path("DATA") / "manifests" / "pubmed.parquet"
EUROPE_PMC_MANIFEST_PATH = Path("DATA") / "manifests" / "europe_pmc.parquet"
CROSSREF_MANIFEST_PATH = Path("DATA") / "manifests" / "crossref.parquet"
EUROPE_PMC_FULLTEXT_MANIFEST_PATH = Path("DATA") / "manifests" / "europe_pmc_fulltext.parquet"

EXTRA_FIELDS = ["doi", "oa_status", "host_type", "source_location_url", "upstream_sources"]
LICENSE_NOTE_TEMPLATE = (
    "Unpaywall-identified legal open-access copy (host_type={host_type}, oa_status={oa_status}); "
    "publisher paywalls are never bypassed -- only Unpaywall-confirmed OA locations are fetched."
)

CONTENT_RATE_LIMIT = 0.5  # req/s -- same conservative default as Jobs 11/12's WebSnapshotClient (arbitrary, uncoordinated publisher/repository hosts).
RAW_NAMESPACE = "raw_records"

ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]

UNRESOLVED_STATUSES = {"failed", "not_available"}
RESOLVED_STATUSES = {"success", "skipped_unchanged"}

UPSTREAM_MANIFESTS = ("pubmed", "europe_pmc", "crossref")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _query_text(doi: str) -> str:
    """Single source of truth for this DOI's query_text -- used by BOTH the
    fast-skip loop and the real-fetch loop, so the same query_id never
    resolves to two different query_text values across manifest/attempts
    (the provenance bug Job 12's round-1 review caught, recurring at
    Job 13, guarded against proactively here)."""
    return f"Unpaywall OA lookup and content fetch for doi={doi}"


def _record_row(
    doi: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="publication_bioactivity_corpus", source_record_id=doi, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _content_manifest_row(
    doi: str, oa_status: str | None, host_type: str | None, source_location_url: str | None,
    upstream_sources: set, query_id: str, query_text: str, raw_path: Path, raw_format: str,
    content_hash: str, version: int, now: str,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="publication_bioactivity_corpus",
        source_record_id=doi,
        source_record_type="unpaywall_oa_fulltext",
        title=f"OA full text: {doi}",
        url=source_location_url,
        publication_or_release_date=None,
        retrieved_at=now,
        query_id=query_id,
        query_text=query_text,
        raw_file_path=str(raw_path),
        raw_format=raw_format,
        content_hash=content_hash,
        download_status="success",
        http_status=200,
        license_or_access_note=LICENSE_NOTE_TEMPLATE.format(host_type=host_type, oa_status=oa_status),
        parent_record_id=None,
        version=version,
        notes=None,
        doi=doi,
        oa_status=oa_status,
        host_type=host_type,
        source_location_url=source_location_url,
        upstream_sources=",".join(sorted(upstream_sources)),
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


def _classify_ids(all_ids: list, latest_attempts: dict, checkpoint_store, checkpoint) -> tuple:
    """Same pattern as jobs/patent_bioactivity_corpus/job.py's
    _classify_artifact_ids: a resolved attempt (success/skipped_unchanged)
    is only safe to fast-skip if its own recorded version matches
    RAW_NAMESPACE's CURRENT version -- otherwise it's pending_recovery,
    routed through the ordinary per-item loop instead of trusted as a
    no-request skip."""
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


def _normalize_doi(doi: str) -> str:
    """DOIs are case-insensitive by specification (https://www.doi.org/doi_handbook/2_Numbering.html#2.4)
    -- verified live against this repo's OWN committed data: PubMed's
    manifest has doi=10.1007/BF01741596 for the same work Crossref's
    manifest records as doi=10.1007/bf01741596 (Crossref itself lowercases
    the doi field it returns). Without normalizing, this job would treat
    those as two different candidates and fetch/store the same OA article
    twice under two identity keys -- the exact "same entity, two spellings"
    conflation class this repo has hit before (release/query identity in
    Job 12, publication_number casing assumptions in Job 13)."""
    return doi.strip().lower()


def _load_doi_candidates_from_manifest(manifest_path: Path, upstream_source: str, since: str | None, until: str | None) -> list[dict]:
    """Every non-null doi in an upstream job's manifest (Job 01/PubMed,
    Job 02/Europe PMC, or Job 04/Crossref), latest version only, optionally
    date-filtered by --since/--until against that manifest's own
    publication_or_release_date."""
    if not manifest_path.exists():
        return []
    df = pd.read_parquet(manifest_path)
    if df.empty or "doi" not in df.columns:
        return []
    latest = df.sort_values("version").groupby("source_record_id", as_index=False).tail(1)
    if since:
        latest = latest[latest["publication_or_release_date"].fillna("") >= since]
    if until:
        latest = latest[latest["publication_or_release_date"].fillna("9999-99-99") <= until]
    latest = latest[latest["doi"].notna() & (latest["doi"].astype(str).str.strip() != "")]
    return [
        dict(
            doi=_normalize_doi(str(row["doi"])),
            publication_or_release_date=row.get("publication_or_release_date"),
            upstream_source=upstream_source,
        )
        for _, row in latest.iterrows()
    ]


def _dois_with_resolved_europe_pmc_fulltext(fulltext_manifest_path: Path, europe_pmc_manifest_path: Path) -> set:
    """DOIs whose Job 02 (Europe PMC) full text has already been
    successfully materialized at least once -- europe_pmc_fulltext.parquet
    only ever gains a content row on a successful fetch (an unchanged
    rerun doesn't write a new row, see jobs/europe_pmc/job.py's
    _process_fulltext), so any pmcid present there has resolved full text.
    Joined back to a DOI via europe_pmc.parquet's own doi field (latest
    version per metadata record only)."""
    if not fulltext_manifest_path.exists() or not europe_pmc_manifest_path.exists():
        return set()
    ft_df = pd.read_parquet(fulltext_manifest_path)
    epmc_df = pd.read_parquet(europe_pmc_manifest_path)
    if ft_df.empty or epmc_df.empty:
        return set()
    latest_epmc = epmc_df.sort_values("version").groupby("source_record_id", as_index=False).tail(1)
    pmcid_to_doi = {
        row["pmcid"]: _normalize_doi(str(row["doi"]))
        for _, row in latest_epmc.iterrows()
        if row.get("pmcid") and row.get("doi")
    }
    resolved_pmcids = set(ft_df["source_record_id"].dropna().unique())
    return {pmcid_to_doi[p] for p in resolved_pmcids if pmcid_to_doi.get(p)}


class PublicationBioactivityCorpusJob(AcquisitionJob):
    name = "publication_bioactivity_corpus"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--pubmed-manifest", type=str, default=str(PUBMED_MANIFEST_PATH),
            help="Path to Job 01 (PubMed)'s manifest to read DOI candidates from.",
        )
        parser.add_argument(
            "--europe-pmc-manifest", type=str, default=str(EUROPE_PMC_MANIFEST_PATH),
            help="Path to Job 02 (Europe PMC)'s manifest to read DOI candidates from.",
        )
        parser.add_argument(
            "--crossref-manifest", type=str, default=str(CROSSREF_MANIFEST_PATH),
            help="Path to Job 04 (Crossref)'s manifest to read DOI candidates from.",
        )
        parser.add_argument(
            "--europe-pmc-fulltext-manifest", type=str, default=str(EUROPE_PMC_FULLTEXT_MANIFEST_PATH),
            help="Path to Job 02's full-text manifest, used only to exclude DOIs Job 02 already resolved.",
        )
        parser.add_argument(
            "--contact-email", type=str, default=None,
            help="Contact email for Unpaywall's API (also read from UNPAYWALL_CONTACT_EMAIL env var). "
            "Unpaywall rejects placeholder-looking addresses with HTTP 422.",
        )
        parser.add_argument(
            "--refresh", action="store_true",
            help=(
                "Re-run BOTH the Unpaywall lookup and the content fetch for EVERY candidate DOI, including "
                "ones already successfully materialized, to pick up newly-available OA copies or corrected "
                "OA status (run periodically, not on every incremental run)."
            ),
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        load_dotenv()
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        email = args.contact_email or os.environ.get("UNPAYWALL_CONTACT_EMAIL")
        if not email:
            raise RuntimeError(
                "UNPAYWALL_CONTACT_EMAIL (or --contact-email) must be set to a real-looking email address -- "
                "Unpaywall's API rejects placeholder addresses (e.g. test@example.com) with HTTP 422. "
                "Free, no registration required: https://unpaywall.org/products/api"
            )
        unpaywall_client = UnpaywallClient(RetryingClient(RateLimiter(RATE_LIMIT)), email=email)
        content_client = WebSnapshotClient(RetryingClient(RateLimiter(CONTENT_RATE_LIMIT)))

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: candidate selection isn't windowed by any "
                "cursor (every DOI in the upstream manifests is considered every run), so there's no "
                "separate incremental-window narrowing to do."
            )

        candidates = (
            _load_doi_candidates_from_manifest(Path(args.pubmed_manifest), "pubmed", args.since, args.until)
            + _load_doi_candidates_from_manifest(Path(args.europe_pmc_manifest), "europe_pmc", args.since, args.until)
            + _load_doi_candidates_from_manifest(Path(args.crossref_manifest), "crossref", args.since, args.until)
        )
        if not candidates:
            raise RuntimeError(
                f"no DOI candidates found in {args.pubmed_manifest}, {args.europe_pmc_manifest}, or "
                f"{args.crossref_manifest} (have Jobs 01/02/04 been run yet? or did --since/--until "
                "exclude everything?)"
            )

        candidates_by_source = Counter(c["upstream_source"] for c in candidates)

        doi_info: dict[str, dict] = {}
        for c in candidates:
            info = doi_info.setdefault(c["doi"], {"upstream_sources": set(), "publication_or_release_date": None})
            info["upstream_sources"].add(c["upstream_source"])
            if info["publication_or_release_date"] is None and c["publication_or_release_date"]:
                info["publication_or_release_date"] = c["publication_or_release_date"]

        already_covered_dois = _dois_with_resolved_europe_pmc_fulltext(
            Path(args.europe_pmc_fulltext_manifest), Path(args.europe_pmc_manifest),
        )
        already_covered_count = sum(1 for doi in doi_info if doi in already_covered_dois)
        all_ids = sorted(doi for doi in doi_info if doi not in already_covered_dois)

        result.queries_run = len(candidates)
        result.records_discovered = len(all_ids)

        attempts_path = output_dir / "manifests" / "publication_bioactivity_corpus_attempts.parquet"
        latest_attempts = _latest_attempt_by_id(attempts_path)
        unresolved_ids = {rid for rid, att in latest_attempts.items() if att["status"] in UNRESOLVED_STATUSES}

        resolved_ids, pending_recovery_ids = _classify_ids(all_ids, latest_attempts, checkpoint_store, checkpoint)
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

        if args.dry_run:
            candidates_by_source_str = ", ".join(f"{source}: {count}" for source, count in candidates_by_source.items())
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} candidate DOIs "
                f"({candidates_by_source_str} upstream mentions, {already_covered_count} excluded as already "
                f"covered by Job 02's own resolved full text) "
                f"({len(fresh_ids)} never attempted, {len(backlog_ids)} unresolved retries, "
                f"{len(pending_recovery_ids)} pending recovery, "
                f"{len(fast_skip_ids)} already successful and skipped with no request"
                + (", 0 refresh re-checks (--refresh not set)" if not args.refresh else "")
                + ")"
            )
            return result

        now = _now_iso()
        run_id = now

        manifest_path = output_dir / "manifests" / "publication_bioactivity_corpus.parquet"
        content_rows = []
        attempt_rows = []
        not_available_this_run = 0
        outcome_counts: Counter = Counter()

        already_skipped_id_set = set(already_skipped_ids)

        for doi in fast_skip_ids:
            result.records_skipped_unchanged += 1
            outcome_counts["skipped_unchanged"] += 1
            query_id = doi
            query_text = _query_text(doi)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, doi, namespace=RAW_NAMESPACE)
            attempt_rows.append(
                _record_row(
                    doi, run_id, now, "skipped_unchanged", query_id, query_text,
                    content_hash=raw_prior_state["content_hash"] if raw_prior_state else None,
                    version=raw_prior_state["version"] if raw_prior_state else None,
                )
            )

        for doi in target_ids:
            query_id = doi
            query_text = _query_text(doi)

            try:
                unpaywall_result = unpaywall_client.lookup(doi)
            except requests.RequestException as exc:
                logger.warning("doi=%s Unpaywall lookup failed: %s", doi, exc)
                failure_logger.info("doi=%s error=%s", doi, exc)
                result.records_failed += 1
                outcome_counts["failed"] += 1
                attempt_rows.append(_record_row(doi, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if unpaywall_result is None or not unpaywall_result.is_oa or not unpaywall_result.locations:
                oa_status = unpaywall_result.oa_status if unpaywall_result else None
                logger.info("doi=%s: no OA copy available (Unpaywall oa_status=%s)", doi, oa_status)
                not_available_this_run += 1
                outcome_counts["not_available"] += 1
                attempt_rows.append(
                    _record_row(doi, run_id, now, "not_available", query_id, query_text, http_status=404, error="not_available")
                )
                continue

            raw_bytes = None
            used_location = None
            used_url = None
            used_content_type = None
            fetch_errors = []
            for location in unpaywall_result.locations:
                candidate_url = location.url_for_pdf or location.url
                if not candidate_url:
                    continue
                try:
                    response = content_client.fetch(candidate_url)
                except requests.RequestException as exc:
                    fetch_errors.append(f"{candidate_url}: {exc}")
                    continue
                if response.status_code != 200 or not response.content:
                    fetch_errors.append(f"{candidate_url}: HTTP {response.status_code}")
                    continue
                raw_bytes = response.content
                used_location = location
                used_url = candidate_url
                used_content_type = response.headers.get("Content-Type")
                break

            if raw_bytes is None:
                error = "; ".join(fetch_errors[:3]) or "no fetchable OA location URL"
                logger.warning("doi=%s: Unpaywall confirmed an OA copy but content fetch failed: %s", doi, error)
                failure_logger.info("doi=%s error=%s", doi, error)
                result.records_failed += 1
                outcome_counts["failed"] += 1
                attempt_rows.append(_record_row(doi, run_id, now, "failed", query_id, query_text, error=error))
                continue

            content_hash = sha256_bytes(raw_bytes)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, doi, namespace=RAW_NAMESPACE)
            raw_format = infer_raw_format(used_content_type, used_url)
            raw_dir = output_dir / "raw" / "publication_bioactivity_corpus" / doi.replace("/", "_")

            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                version = raw_prior_state["version"]
                raw_path = raw_dir / f"v{version}.{raw_format}"
                if doi in already_skipped_id_set:
                    result.records_skipped_unchanged += 1
                    outcome_counts["skipped_unchanged"] += 1
                    attempt_rows.append(
                        _record_row(doi, run_id, now, "skipped_unchanged", query_id, query_text, content_hash=content_hash, version=version)
                    )
                    continue
                # Else: fresh/backlog/pending_recovery whose content
                # happens to match a PRIOR fetch that was never
                # successfully materialized -- fall through and recover,
                # reusing the existing raw file rather than rewriting it.
            else:
                version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.{raw_format}"
                raw_path.write_bytes(raw_bytes)
                checkpoint_store.set_record_state(checkpoint, doi, content_hash, version, now, namespace=RAW_NAMESPACE)
                checkpoint_store.save(checkpoint)

            result.records_downloaded += 1
            outcome_counts["success"] += 1
            attempt_rows.append(
                _record_row(doi, run_id, now, "success", query_id, query_text, content_hash=content_hash, version=version)
            )
            content_rows.append(
                _content_manifest_row(
                    doi, unpaywall_result.oa_status, used_location.host_type, used_url,
                    doi_info[doi]["upstream_sources"], query_id, query_text, raw_path, raw_format,
                    content_hash, version, now,
                )
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        total_outcomes = result.records_downloaded + result.records_skipped_unchanged + not_available_this_run + result.records_failed
        result.notes.append(
            f"this run: {result.records_downloaded} success, {result.records_skipped_unchanged} skipped_unchanged, "
            f"{not_available_this_run} not_available, {result.records_failed} failed "
            f"({total_outcomes} total attempted/fast-skipped outcomes)."
        )
        if already_covered_count:
            result.notes.append(
                f"{already_covered_count} candidate DOIs excluded: already covered by Job 02's own resolved "
                "Europe PMC full text (avoiding pure duplication of that job's work)."
            )

        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / "publication_bioactivity_corpus.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(
                result, manifest_df, all_ids, fresh_ids, backlog_ids, pending_recovery_ids, fast_skip_ids,
                candidates_by_source, outcome_counts, not_available_this_run, already_covered_count,
            ),
            encoding="utf-8",
        )

        return result
