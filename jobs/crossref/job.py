"""Job 04: Crossref acquisition (Prompt.md section 16).

DOI-centric reconciliation, not broad discovery — see
configs/crossref_reconciliation_sources.yaml for why: Crossref's own search
params are relevance-ranked free text, not a phrase/boolean search, and are
unusable for precise topic discovery (verified live). This job instead
looks up DOIs already discovered by other jobs (currently: PubMed, Europe
PMC) via the authoritative GET /works/{doi} endpoint, plus an ad hoc
--doi "<doi>" lookup mode.

Same three-table model as Jobs 01-03: crossref.parquet holds only
materialized evidence snapshots, crossref_discovery.parquet is an
append-only every-source-every-run ledger, crossref_attempts.parquet is an
append-only every-attempt ledger (a DOI Crossref doesn't have — HTTP 404 —
is a distinct, expected outcome, not a generic failure, but still never
occupies a content-version slot).

--since/--until/--resume are accepted (per the common CLI surface) but are
explicitly not applicable here and are ignored with a loud note in the
result/report — Crossref reconciliation is driven by which DOIs upstream
jobs have discovered, not by a queryable date range on Crossref's side, and
the checkpoint's content-hash skip already avoids redundant re-fetching on
every run regardless of --resume.

Each distinct --doi lookup gets its own deterministic query_id (a hash of
the DOI), not one shared template id — same fix Job 03's --intervention
lookup needed, applied proactively here (Prompt.md section 20: never reuse
a query_id for a materially different query_text).
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from jobs.crossref.client import RATE_LIMIT, CrossrefClient
from jobs.crossref.parser import parse_work
from jobs.crossref.report import build_report

SOURCES_PATH = Path("configs/crossref_reconciliation_sources.yaml")
EXTRA_FIELDS = ["doi", "authors", "publisher", "container_title", "work_type", "published_date", "license_url", "references", "abstract"]
LICENSE_NOTE_TEMPLATE = "Crossref bibliographic metadata (publisher={publisher})."

DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]


@dataclass(frozen=True)
class ReconciliationSource:
    source_id: str
    manifest_path: str
    query_id: str
    query_version: int
    purpose: str
    active: bool


def load_reconciliation_sources(path: Path) -> list[ReconciliationSource]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [ReconciliationSource(**entry) for entry in data.get("reconciliation_sources", [])]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attempt_row(
    doi: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="crossref", source_record_id=doi, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


class CrossrefJob(AcquisitionJob):
    name = "crossref"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--sources-file", type=str, default=str(SOURCES_PATH),
            help="Path to the Crossref reconciliation-sources registry YAML.",
        )
        parser.add_argument(
            "--doi", type=str, default=None,
            help="Ad hoc lookup: reconcile a single DOI directly, bypassing the reconciliation-sources registry.",
        )
        parser.add_argument(
            "--mailto", type=str, default=None,
            help="Contact email for Crossref's polite pool (also read from CROSSREF_CONTACT_EMAIL env var).",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        mailto = args.mailto or os.environ.get("CROSSREF_CONTACT_EMAIL")
        client = CrossrefClient(RetryingClient(RateLimiter(RATE_LIMIT)), mailto=mailto)

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.since or args.until:
            result.notes.append(
                "--since/--until are not applicable to Crossref reconciliation (driven by which DOIs "
                "upstream jobs have discovered, not a queryable date range on Crossref's side) and were ignored"
            )
        if args.resume:
            result.notes.append(
                "--resume is a no-op here beyond default behavior: every DOI is always content-hash-checked "
                "against the checkpoint regardless, so there's no separate incremental-window narrowing to do"
            )

        sources = [s for s in load_reconciliation_sources(Path(args.sources_file)) if s.active]
        if not sources and not args.doi:
            raise RuntimeError(f"no active reconciliation sources in {args.sources_file} and no --doi given")

        record_first_query: dict[str, tuple[str, str]] = {}
        record_query_hits: dict[str, set[str]] = defaultdict(set)
        query_id_counts: Counter = Counter()
        query_by_id: dict[str, tuple[int, str]] = {}  # query_id -> (query_version, query_text)
        sources_used: list[str] = []
        skipped_missing_manifests: list[str] = []

        for source in sources:
            manifest_path = Path(source.manifest_path)
            if not manifest_path.exists():
                skipped_missing_manifests.append(source.source_id)
                continue
            df = pd.read_parquet(manifest_path)
            dois = sorted(set(df["doi"].dropna().unique().tolist())) if "doi" in df.columns else []
            query_text = f"non-null doi values from {source.source_id}'s manifest ({source.manifest_path})"
            query_by_id[source.query_id] = (source.query_version, query_text)
            query_id_counts[source.query_id] = len(dois)
            for doi in dois:
                record_query_hits[doi].add(source.query_id)
                if doi not in record_first_query:
                    record_first_query[doi] = (source.query_id, query_text)
            sources_used.append(source.source_id)

        if args.doi:
            lookup_query_text = f"doi={args.doi}"
            lookup_query_id = f"CROSSREF_LOOKUP_DOI_{sha256_bytes(lookup_query_text.encode('utf-8'))[:12]}"
            query_by_id[lookup_query_id] = (1, lookup_query_text)
            query_id_counts[lookup_query_id] = 1
            record_query_hits[args.doi].add(lookup_query_id)
            if args.doi not in record_first_query:
                record_first_query[args.doi] = (lookup_query_id, lookup_query_text)
            sources_used.append(f"--doi {args.doi}")

        all_ids = list(record_first_query.keys())
        duplicate_ids = {doi for doi, qids in record_query_hits.items() if len(qids) > 1}

        result.queries_run = len(sources_used)
        result.records_discovered = len(all_ids)

        all_ids.sort()
        target_ids = all_ids[: args.limit] if args.limit else all_ids

        if args.dry_run:
            result.notes.append(f"dry-run: would reconcile {len(target_ids)} of {len(all_ids)} discovered DOIs")
            return result

        now = _now_iso()
        run_id = now

        manifest_path = output_dir / "manifests" / "crossref.parquet"
        discovery_path = output_dir / "manifests" / "crossref_discovery.parquet"
        attempts_path = output_dir / "manifests" / "crossref_attempts.parquet"

        discovery_rows = [
            dict(
                source="crossref",
                source_record_id=doi,
                query_id=qid,
                query_version=query_by_id[qid][0],
                query_text=query_by_id[qid][1],
                discovered_at=now,
                run_id=run_id,
            )
            for doi, query_ids in record_query_hits.items()
            for qid in sorted(query_ids)
        ]
        append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        content_rows = []
        attempt_rows = []
        not_found_count = 0

        for doi in target_ids:
            query_id, query_text = record_first_query[doi]
            try:
                message = client.get_work(doi)
            except requests.RequestException as exc:
                logger.error("doi=%s fetch failed: %s", doi, exc)
                failure_logger.info("doi=%s error=%s", doi, exc)
                result.records_failed += 1
                attempt_rows.append(_attempt_row(doi, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if message is None:
                logger.info("doi=%s not found in Crossref", doi)
                failure_logger.info("doi=%s error=not_found_in_crossref", doi)
                result.records_failed += 1
                not_found_count += 1
                attempt_rows.append(
                    _attempt_row(doi, run_id, now, "failed", query_id, query_text, http_status=404, error="not_found_in_crossref")
                )
                continue

            parsed = parse_work(message)
            if parsed is None:
                logger.warning("doi=%s Crossref response missing DOI field", doi)
                failure_logger.info("doi=%s error=unparseable_response", doi)
                result.records_failed += 1
                attempt_rows.append(_attempt_row(doi, run_id, now, "failed", query_id, query_text, error="unparseable_response"))
                continue

            raw_bytes = json.dumps(message, sort_keys=True).encode("utf-8")
            content_hash = sha256_bytes(raw_bytes)
            prior_state = checkpoint_store.get_record_state(checkpoint, doi)

            if prior_state and prior_state.get("content_hash") == content_hash:
                result.records_skipped_unchanged += 1
                version = prior_state["version"]
                status = "skipped_unchanged"
            else:
                version = (prior_state["version"] + 1) if prior_state else 1
                raw_dir = output_dir / "raw" / "crossref" / doi.replace("/", "_")
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.json"
                raw_path.write_bytes(raw_bytes)
                checkpoint_store.set_record_state(checkpoint, doi, content_hash, version, now)
                result.records_downloaded += 1
                status = "success"
                content_rows.append(
                    new_manifest_row(
                        extra_fields=EXTRA_FIELDS,
                        source="crossref",
                        source_record_id=doi,
                        source_record_type="crossref_work",
                        title=parsed.title,
                        url=parsed.url or f"https://doi.org/{doi}",
                        publication_or_release_date=parsed.published_date,
                        retrieved_at=now,
                        query_id=query_id,
                        query_text=query_text,
                        raw_file_path=str(raw_path),
                        raw_format="json",
                        content_hash=content_hash,
                        download_status="success",
                        http_status=200,
                        license_or_access_note=LICENSE_NOTE_TEMPLATE.format(publisher=parsed.publisher),
                        parent_record_id=None,
                        version=version,
                        notes=None,
                        doi=parsed.doi,
                        authors=parsed.authors,
                        publisher=parsed.publisher,
                        container_title=parsed.container_title,
                        work_type=parsed.work_type,
                        published_date=parsed.published_date,
                        license_url=parsed.license_url,
                        references=parsed.references,
                        abstract=parsed.abstract,
                    )
                )

            attempt_rows.append(
                _attempt_row(doi, run_id, now, status, query_id, query_text, http_status=200, content_hash=content_hash, version=version)
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)
        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_text = build_report(
            result=result, manifest_df=manifest_df, sources_used=sources_used,
            query_id_counts=query_id_counts, unique_ids=set(all_ids), duplicate_ids=duplicate_ids,
            not_found_count=not_found_count, skipped_missing_manifests=skipped_missing_manifests,
        )
        report_path = output_dir.parent / "reports" / "acquisition" / "crossref.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
