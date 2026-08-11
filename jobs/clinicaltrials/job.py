"""Job 03: ClinicalTrials.gov acquisition (Prompt.md section 10).

Same three-table model as Jobs 01/02: clinicaltrials.parquet holds only
materialized evidence snapshots, clinicaltrials_discovery.parquet is an
append-only every-query-every-run ledger, clinicaltrials_attempts.parquet is
an append-only every-attempt ledger.

Unlike PubMed (esearch -> efetch) or Europe PMC (search -> fullTextXML),
ClinicalTrials.gov's search endpoint returns each trial's complete record
inline — there's no second "fetch full record" phase, so the discovered
search result *is* the content snapshot.

Prompt.md section 10 asks for both:
  A. broad ADC discovery queries (configs/clinicaltrials_queries.yaml)
  B. known-asset lookup capability (--intervention "<name>"), which searches
     query.intr instead of the broad query family. This is a capability, not
     yet wired into a systematic asset-expansion pass — that's Job 15.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.query_registry import QuerySpec, active_queries, load_queries
from jobs.clinicaltrials.client import RATE_LIMIT, ClinicalTrialsClient
from jobs.clinicaltrials.parser import parse_study
from jobs.clinicaltrials.report import build_report

QUERIES_PATH = Path("configs/clinicaltrials_queries.yaml")
EXTRA_FIELDS = [
    "nct_id", "brief_title", "official_title", "study_type", "phases", "overall_status",
    "conditions", "intervention_names", "lead_sponsor", "collaborators", "enrollment",
    "enrollment_type", "study_first_post_date", "start_date", "primary_completion_date", "completion_date",
    "primary_outcomes", "secondary_outcomes", "locations", "references", "last_update_date",
]
DEFAULT_PAGE_SIZE = 100
LICENSE_NOTE = "ClinicalTrials.gov trial registration record, public domain."

DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attempt_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="clinicaltrials", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _process_record(
    nct_id: str,
    raw_result: dict,
    query_id: str,
    query_text: str,
    now: str,
    output_dir: Path,
    checkpoint_store: CheckpointStore,
    checkpoint: dict,
):
    """Returns (content_row_or_None, status, content_hash, version). Raises
    on genuinely malformed input; the caller turns that into a failed
    attempt so one bad record can't crash the whole run."""
    parsed = parse_study(raw_result)
    if parsed is None:
        raise ValueError("missing protocolSection/nctId on a record that reached per-record processing")

    raw_bytes = json.dumps(raw_result, sort_keys=True).encode("utf-8")
    content_hash = sha256_bytes(raw_bytes)
    prior_state = checkpoint_store.get_record_state(checkpoint, nct_id)
    raw_dir = output_dir / "raw" / "clinicaltrials" / nct_id

    if prior_state and prior_state.get("content_hash") == content_hash:
        return None, "skipped_unchanged", content_hash, prior_state["version"]

    version = (prior_state["version"] + 1) if prior_state else 1
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"v{version}.json"
    raw_path.write_bytes(raw_bytes)
    checkpoint_store.set_record_state(checkpoint, nct_id, content_hash, version, now)

    content_row = new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="clinicaltrials",
        source_record_id=nct_id,
        source_record_type="clinical_trial",
        title=parsed.brief_title,
        url=f"https://clinicaltrials.gov/study/{nct_id}",
        # publication_or_release_date is when this evidence record was
        # first published, not when the trial itself started — those are
        # different dates (studyFirstPostDate vs startDate).
        publication_or_release_date=parsed.study_first_post_date,
        retrieved_at=now,
        query_id=query_id,
        query_text=query_text,
        raw_file_path=str(raw_path),
        raw_format="json",
        content_hash=content_hash,
        download_status="success",
        http_status=200,
        license_or_access_note=LICENSE_NOTE,
        parent_record_id=None,
        version=version,
        notes=None,
        nct_id=parsed.nct_id,
        brief_title=parsed.brief_title,
        official_title=parsed.official_title,
        study_type=parsed.study_type,
        phases=parsed.phases,
        overall_status=parsed.overall_status,
        conditions=parsed.conditions,
        intervention_names=parsed.intervention_names,
        lead_sponsor=parsed.lead_sponsor,
        collaborators=parsed.collaborators,
        enrollment=parsed.enrollment,
        enrollment_type=parsed.enrollment_type,
        study_first_post_date=parsed.study_first_post_date,
        start_date=parsed.start_date,
        primary_completion_date=parsed.primary_completion_date,
        completion_date=parsed.completion_date,
        primary_outcomes=parsed.primary_outcomes,
        secondary_outcomes=parsed.secondary_outcomes,
        locations=parsed.locations,
        references=parsed.references,
        last_update_date=parsed.last_update_date,
    )
    return content_row, "success", content_hash, version


class ClinicalTrialsJob(AcquisitionJob):
    name = "clinicaltrials"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--queries-file", type=str, default=str(QUERIES_PATH),
            help="Path to the ClinicalTrials.gov query registry YAML.",
        )
        parser.add_argument(
            "--intervention", type=str, default=None,
            help="Known-asset lookup (Prompt.md section 10.B): search by intervention/drug name instead of the broad query family.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        client = ClinicalTrialsClient(RetryingClient(RateLimiter(RATE_LIMIT)))

        since = args.since
        if args.resume and not since:
            since = checkpoint.get("last_success_max_date")

        if args.intervention:
            # Every distinct intervention name must get its own query_id —
            # reusing one fixed id (e.g. "CTGOV_LOOKUP_INTR") for every
            # lookup would violate the query provenance contract (Prompt.md
            # section 20: never reuse a query_id for a materially different
            # query_text). The id is a deterministic hash of the canonical
            # query text, so re-running the same intervention lookup later
            # (e.g. in Job 15's asset expansion) reproduces the same id.
            lookup_query_text = f"query.intr={args.intervention}"
            lookup_query_id = f"CTGOV_LOOKUP_INTR_{sha256_bytes(lookup_query_text.encode('utf-8'))[:12]}"
            queries = [QuerySpec(
                query_id=lookup_query_id, query_version=1,
                query_text=lookup_query_text,
                purpose=f"known-asset lookup for intervention {args.intervention!r}", active=True,
            )]

            def search_fn(term, page_token, page_size):
                return client.search_by_intervention(args.intervention, page_token, page_size, since=since, until=args.until)
        else:
            queries = active_queries(load_queries(Path(args.queries_file)))

            def search_fn(term, page_token, page_size):
                return client.search(term, page_token, page_size, since=since, until=args.until)
        if not queries:
            raise RuntimeError(f"no active queries found in {args.queries_file}")
        query_by_id = {q.query_id: q for q in queries}

        # --- Discovery: run every active query, paginate via pageToken ---
        record_first_query: dict[str, tuple[str, str]] = {}
        record_query_hits: dict[str, set[str]] = defaultdict(set)
        record_results: dict[str, dict] = {}
        query_id_counts: Counter = Counter()

        for query in queries:
            page_token = None
            hits_for_query = 0
            total_count = None
            while True:
                page = search_fn(query.query_text, page_token, DEFAULT_PAGE_SIZE)
                total_count = page.total_count
                for study in page.studies:
                    nct_id = ((study.get("protocolSection") or {}).get("identificationModule") or {}).get("nctId")
                    if not nct_id:
                        continue
                    record_query_hits[nct_id].add(query.query_id)
                    if nct_id not in record_first_query:
                        record_first_query[nct_id] = (query.query_id, query.query_text)
                    record_results[nct_id] = study
                hits_for_query += len(page.studies)
                enough_for_limit = args.limit and len(record_first_query) >= args.limit
                if not page.next_page_token or not page.studies or enough_for_limit:
                    break
                page_token = page.next_page_token
            query_id_counts[query.query_id] = hits_for_query
            logger.info("query %s: %d hits (of %s total)", query.query_id, hits_for_query, total_count)

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

        all_ids.sort()
        target_ids = all_ids[: args.limit] if args.limit else all_ids

        if args.dry_run:
            result.notes.append(f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered NCT IDs")
            return result

        now = _now_iso()
        run_id = now

        manifest_path = output_dir / "manifests" / "clinicaltrials.parquet"
        discovery_path = output_dir / "manifests" / "clinicaltrials_discovery.parquet"
        attempts_path = output_dir / "manifests" / "clinicaltrials_attempts.parquet"

        discovery_rows = [
            dict(
                source="clinicaltrials",
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

        for nct_id in target_ids:
            query_id, query_text = record_first_query[nct_id]
            raw_result = record_results[nct_id]
            try:
                content_row, status, content_hash, version = _process_record(
                    nct_id, raw_result, query_id, query_text, now, output_dir, checkpoint_store, checkpoint,
                )
            except Exception as exc:  # noqa: BLE001 — one malformed record must not crash the whole run
                logger.error("record=%s failed to process: %s", nct_id, exc)
                failure_logger.info("record=%s error=%s", nct_id, exc)
                result.records_failed += 1
                attempt_rows.append(_attempt_row(nct_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if status == "success":
                result.records_downloaded += 1
            else:
                result.records_skipped_unchanged += 1
            if content_row is not None:
                content_rows.append(content_row)
            attempt_rows.append(
                _attempt_row(nct_id, run_id, now, status, query_id, query_text, http_status=200, content_hash=content_hash, version=version)
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)
        checkpoint["last_run_at"] = now
        if not result.records_failed:
            checkpoint["last_success_max_date"] = args.until or now[:10]
        checkpoint_store.save(checkpoint)

        report_text = build_report(
            result=result, manifest_df=manifest_df, queries=queries,
            query_id_counts=query_id_counts, unique_ids=set(all_ids), duplicate_ids=duplicate_ids,
            since=since, until=args.until,
        )
        report_path = output_dir.parent / "reports" / "acquisition" / "clinicaltrials.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
