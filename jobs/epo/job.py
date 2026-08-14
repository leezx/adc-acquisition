"""Job 10: EPO patent acquisition (Prompt.md section 9, execution order
section 29).

Uses EPO's own Open Patent Services (OPS) — the same official API Job 08
(WIPO) uses, since WIPO PATENTSCOPE has no usable public API of its own
(see adc_acquisition/ops_client.py's module docstring for that rationale).
This job queries OPS filtered to EP-prefixed publications via `pn=EP`
instead of Job 08's `pn=WO` — an architecturally independent job with its
own query registry (configs/epo_queries.yaml), own query_id/provenance
namespace, and own manifest/discovery/attempts triple (epo.parquet/
epo_discovery.parquet/epo_attempts.parquet), sharing only the
already-tested, source-agnostic OPS client (adc_acquisition/ops_client.py)
and response parser (adc_acquisition/ops_parser.py) — no EPO-specific
client/parser code exists, so this job has no separate client.py/parser.py
of its own (unlike Job 08, whose client.py/parser.py are now thin
re-export shims onto the same shared modules, kept for import-path
backward compatibility with its own already-merged tests).

Discovery: configs/epo_queries.yaml's 5 CQL queries (the same Prompt.md
search concepts Job 08/USPTO use), each verified live to return well
under OPS's 2000-total-result access cap. Search only returns
(family_id, country, doc_number, kind) per hit — not bibliographic data —
so discovery and materialization are naturally two different OPS calls,
same shape as every other two-phase discovery job in this repo.

Three tables: epo.parquet (publication content-version manifest, raw
biblio XML preserved verbatim, keyed by publication_number e.g.
"EP4789684A1"), epo_discovery.parquet (every (publication, query, run)
triple, written unconditionally right after all queries' search sweeps
complete and BEFORE any biblio fetch is attempted), epo_attempts.parquet
(every fetch attempt: success/skipped_unchanged/failed/parse_failed).

DESIGN MIRRORS JOB 08 (WIPO) EXACTLY, reused unmodified rather than
re-derived — confirmed live (2026-08-14) that OPS's EP-prefixed biblio
response is the byte-identical exchange-document schema WO-prefixed
responses use, so every WIPO design decision applies here for the same
underlying reason, not by coincidence:
- Once a publication_number is successfully materialized, its OPS record
  is skipped WITHOUT a request by default (efficiency default, not a
  permanence claim — EPO OPS's own terms note corrections do get
  incorporated into DOCDB data over time, same as WIPO). `--refresh` opts
  a run into re-fetching/hash-comparing every discovered publication
  (including already-successful ones), versioning on genuine change.
- The skip decision requires BOTH unchanged raw bytes (RAW_NAMESPACE
  checkpoint) AND the attempts ledger's own most-recent status already
  being resolved (success or skipped_unchanged) — not hash match alone
  (the exact distinction Job 09/USPTO's round-1 review had to correct).
  Unchanged bytes with an unresolved last attempt (parse_failed, or no
  attempt recorded due to a lost end-of-run flush) fall through to reuse
  the existing raw file and retry parsing, rather than being misclassified
  skipped_unchanged forever.
- Raw XML is persisted, and RAW_NAMESPACE's checkpoint state is saved to
  disk IMMEDIATELY, before parsing is attempted (RAW FETCH -> RAW SNAPSHOT
  -> CHECKPOINT SAVED TO DISK -> PARSE).
- `--since`/`--until` apply server-side via OPS's own `pd within
  "YYYYMMDD,YYYYMMDD"` CQL filter; `--resume` (the implicit cursor) does
  NOT narrow the search this way, for the same reason as every other job
  here (an unresolved backlog item predating the cursor must stay
  discoverable).
- `--limit` prioritizes never-attempted (fresh) over previously-failed
  (backlog) over already-successful-under-refresh (reverify, strictly
  last).

ONE genuine EPO-specific live finding DOES differentiate this job's query
registry from WIPO's, discovered via ~45 minutes of isolated A/B testing
(2026-08-14): OPS's `ti=` (title) field, searched with a quoted
multi-word phrase and restricted to `pn=EP`, reproducibly returns HTTP 500
`SERVER.DomainAccess` at any Range span greater than 1 — while the
identical phrase search on `ab=` (abstract) succeeds fine, a single-word
`ti=` search (no phrase quoting) succeeds fine, and the byte-identical
`pn=WO and ti="..."` pattern Job 08 already runs in production is
unaffected. Ruled out via direct testing: clause ordering, OR-combination
itself, and general OPS system load (concurrent non-phrase `pn=EP`
queries at the same Range succeeded throughout the same test window). See
configs/epo_queries.yaml's header comment for the full investigation.
Consequence: the two "antibody-drug conjugate(s)" phrase queries search
the ABSTRACT ONLY for EP scope (not title+abstract like WIPO) — a
disclosed, live-verified coverage gap (see jobs/epo/report.py), not a
silently-forced fit. The immunoconjugate query is unaffected (single
word, not a phrase) and still searches both fields.
"""

from __future__ import annotations

import argparse
import os
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
from adc_acquisition.ops_client import BIBLIO_RATE_LIMIT, MAX_RANGE_SPAN, MAX_TOTAL_RESULTS, SEARCH_RATE_LIMIT, OPSClient, OPSThrottleError
from adc_acquisition.ops_parser import parse_biblio_response, parse_search_response
from adc_acquisition.query_registry import active_queries, load_queries
from jobs.epo.report import build_report

QUERIES_PATH = Path("configs/epo_queries.yaml")
PUBLICATION_EXTRA_FIELDS = [
    "publication_number", "family_id", "application_number", "filing_date",
    "priority_date", "applicants", "inventors", "ipc_classes", "cpc_classes",
]
LICENSE_NOTE = "EPO OPS bibliographic data (INPADOC/DOCDB), covers EP-prefixed publications."

# See module docstring / adc_acquisition/ops_client.py for why this must
# be a SEPARATE checkpoint namespace, updated unconditionally on every raw
# write and saved to disk immediately, independent of parse outcome.
RAW_NAMESPACE = "raw_records"

DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_ops_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    return date_str.replace("-", "")


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="epo", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


UNRESOLVED_STATUSES = {"failed", "parse_failed"}
RESOLVED_STATUSES = {"success", "skipped_unchanged"}


def _unresolved_publication_ids(attempts_path: Path) -> set[str]:
    """Publication ids whose MOST RECENT recorded attempt is unresolved
    (a fetch failure or a parse failure) — retried on every run regardless
    of --resume's cursor (which never narrows EPO's search itself, see
    module docstring)."""
    if not attempts_path.exists():
        return set()
    df = pd.read_parquet(attempts_path)
    if df.empty:
        return set()
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    return set(latest.loc[latest["status"].isin(UNRESOLVED_STATUSES), "source_record_id"])


def _resolved_publication_ids(attempts_path: Path) -> set[str]:
    """Publication ids whose most recent attempt is already resolved
    (success, OR skipped_unchanged from a prior successful fetch) —
    both statuses must count as "already resolved" or this set would stop
    recognizing a record after its second consecutive unchanged run."""
    if not attempts_path.exists():
        return set()
    df = pd.read_parquet(attempts_path)
    if df.empty:
        return set()
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    return set(latest.loc[latest["status"].isin(RESOLVED_STATUSES), "source_record_id"])


class EPOJob(AcquisitionJob):
    name = "epo"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--queries-file", type=str, default=str(QUERIES_PATH),
            help="Path to the EPO/OPS discovery query registry YAML.",
        )
        parser.add_argument(
            "--refresh", action="store_true",
            help=(
                "Re-fetch and hash-compare EVERY discovered publication, including ones already "
                "successfully materialized, to pick up OPS-side corrections (run periodically, e.g. "
                "monthly, not on every incremental run)."
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
                "https://developers.epo.org/) — same OPS account Job 08 (WIPO) uses."
            )
        client = OPSClient(
            search_client=RetryingClient(RateLimiter(SEARCH_RATE_LIMIT)),
            biblio_client=RetryingClient(RateLimiter(BIBLIO_RATE_LIMIT)),
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
        )

        queries = active_queries(load_queries(Path(args.queries_file)))
        if not queries:
            raise RuntimeError(f"no active queries found in {args.queries_file}")

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        now = _now_iso()
        run_id = now

        pd_filter = None
        if args.since or args.until:
            since_ops = _to_ops_date(args.since) or "00000101"
            until_ops = _to_ops_date(args.until) or "29991231"
            pd_filter = f'pd within "{since_ops},{until_ops}"'

        # --- Discovery: full sweep of every registered query. Each hit is
        # attributed to the FIRST query that discovered it for the
        # manifest's single "primary" query_id, but every (publication,
        # query) pair still gets its own discovery ledger row below. ---
        hits_by_id: dict[str, "SearchHit"] = {}
        first_query_by_id: dict[str, tuple[str, str]] = {}
        discovery_pairs: list[tuple[str, str, str]] = []  # (publication_number, query_id, query_text)

        discovery_error: str | None = None
        try:
            for q in queries:
                cql = q.query_text if not pd_filter else f"{q.query_text} and {pd_filter}"
                begin = 1
                total = None
                while total is None or begin <= min(total, MAX_TOTAL_RESULTS):
                    end = min(begin + MAX_RANGE_SPAN - 1, MAX_TOTAL_RESULTS)
                    xml_bytes = client.search(cql, begin, end)
                    page_hits, total = parse_search_response(xml_bytes)
                    if total > MAX_TOTAL_RESULTS:
                        logger.warning(
                            "query=%s total_result_count=%d exceeds OPS's %d-result access cap — "
                            "results beyond %d are not retrievable; narrow this query",
                            q.query_id, total, MAX_TOTAL_RESULTS, MAX_TOTAL_RESULTS,
                        )
                    for hit in page_hits:
                        pub_id = hit.publication_number
                        hits_by_id.setdefault(pub_id, hit)
                        first_query_by_id.setdefault(pub_id, (q.query_id, q.query_text))
                        discovery_pairs.append((pub_id, q.query_id, q.query_text))
                    if not page_hits:
                        break
                    begin = end + 1
        except OPSThrottleError as exc:
            # Persist whatever discovery this run DID gather (below) before
            # surfacing the error — a partial discovery sweep must not lose
            # the provenance it already collected.
            discovery_error = str(exc)
            logger.error("EPO discovery stopped early: %s", discovery_error)

        result.queries_run = len(queries)
        result.records_discovered = len(hits_by_id)

        discovery_path = output_dir / "manifests" / "epo_discovery.parquet"
        if not args.dry_run:
            discovery_rows = [
                dict(
                    source="epo", source_record_id=pub_id, query_id=qid, query_version=next(
                        qq.query_version for qq in queries if qq.query_id == qid
                    ),
                    query_text=qtext, discovered_at=now, run_id=run_id,
                )
                for pub_id, qid, qtext in discovery_pairs
            ]
            append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        if discovery_error is not None:
            raise RuntimeError(f"EPO discovery incomplete (partial results already persisted): {discovery_error}")

        attempts_path = output_dir / "manifests" / "epo_attempts.parquet"
        resolved_ids = _resolved_publication_ids(attempts_path)
        unresolved_ids = _unresolved_publication_ids(attempts_path)

        all_ids = list(hits_by_id.keys())
        fresh_ids = sorted(pid for pid in all_ids if pid not in resolved_ids and pid not in unresolved_ids)
        backlog_ids = sorted(pid for pid in all_ids if pid in unresolved_ids)
        already_skipped_ids = sorted(pid for pid in all_ids if pid in resolved_ids)

        if args.refresh:
            ordered_new_work = fresh_ids + backlog_ids + already_skipped_ids
            fast_skip_ids: list[str] = []
        else:
            ordered_new_work = fresh_ids + backlog_ids
            fast_skip_ids = already_skipped_ids
        target_ids = ordered_new_work[: args.limit] if args.limit else ordered_new_work

        if args.dry_run:
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered publications "
                f"({len(fresh_ids)} never attempted, {len(backlog_ids)} unresolved retries, "
                f"{len(fast_skip_ids)} already successful and skipped with no OPS request"
                + (", 0 refresh re-checks (--refresh not set)" if not args.refresh else "")
                + ")"
            )
            return result

        manifest_path = output_dir / "manifests" / "epo.parquet"

        content_rows = []
        attempt_rows = []
        parse_error: str | None = None

        already_skipped_id_set = set(already_skipped_ids)

        for pub_id in fast_skip_ids:
            result.records_skipped_unchanged += 1
            query_id, query_text = first_query_by_id[pub_id]
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, pub_id, namespace=RAW_NAMESPACE)
            attempt_rows.append(
                _record_row(
                    pub_id, run_id, now, "skipped_unchanged", query_id, query_text,
                    content_hash=raw_prior_state["content_hash"] if raw_prior_state else None,
                    version=raw_prior_state["version"] if raw_prior_state else None,
                )
            )

        for pub_id in target_ids:
            hit = hits_by_id[pub_id]
            query_id, query_text = first_query_by_id[pub_id]
            try:
                raw_bytes = client.fetch_biblio(hit.docdb_id)
            except requests.RequestException as exc:
                logger.warning("publication=%s biblio fetch failed: %s", pub_id, exc)
                failure_logger.info("publication=%s error=%s", pub_id, exc)
                result.records_failed += 1
                attempt_rows.append(_record_row(pub_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if raw_bytes is None:
                logger.warning("publication=%s: OPS has no biblio record (404)", pub_id)
                failure_logger.info("publication=%s error=not_found", pub_id)
                result.records_failed += 1
                attempt_rows.append(_record_row(pub_id, run_id, now, "failed", query_id, query_text, error="not_found"))
                continue

            content_hash = sha256_bytes(raw_bytes)
            # Raw version numbering is driven ENTIRELY by RAW_NAMESPACE,
            # updated unconditionally right after every raw write --
            # independent of whether parsing succeeds.
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, pub_id, namespace=RAW_NAMESPACE)
            raw_dir = output_dir / "raw" / "epo" / pub_id

            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                version = raw_prior_state["version"]
                raw_path = raw_dir / f"v{version}.xml"
                if pub_id in already_skipped_id_set:
                    # Already fully resolved before this run (a --refresh
                    # re-check): unchanged content AND the ledger's own
                    # most-recent status is already resolved -- a genuine
                    # no-op, no re-parse needed.
                    result.records_skipped_unchanged += 1
                    attempt_rows.append(
                        _record_row(
                            pub_id, run_id, now, "skipped_unchanged", query_id, query_text,
                            content_hash=content_hash, version=version,
                        )
                    )
                    continue
                # Else: this is a fresh/backlog id whose raw content
                # happens to match a PRIOR raw fetch that was never
                # successfully parsed (e.g. a still-unresolved parse
                # failure) -- fall through and retry parsing below,
                # reusing the existing raw file rather than rewriting it.
            else:
                version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.xml"
                raw_path.write_bytes(raw_bytes)
                checkpoint_store.set_record_state(checkpoint, pub_id, content_hash, version, now, namespace=RAW_NAMESPACE)
                checkpoint_store.save(checkpoint)

            try:
                parsed = parse_biblio_response(raw_bytes)
            except Exception as exc:  # noqa: BLE001 - any parser bug must not silently lose this record
                logger.error("publication=%s biblio parse failed: %s", pub_id, exc)
                failure_logger.info("publication=%s error=parse_failed: %s", pub_id, exc)
                attempt_rows.append(
                    _record_row(
                        pub_id, run_id, now, "parse_failed", query_id, query_text,
                        error=str(exc), content_hash=content_hash, version=version,
                    )
                )
                parse_error = f"publication={pub_id}: {exc}"
                break  # a parser bug is likely systematic -- stop rather than push through the whole batch

            result.records_downloaded += 1
            attempt_rows.append(
                _record_row(pub_id, run_id, now, "success", query_id, query_text, content_hash=content_hash, version=version)
            )
            content_rows.append(
                new_manifest_row(
                    extra_fields=PUBLICATION_EXTRA_FIELDS,
                    source="epo",
                    source_record_id=pub_id,
                    source_record_type="epo_publication",
                    title=parsed.title if parsed else None,
                    url=f"https://register.epo.org/application?number={parsed.application_number}" if parsed and parsed.application_number else None,
                    publication_or_release_date=parsed.publication_date if parsed else None,
                    retrieved_at=now,
                    query_id=query_id,
                    query_text=query_text,
                    raw_file_path=str(raw_path),
                    raw_format="xml",
                    content_hash=content_hash,
                    download_status="success",
                    http_status=200,
                    license_or_access_note=LICENSE_NOTE,
                    parent_record_id=None,
                    version=version,
                    notes=parsed.abstract if parsed else None,
                    publication_number=pub_id,
                    family_id=parsed.family_id if parsed else hit.family_id,
                    application_number=parsed.application_number if parsed else None,
                    filing_date=parsed.filing_date if parsed else None,
                    priority_date=parsed.priority_date if parsed else None,
                    applicants=parsed.applicants if parsed else [],
                    inventors=parsed.inventors if parsed else [],
                    ipc_classes=parsed.ipc_classes if parsed else [],
                    cpc_classes=parsed.cpc_classes if parsed else [],
                )
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=PUBLICATION_EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        checkpoint["last_run_at"] = now
        checkpoint["last_success_max_date"] = args.until or now[:10]
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / "epo.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(result, manifest_df, all_ids, fresh_ids, backlog_ids, fast_skip_ids),
            encoding="utf-8",
        )

        if parse_error is not None:
            raise RuntimeError(
                f"EPO biblio parsing failed (raw bytes and prior progress already persisted): {parse_error}"
            )

        return result
