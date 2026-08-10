"""Job 02: Europe PMC acquisition (Prompt.md section 6).

Same three-table model as Job 01 (see jobs/pubmed/job.py for the full
rationale): europe_pmc.parquet holds only materialized evidence snapshots,
europe_pmc_discovery.parquet is an append-only every-query-every-run ledger,
europe_pmc_attempts.parquet is an append-only every-attempt ledger. Failures
never occupy a content-version slot.

Full-text XML is a SEPARATE, independently versioned artifact, not a field
on the metadata row. For isOpenAccess=Y records (Prompt.md: "For open-access
full text, download legally accessible XML whenever supported... Do NOT
bypass publisher paywalls") we fetch JATS full text and track it exactly
like a second evidence-record type:

- europe_pmc_fulltext.parquet          — content-version manifest, keyed by
                                          pmcid, with parent_record_id
                                          pointing back to the metadata
                                          record. Never touched by a fetch
                                          failure or by the metadata row's
                                          own lifecycle.
- europe_pmc_fulltext_attempts.parquet — append-only attempts ledger for
                                          full-text fetches specifically.

The checkpoint file tracks metadata and full-text state in separate
namespaces ("records" vs "fulltext_records") so a record and its full-text
artifact never collide on state, even though they happen to share a related
identifier space (a metadata record's pmcid vs. its own source_record_id).

This means a full-text fetch is retried every run (hash-compared against the
checkpoint, same as metadata) rather than treated as permanently done or
permanently failed after one attempt — and, critically, updating full-text
state never mutates the metadata record's own content-version row.

We do not deduplicate against the PubMed manifest (Prompt.md: "A paper
appearing in both PubMed and Europe PMC should retain both provenance
records") — pmid/doi are preserved so a downstream join is possible, but no
active cross-referencing happens in the acquisition layer.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.query_registry import active_queries, load_queries
from jobs.europe_pmc.client import RATE_LIMIT, EuropePMCClient
from jobs.europe_pmc.parser import parse_search_result
from jobs.europe_pmc.report import build_report

QUERIES_PATH = Path("configs/europe_pmc_queries.yaml")
EXTRA_FIELDS = ["epmc_source", "epmc_id", "pmid", "pmcid", "doi", "abstract", "journal", "is_open_access", "license", "in_pmc"]
DEFAULT_PAGE_SIZE = 200
LICENSE_NOTE_TEMPLATE = "Europe PMC metadata (source={epmc_source}); license={license}."
FULLTEXT_NAMESPACE = "fulltext_records"

DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]
FULLTEXT_ATTEMPT_COLUMNS = [
    "source", "source_record_id", "parent_record_id", "run_id", "attempted_at",
    "status", "http_status", "error", "content_hash", "version",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attempt_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="europe_pmc", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _fulltext_attempt_row(
    pmcid: str, parent_record_id: str, run_id: str, attempted_at: str, status: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="europe_pmc", source_record_id=pmcid, parent_record_id=parent_record_id,
        run_id=run_id, attempted_at=attempted_at, status=status,
        http_status=http_status, error=error, content_hash=content_hash, version=version,
    )


def _process_metadata_record(
    source_record_id: str,
    raw_result: dict,
    query_id: str,
    query_text: str,
    now: str,
    output_dir: Path,
    checkpoint_store: CheckpointStore,
    checkpoint: dict,
):
    """Process one discovered record's metadata snapshot only — no full text
    here. Returns (content_row_or_None, status, content_hash, version, parsed).
    Raises on genuinely malformed input; the caller turns that into a failed
    attempt so one bad record can't crash the whole run."""
    parsed = parse_search_result(raw_result)
    if parsed is None:
        raise ValueError("missing source/id on a record that reached per-record processing")

    raw_bytes = json.dumps(raw_result, sort_keys=True).encode("utf-8")
    content_hash = sha256_bytes(raw_bytes)
    prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id)
    raw_dir = output_dir / "raw" / "europe_pmc" / source_record_id.replace(":", "_")

    if prior_state and prior_state.get("content_hash") == content_hash:
        version = prior_state["version"]
        status = "skipped_unchanged"
        content_row = None
    else:
        version = (prior_state["version"] + 1) if prior_state else 1
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"v{version}.json"
        raw_path.write_bytes(raw_bytes)
        checkpoint_store.set_record_state(checkpoint, source_record_id, content_hash, version, now)
        status = "success"
        content_row = new_manifest_row(
            extra_fields=EXTRA_FIELDS,
            source="europe_pmc",
            source_record_id=source_record_id,
            source_record_type="literature_record",
            title=parsed.title,
            url=f"https://europepmc.org/article/{parsed.epmc_source}/{parsed.epmc_id}",
            publication_or_release_date=parsed.publication_date,
            retrieved_at=now,
            query_id=query_id,
            query_text=query_text,
            raw_file_path=str(raw_path),
            raw_format="json",
            content_hash=content_hash,
            download_status="success",
            http_status=200,
            license_or_access_note=LICENSE_NOTE_TEMPLATE.format(epmc_source=parsed.epmc_source, license=parsed.license),
            parent_record_id=None,
            version=version,
            notes=None,
            epmc_source=parsed.epmc_source,
            epmc_id=parsed.epmc_id,
            pmid=parsed.pmid,
            pmcid=parsed.pmcid,
            doi=parsed.doi,
            abstract=parsed.abstract,
            journal=parsed.journal,
            is_open_access=parsed.is_open_access,
            license=parsed.license,
            in_pmc=parsed.in_pmc,
        )

    return content_row, status, content_hash, version, parsed


def _process_fulltext(
    pmcid: str,
    parent_record_id: str,
    now: str,
    output_dir: Path,
    checkpoint_store: CheckpointStore,
    checkpoint: dict,
    client: EuropePMCClient,
):
    """Fetch and version one full-text XML artifact, entirely independent of
    its parent metadata record's own content-version state. Raises
    requests.RequestException on fetch failure — the caller logs that as a
    failed full-text attempt without touching the metadata row at all.
    Returns (content_row_or_None, status, content_hash, version)."""
    fulltext_xml = client.fetch_fulltext_xml(pmcid)
    content_hash = sha256_bytes(fulltext_xml)
    prior_state = checkpoint_store.get_record_state(checkpoint, pmcid, namespace=FULLTEXT_NAMESPACE)
    raw_dir = output_dir / "raw" / "europe_pmc_fulltext" / pmcid

    if prior_state and prior_state.get("content_hash") == content_hash:
        version = prior_state["version"]
        status = "skipped_unchanged"
        return None, status, content_hash, version

    version = (prior_state["version"] + 1) if prior_state else 1
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"v{version}.xml"
    raw_path.write_bytes(fulltext_xml)
    checkpoint_store.set_record_state(checkpoint, pmcid, content_hash, version, now, namespace=FULLTEXT_NAMESPACE)

    content_row = new_manifest_row(
        source="europe_pmc",
        source_record_id=pmcid,
        source_record_type="fulltext_jats_xml",
        title=None,
        url=f"https://europepmc.org/articles/{pmcid}",
        publication_or_release_date=None,
        retrieved_at=now,
        query_id=None,
        query_text=None,
        raw_file_path=str(raw_path),
        raw_format="xml",
        content_hash=content_hash,
        download_status="success",
        http_status=200,
        license_or_access_note="Europe PMC open-access full text (JATS XML); publisher paywalls are never bypassed.",
        parent_record_id=parent_record_id,
        version=version,
        notes=None,
    )
    return content_row, "success", content_hash, version


class EuropePMCJob(AcquisitionJob):
    name = "europe_pmc"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--queries-file", type=str, default=str(QUERIES_PATH),
            help="Path to the Europe PMC query registry YAML.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        queries = active_queries(load_queries(Path(args.queries_file)))
        if not queries:
            raise RuntimeError(f"no active queries found in {args.queries_file}")
        query_by_id = {q.query_id: q for q in queries}

        since = args.since
        if args.resume and not since:
            since = checkpoint.get("last_success_max_date")
        date_filter = None
        if since or args.until:
            date_filter = f"FIRST_PDATE:[{since or '1900-01-01'} TO {args.until or '3000-01-01'}]"

        http_client = RetryingClient(RateLimiter(RATE_LIMIT))
        client = EuropePMCClient(http_client)

        # --- Discovery: run every active query, paginate via cursorMark ---
        record_first_query: dict[str, tuple[str, str]] = {}
        record_query_hits: dict[str, set[str]] = defaultdict(set)
        record_results: dict[str, dict] = {}  # source_record_id -> raw search result dict
        query_id_counts: Counter = Counter()

        for query in queries:
            query_text = f"({query.query_text}) AND {date_filter}" if date_filter else query.query_text
            cursor_mark = "*"
            hits_for_query = 0
            hit_count = 0
            while True:
                page = client.search(query_text, cursor_mark=cursor_mark, page_size=DEFAULT_PAGE_SIZE)
                hit_count = page.hit_count
                for record in page.results:
                    parsed_source = record.get("source")
                    parsed_id = record.get("id")
                    if not parsed_source or not parsed_id:
                        continue
                    source_record_id = f"{parsed_source}:{parsed_id}"
                    record_query_hits[source_record_id].add(query.query_id)
                    if source_record_id not in record_first_query:
                        record_first_query[source_record_id] = (query.query_id, query.query_text)
                    record_results[source_record_id] = record
                hits_for_query += len(page.results)
                # Same efficiency guard as Job 01: don't page a 16k-hit query
                # to exhaustion just to serve a 20-record smoke test.
                enough_for_limit = args.limit and len(record_first_query) >= args.limit
                if page.next_cursor_mark is None or not page.results or enough_for_limit:
                    break
                cursor_mark = page.next_cursor_mark
            query_id_counts[query.query_id] = hits_for_query
            logger.info("query %s: %d hits (of %d total)", query.query_id, hits_for_query, hit_count)

        all_ids = list(record_first_query.keys())
        duplicate_ids = {rid for rid, qids in record_query_hits.items() if len(qids) > 1}

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        result.queries_run = len(queries)
        result.records_discovered = len(all_ids)
        if args.limit:
            result.notes.append(
                "discovery pagination was capped by --limit; per-query hit counts reflect only the "
                "pages actually fetched, not each query's true total corpus size"
            )

        # Deterministic ordering so --limit is reproducible across runs.
        all_ids.sort()
        target_ids = all_ids[: args.limit] if args.limit else all_ids

        if args.dry_run:
            result.notes.append(f"dry-run: would fetch {len(target_ids)} of {len(all_ids)} discovered records")
            return result

        now = _now_iso()
        run_id = now

        manifest_path = output_dir / "manifests" / "europe_pmc.parquet"
        discovery_path = output_dir / "manifests" / "europe_pmc_discovery.parquet"
        attempts_path = output_dir / "manifests" / "europe_pmc_attempts.parquet"
        fulltext_manifest_path = output_dir / "manifests" / "europe_pmc_fulltext.parquet"
        fulltext_attempts_path = output_dir / "manifests" / "europe_pmc_fulltext_attempts.parquet"

        discovery_rows = [
            dict(
                source="europe_pmc",
                source_record_id=rid,
                query_id=query_by_id[qid].query_id,
                query_version=query_by_id[qid].query_version,
                query_text=query_by_id[qid].query_text,
                discovered_at=now,
                run_id=run_id,
            )
            for rid, query_ids in record_query_hits.items()
            for qid in sorted(query_ids)
        ]
        append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        content_rows = []
        attempt_rows = []
        fulltext_content_rows = []
        fulltext_attempt_rows = []

        for source_record_id in target_ids:
            query_id, query_text = record_first_query[source_record_id]
            raw_result = record_results[source_record_id]
            try:
                content_row, status, content_hash, version, parsed = _process_metadata_record(
                    source_record_id, raw_result, query_id, query_text, now,
                    output_dir, checkpoint_store, checkpoint,
                )
            except Exception as exc:  # noqa: BLE001 — one malformed record must not crash the whole run
                logger.error("record=%s failed to process: %s", source_record_id, exc)
                failure_logger.info("record=%s error=%s", source_record_id, exc)
                result.records_failed += 1
                attempt_rows.append(_attempt_row(source_record_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if status == "success":
                result.records_downloaded += 1
            else:
                result.records_skipped_unchanged += 1
            if content_row is not None:
                content_rows.append(content_row)
            attempt_rows.append(
                _attempt_row(
                    source_record_id, run_id, now, status, query_id, query_text,
                    http_status=200, content_hash=content_hash, version=version,
                )
            )

            if parsed.is_open_access and parsed.pmcid:
                try:
                    ft_row, ft_status, ft_hash, ft_version = _process_fulltext(
                        parsed.pmcid, source_record_id, now, output_dir, checkpoint_store, checkpoint, client,
                    )
                    if ft_row is not None:
                        fulltext_content_rows.append(ft_row)
                    fulltext_attempt_rows.append(
                        _fulltext_attempt_row(
                            parsed.pmcid, source_record_id, run_id, now, ft_status,
                            http_status=200, content_hash=ft_hash, version=ft_version,
                        )
                    )
                except requests.RequestException as exc:
                    logger.warning("record=%s fulltext fetch failed: %s", source_record_id, exc)
                    failure_logger.info("pmcid=%s parent=%s error=%s", parsed.pmcid, source_record_id, exc)
                    fulltext_attempt_rows.append(
                        _fulltext_attempt_row(parsed.pmcid, source_record_id, run_id, now, "failed", error=str(exc))
                    )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        write_manifest(fulltext_content_rows, fulltext_manifest_path)
        append_only(fulltext_attempt_rows, fulltext_attempts_path, FULLTEXT_ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)
        checkpoint["last_run_at"] = now
        if not result.records_failed:
            checkpoint["last_success_max_date"] = args.until or now[:10]
        checkpoint_store.save(checkpoint)

        report_text = build_report(
            result=result,
            manifest_df=manifest_df,
            queries=queries,
            query_id_counts=query_id_counts,
            unique_ids=set(all_ids),
            duplicate_ids=duplicate_ids,
            since=since,
            until=args.until,
            fulltext_attempted=len(fulltext_attempt_rows),
            fulltext_new_or_changed=sum(1 for r in fulltext_attempt_rows if r["status"] == "success"),
            fulltext_unchanged=sum(1 for r in fulltext_attempt_rows if r["status"] == "skipped_unchanged"),
            fulltext_failed=sum(1 for r in fulltext_attempt_rows if r["status"] == "failed"),
        )
        # reports/ is a sibling of DATA/ (Prompt.md section 2), scoped to
        # wherever --output pointed — otherwise a scratch/test run with a
        # different --output would silently clobber the real report.
        report_path = output_dir.parent / "reports" / "acquisition" / "europe_pmc.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
