"""Job 07: EMA acquisition (Prompt.md section 15).

EMA has no public REST API for this, but explicitly publishes bulk JSON
exports intended for automated systems (see jobs/ema/client.py) — one
covering every EMA-authorised medicine, one covering every EPAR document
across every medicine, each with stable per-record identifiers and
first_published/last_updated dates independent of any single medicine's
own page. This supersedes an earlier version of this job that scraped
each medicine's rendered EPAR HTML page to enumerate its documents (a
review round on PR #7 caught that this coupled document discovery to
per-medicine page availability, coupled document retry-scope to the
medicine's own --resume window, and triggered EMA's session-level rate
throttle far more than the bulk feeds do).

Discovery is systematic INN-suffix matching (configs/ema_adc_substance_patterns.yaml:
vedotin, emtansine, deruxtecan, ...) against the medicines feed's
name/active-substance fields — standardized WHO stems for ADC
linker/payload chemistry, not a manually maintained list (see that config
file for the live-verification details), same spirit as Job 06 (FDA)'s
full-text label search.

Three independent levels:

- ema_bulk.parquet        — the raw bulk JSON feeds themselves (source
                             records: "medicines_bulk", "documents_bulk"),
                             content-versioned exactly as downloaded, so
                             a future schema/data change on EMA's side
                             never leaves us without the exact input that
                             produced a given run's discovery decisions.
- ema.parquet             — medicine content-version manifest, keyed by
                             EMA product number. Content is the medicine's
                             own record dict from the medicines feed
                             verbatim (already the source's raw
                             per-record representation, not a
                             reconstruction). Authorisation history and
                             withdrawal information (Prompt.md's explicit
                             list) live here as structured date fields.
- ema_documents.parquet   — the actual EPAR documents (product
                             information, assessment reports, ... —
                             Prompt.md's explicit list, EXCEPT the
                             safety-specific PSUSA/DHPC feeds, which are
                             separate EMA datasets not yet acquired here)
                             as a SEPARATE, independently versioned
                             artifact, keyed by "{product_number}:{doc_id}"
                             (doc_id is EMA's own stable numeric id, not a
                             derived filename), parent_record_id =
                             product_number.

Documents are discovered from the SAME bulk documents feed for every
ADC-candidate medicine on every run, entirely independent of which
medicines --limit/--since/--until/--resume selected for materialization
this run — a medicine whose own record hasn't changed (so it's outside
this run's medicine scope) can still have a newly-added or updated
document discovered and downloaded, because document discovery was never
gated by the medicine's own scope to begin with. Each document's own
checkpoint (hash-compare-then-version) already provides the incremental
efficiency of skipping unchanged downloads, so no separate resume-backlog
logic is needed at the document level.

--since/--until filter medicines by last_updated_date (client-side — the
bulk feed has no server-side filtering at all). --resume for medicines
uses the same failure-safe design as SEC/FDA: the cursor advances
unconditionally every run; any medicine not yet successfully
materialized is unioned back into scope regardless of date; fresh/
in-range medicines always get priority over that backlog within a
--limit budget.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from dotenv import load_dotenv

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from jobs.ema.client import EMA_EPAR_DOCUMENTS_JSON_URL, EMA_MEDICINES_JSON_URL, RATE_LIMIT, EMAClient
from jobs.ema.parser import is_adc_candidate, parse_epar_documents_json, parse_medicines_json, within_date_range
from jobs.ema.report import build_report

PATTERNS_PATH = Path("configs/ema_adc_substance_patterns.yaml")
MEDICINE_EXTRA_FIELDS = [
    "product_number", "status", "active_substance", "therapeutic_area",
    "marketing_authorisation_holder", "authorisation_date", "withdrawal_date",
]
DOCUMENT_EXTRA_FIELDS = ["doc_type"]
LICENSE_NOTE = "EMA regulatory record, public disclosure."

MEDICINE_NAMESPACE = "medicine_records"
DOCUMENT_NAMESPACE = "document_records"
BULK_NAMESPACE = "bulk_records"

DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]
DOCUMENT_ATTEMPT_COLUMNS = [
    "source", "source_record_id", "parent_record_id", "run_id", "attempted_at",
    "status", "http_status", "error", "content_hash", "version",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_patterns_config(path: Path) -> tuple[str, int, list[str]]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data["query_id"], data["query_version"], list(data.get("substance_patterns") or [])


def _medicine_content_bytes(medicine) -> bytes:
    return json.dumps(medicine.raw_row, sort_keys=True, default=str).encode("utf-8")


def _feed_timestamp_date(json_bytes: bytes) -> str | None:
    try:
        meta = json.loads(json_bytes).get("meta") or {}
    except (ValueError, TypeError):
        return None
    ts = meta.get("timestamp")
    return ts[:10] if ts else None


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="ema", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _document_attempt_row(
    doc_key: str, parent_record_id: str, run_id: str, attempted_at: str, status: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="ema", source_record_id=doc_key, parent_record_id=parent_record_id,
        run_id=run_id, attempted_at=attempted_at, status=status,
        http_status=http_status, error=error, content_hash=content_hash, version=version,
    )


class EMAJob(AcquisitionJob):
    name = "ema"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--patterns-file", type=str, default=str(PATTERNS_PATH),
            help="Path to the ADC substance-pattern discovery config YAML.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        load_dotenv()
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        client = EMAClient(RetryingClient(RateLimiter(RATE_LIMIT)))
        query_id, query_version, patterns = _load_patterns_config(Path(args.patterns_file))
        if not patterns:
            raise RuntimeError(f"no substance patterns found in {args.patterns_file}")
        query_text = f"active_substance/name matches one of: {', '.join(patterns)}"

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))

        try:
            medicines_bytes = client.fetch_medicines_json()
            documents_bytes = client.fetch_epar_documents_json()
        except requests.RequestException as exc:
            raise RuntimeError(f"could not fetch EMA bulk JSON feed: {exc}") from exc
        all_medicines = parse_medicines_json(medicines_bytes)
        all_documents = parse_epar_documents_json(documents_bytes)
        candidates = {m.product_number: m for m in all_medicines if is_adc_candidate(m, patterns)}
        candidate_documents = [d for d in all_documents if d.product_number in candidates]

        since = args.since
        used_resume_cursor = False
        if args.resume and not since:
            since = checkpoint.get("last_success_max_date")
            used_resume_cursor = True
        until = args.until

        if since or until:
            in_range = {pn: m for pn, m in candidates.items() if within_date_range(m.last_updated_date, since, until)}
        else:
            in_range = dict(candidates)
        fresh_product_numbers = set(in_range.keys())

        chosen = dict(in_range)
        if used_resume_cursor:
            resolved_pns = checkpoint.get(MEDICINE_NAMESPACE, {})
            for pn, m in candidates.items():
                if pn in fresh_product_numbers or pn in resolved_pns:
                    continue
                chosen[pn] = m

        all_ids = list(chosen.keys())
        result.queries_run = 1
        result.records_discovered = len(all_ids)

        retry_backlog_ids = sorted(pn for pn in all_ids if pn not in fresh_product_numbers)
        ordered_ids = sorted(fresh_product_numbers & set(all_ids)) + retry_backlog_ids
        target_ids = ordered_ids[: args.limit] if args.limit else ordered_ids

        now = _now_iso()
        run_id = now
        discovery_path = output_dir / "manifests" / "ema_discovery.parquet"

        if not args.dry_run:
            discovery_rows = [
                dict(
                    source="ema", source_record_id=pn, query_id=query_id, query_version=query_version,
                    query_text=query_text, discovered_at=now, run_id=run_id,
                )
                for pn in all_ids
            ]
            append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        if args.dry_run:
            result.notes.append(f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered medicines")
            result.notes.append(f"{len(candidate_documents)} documents across all {len(candidates)} ADC-candidate medicines would be checked, independent of --limit")
            if retry_backlog_ids:
                result.notes.append(
                    f"{len(retry_backlog_ids)} of those are --resume backlog retries (unresolved, predate the cursor) — "
                    "fresh/in-range medicines are prioritized first within --limit"
                )
            return result

        bulk_manifest_path = output_dir / "manifests" / "ema_bulk.parquet"
        manifest_path = output_dir / "manifests" / "ema.parquet"
        attempts_path = output_dir / "manifests" / "ema_attempts.parquet"
        documents_manifest_path = output_dir / "manifests" / "ema_documents.parquet"
        documents_attempts_path = output_dir / "manifests" / "ema_documents_attempts.parquet"

        # --- Raw bulk source snapshots: preserved exactly as downloaded,
        # so a future EMA schema/data change never leaves us without the
        # actual input that produced this run's discovery decisions. ---
        bulk_content_rows = []
        for bulk_id, bulk_bytes, bulk_url in [
            ("medicines_bulk", medicines_bytes, EMA_MEDICINES_JSON_URL),
            ("documents_bulk", documents_bytes, EMA_EPAR_DOCUMENTS_JSON_URL),
        ]:
            bulk_hash = sha256_bytes(bulk_bytes)
            prior_bulk_state = checkpoint_store.get_record_state(checkpoint, bulk_id, namespace=BULK_NAMESPACE)
            bulk_raw_dir = output_dir / "raw" / "ema" / "bulk" / bulk_id
            if prior_bulk_state and prior_bulk_state.get("content_hash") == bulk_hash:
                continue
            bulk_version = (prior_bulk_state["version"] + 1) if prior_bulk_state else 1
            bulk_raw_dir.mkdir(parents=True, exist_ok=True)
            bulk_raw_path = bulk_raw_dir / f"v{bulk_version}.json"
            bulk_raw_path.write_bytes(bulk_bytes)
            checkpoint_store.set_record_state(checkpoint, bulk_id, bulk_hash, bulk_version, now, namespace=BULK_NAMESPACE)
            bulk_content_rows.append(
                new_manifest_row(
                    source="ema",
                    source_record_id=bulk_id,
                    source_record_type="ema_bulk_source",
                    title=bulk_id,
                    url=bulk_url,
                    publication_or_release_date=_feed_timestamp_date(bulk_bytes),
                    retrieved_at=now,
                    query_id=query_id,
                    query_text=query_text,
                    raw_file_path=str(bulk_raw_path),
                    raw_format="json",
                    content_hash=bulk_hash,
                    download_status="success",
                    http_status=200,
                    license_or_access_note=LICENSE_NOTE,
                    parent_record_id=None,
                    version=bulk_version,
                    notes=None,
                )
            )
        write_manifest(bulk_content_rows, bulk_manifest_path)

        content_rows = []
        attempt_rows = []

        for pn in target_ids:
            medicine = chosen[pn]
            content_bytes = _medicine_content_bytes(medicine)
            content_hash = sha256_bytes(content_bytes)
            prior_state = checkpoint_store.get_record_state(checkpoint, pn, namespace=MEDICINE_NAMESPACE)

            if prior_state and prior_state.get("content_hash") == content_hash:
                result.records_skipped_unchanged += 1
                version = prior_state["version"]
                status = "skipped_unchanged"
            else:
                version = (prior_state["version"] + 1) if prior_state else 1
                raw_dir = output_dir / "raw" / "ema" / pn.replace("/", "_")
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.json"
                raw_path.write_bytes(content_bytes)
                checkpoint_store.set_record_state(checkpoint, pn, content_hash, version, now, namespace=MEDICINE_NAMESPACE)
                result.records_downloaded += 1
                status = "success"
                content_rows.append(
                    new_manifest_row(
                        extra_fields=MEDICINE_EXTRA_FIELDS,
                        source="ema",
                        source_record_id=pn,
                        source_record_type="ema_medicine",
                        title=f"{medicine.name} ({medicine.active_substance})",
                        url=medicine.epar_url,
                        publication_or_release_date=medicine.last_updated_date,
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
                        product_number=pn,
                        status=medicine.status,
                        active_substance=medicine.active_substance,
                        therapeutic_area=medicine.therapeutic_area,
                        marketing_authorisation_holder=medicine.marketing_authorisation_holder,
                        authorisation_date=medicine.authorisation_date,
                        withdrawal_date=medicine.withdrawal_date,
                    )
                )

            attempt_rows.append(
                _record_row(pn, run_id, now, status, query_id, query_text, http_status=200, content_hash=content_hash, version=version)
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=MEDICINE_EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)

        # --- Documents: independent lifecycle, processed for EVERY
        # ADC-candidate medicine on every run, regardless of --limit or
        # which medicines' own records changed this run — a medicine
        # outside this run's scope can still have new/updated documents
        # discovered, because document discovery was never gated by the
        # medicine's own scope. ---
        document_content_rows = []
        document_attempt_rows = []
        for doc in candidate_documents:
            doc_key = f"{doc.product_number}:{doc.doc_id}"
            try:
                doc_bytes = client.fetch_document(doc.url)
            except requests.RequestException as exc:
                logger.warning("document=%s fetch failed: %s", doc_key, exc)
                failure_logger.info("document=%s error=%s", doc_key, exc)
                document_attempt_rows.append(_document_attempt_row(doc_key, doc.product_number, run_id, now, "failed", error=str(exc)))
                continue

            doc_hash = sha256_bytes(doc_bytes)
            prior_doc_state = checkpoint_store.get_record_state(checkpoint, doc_key, namespace=DOCUMENT_NAMESPACE)

            if prior_doc_state and prior_doc_state.get("content_hash") == doc_hash:
                document_attempt_rows.append(
                    _document_attempt_row(doc_key, doc.product_number, run_id, now, "skipped_unchanged", content_hash=doc_hash, version=prior_doc_state["version"])
                )
                continue

            doc_version = (prior_doc_state["version"] + 1) if prior_doc_state else 1
            doc_dir = output_dir / "raw" / "ema" / doc.product_number.replace("/", "_") / "documents"
            doc_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(urlparse(doc.url).path).suffix.lstrip(".") or "pdf"
            doc_path = doc_dir / f"v{doc_version}_{doc.doc_id}.{suffix}"
            doc_path.write_bytes(doc_bytes)
            checkpoint_store.set_record_state(checkpoint, doc_key, doc_hash, doc_version, now, namespace=DOCUMENT_NAMESPACE)

            document_content_rows.append(
                new_manifest_row(
                    extra_fields=DOCUMENT_EXTRA_FIELDS,
                    source="ema",
                    source_record_id=doc_key,
                    source_record_type="ema_document",
                    title=f"{doc.doc_type or 'document'} — {doc.product_number}",
                    url=doc.url,
                    publication_or_release_date=doc.last_updated or doc.first_published,
                    retrieved_at=now,
                    query_id=query_id,
                    query_text=query_text,
                    raw_file_path=str(doc_path),
                    raw_format=suffix,
                    content_hash=doc_hash,
                    download_status="success",
                    http_status=200,
                    license_or_access_note=LICENSE_NOTE,
                    parent_record_id=doc.product_number,
                    version=doc_version,
                    notes=None,
                    doc_type=doc.doc_type,
                )
            )
            document_attempt_rows.append(
                _document_attempt_row(doc_key, doc.product_number, run_id, now, "success", content_hash=doc_hash, version=doc_version)
            )

        write_manifest(document_content_rows, documents_manifest_path, extra_fields=DOCUMENT_EXTRA_FIELDS)
        append_only(document_attempt_rows, documents_attempts_path, DOCUMENT_ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)
        checkpoint["last_run_at"] = now
        checkpoint["last_success_max_date"] = until or now[:10]
        checkpoint_store.save(checkpoint)

        report_text = build_report(
            result=result,
            manifest_df=manifest_df,
            unique_ids=set(all_ids),
            document_attempted=len(document_attempt_rows),
            document_new_or_changed=sum(1 for r in document_attempt_rows if r["status"] == "success"),
            document_unchanged=sum(1 for r in document_attempt_rows if r["status"] == "skipped_unchanged"),
            document_failed=sum(1 for r in document_attempt_rows if r["status"] == "failed"),
        )
        report_path = output_dir.parent / "reports" / "acquisition" / "ema.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
