"""Job 07: EMA acquisition (Prompt.md section 15).

EMA has no public REST API for this (unlike FDA's openFDA) — it publishes
a single bulk XLSX covering every EMA-authorised medicine
(https://www.ema.europa.eu/en/medicines/download-medicine-data, verified
live 2026-08-12), refreshed periodically, plus a static per-medicine EPAR
HTML page listing its actual documents (product information, assessment
reports, ...) as plain PDF links.

Discovery is systematic INN-suffix matching (configs/ema_adc_substance_patterns.yaml:
vedotin, emtansine, deruxtecan, ...) against the bulk file's Name/Active
substance columns — standardized WHO stems for ADC linker/payload
chemistry, not a manually maintained list of specific approved drugs (see
that config file for the live-verification details), same spirit as
Job 06 (FDA)'s full-text label search.

Two levels (EMA's own data model, unlike FDA/SEC, doesn't expose a
separate "submissions" list — a medicine's own record IS the top-level
entity, and EPAR documents are its direct children):

- ema.parquet             — medicine content-version manifest, keyed by
                            EMA product number (e.g. "EMEA/H/C/002455").
                            Content is the medicine's COMPLETE raw XLSX
                            row (every column), not a reconstructed
                            subset — same fix Job 06 (FDA) needed a
                            review round to arrive at, applied
                            proactively here. Authorisation history and
                            withdrawal information (Prompt.md's explicit
                            list) live here as structured date fields.
- ema_documents.parquet   — the actual EPAR documents (product
                            information, assessment reports, safety
                            updates, ... — Prompt.md's explicit list) as
                            a SEPARATE, independently versioned artifact,
                            keyed by "{product_number}:{filename}",
                            parent_record_id = product_number — same
                            pattern as SEC's exhibits / FDA's documents.

The EPAR-page fetch itself (which enumerates a medicine's documents) has
its own self-healing attempt identity ("{product_number}:__epar_page__"),
same fix Job 06 needed a review round to arrive at for its filing-index
equivalent — applied proactively here too.

There is no per-medicine "reconciliation" fetch the way FDA needs one
(the medicine's full row is already in hand from the one bulk download),
so there is no separate discovery/reconciliation durability split the
way FDA needed — discovery and content materialization happen from the
same already-fetched data. ema_discovery.parquet records which
substance-pattern(s) matched each medicine.

--since/--until filter by each medicine's own last_updated_date
(client-side — the bulk file has no server-side filtering at all).
--resume uses the SAME failure-safe design as SEC/FDA (applied
proactively, not waiting to be caught on it again): the cursor advances
unconditionally every run; any medicine not yet successfully
materialized, or with an unresolved document/EPAR-page failure, is
unioned back into scope regardless of date; fresh/in-range medicines
always get priority over that backlog within a --limit budget.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
import yaml
from dotenv import load_dotenv

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from jobs.ema.client import RATE_LIMIT, EMAClient
from jobs.ema.parser import is_adc_candidate, parse_epar_documents, parse_medicines_xlsx, within_date_range
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

DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]
DOCUMENT_ATTEMPT_COLUMNS = [
    "source", "source_record_id", "parent_record_id", "run_id", "attempted_at",
    "status", "http_status", "error", "content_hash", "version",
]

EPAR_PAGE_SUFFIX = ":__epar_page__"
QUERY_ID = "EMA_ADC_SUBSTANCE_PATTERN"
QUERY_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_patterns(path: Path) -> list[str]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("substance_patterns") or [])


def _medicine_content_bytes(medicine) -> bytes:
    return json.dumps(medicine.raw_row, sort_keys=True, default=str).encode("utf-8")


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


def _unresolved_document_parent_keys(documents_attempts_path: Path) -> set[str]:
    """product_numbers with a document (or the EPAR-page fetch itself,
    identity f"{product_number}{EPAR_PAGE_SUFFIX}") whose MOST RECENT
    recorded attempt was a failure with no later success — same rationale
    as jobs/sec/job.py's _unresolved_exhibit_parent_ids / jobs/fda/job.py's
    _unresolved_document_parent_keys."""
    if not documents_attempts_path.exists():
        return set()
    df = pd.read_parquet(documents_attempts_path)
    if df.empty:
        return set()
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    failed_ids = set(latest.loc[latest["status"] == "failed", "source_record_id"])
    return {doc_key.split(":", 1)[0] for doc_key in failed_ids}


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
        patterns = _load_patterns(Path(args.patterns_file))
        if not patterns:
            raise RuntimeError(f"no substance patterns found in {args.patterns_file}")
        query_text = f"active_substance/name matches one of: {', '.join(patterns)}"

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))

        try:
            xlsx_bytes = client.fetch_medicines_xlsx()
        except requests.RequestException as exc:
            raise RuntimeError(f"could not fetch EMA bulk medicines file: {exc}") from exc
        all_medicines = parse_medicines_xlsx(xlsx_bytes)
        candidates = {m.product_number: m for m in all_medicines if is_adc_candidate(m, patterns)}

        since = args.since
        used_resume_cursor = False
        if args.resume and not since:
            since = checkpoint.get("last_success_max_date")
            used_resume_cursor = True
        until = args.until

        unresolved_document_parent_keys: set[str] = set()
        if used_resume_cursor:
            unresolved_document_parent_keys = _unresolved_document_parent_keys(
                output_dir / "manifests" / "ema_documents_attempts.parquet"
            )

        if since or until:
            in_range = {pn: m for pn, m in candidates.items() if within_date_range(m.last_updated_date, since, until)}
        else:
            in_range = dict(candidates)
        fresh_product_numbers = set(in_range.keys())

        chosen = dict(in_range)
        if used_resume_cursor:
            resolved_pns = checkpoint.get(MEDICINE_NAMESPACE, {})
            for pn, m in candidates.items():
                if pn in fresh_product_numbers:
                    continue
                if pn not in resolved_pns or pn in unresolved_document_parent_keys:
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
                    source="ema", source_record_id=pn, query_id=QUERY_ID, query_version=QUERY_VERSION,
                    query_text=query_text, discovered_at=now, run_id=run_id,
                )
                for pn in all_ids
            ]
            append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        if args.dry_run:
            result.notes.append(f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered medicines")
            if retry_backlog_ids:
                result.notes.append(
                    f"{len(retry_backlog_ids)} of those are --resume backlog retries (unresolved, predate the cursor) — "
                    "fresh/in-range medicines are prioritized first within --limit"
                )
            return result

        manifest_path = output_dir / "manifests" / "ema.parquet"
        attempts_path = output_dir / "manifests" / "ema_attempts.parquet"
        documents_manifest_path = output_dir / "manifests" / "ema_documents.parquet"
        documents_attempts_path = output_dir / "manifests" / "ema_documents_attempts.parquet"

        content_rows = []
        attempt_rows = []
        document_content_rows = []
        document_attempt_rows = []

        for pn in target_ids:
            medicine = chosen[pn]
            safe_id = pn.replace("/", "_")
            raw_dir = output_dir / "raw" / "ema" / safe_id

            content_bytes = _medicine_content_bytes(medicine)
            content_hash = sha256_bytes(content_bytes)
            prior_state = checkpoint_store.get_record_state(checkpoint, pn, namespace=MEDICINE_NAMESPACE)

            if prior_state and prior_state.get("content_hash") == content_hash:
                result.records_skipped_unchanged += 1
                version = prior_state["version"]
                status = "skipped_unchanged"
            else:
                version = (prior_state["version"] + 1) if prior_state else 1
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
                        query_id=QUERY_ID,
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
                _record_row(pn, run_id, now, status, QUERY_ID, query_text, http_status=200, content_hash=content_hash, version=version)
            )

            # EPAR documents: independent lifecycle, attempted regardless
            # of whether the medicine's own content changed this run.
            epar_page_id = f"{pn}{EPAR_PAGE_SUFFIX}"
            if not medicine.epar_url:
                document_attempt_rows.append(_document_attempt_row(epar_page_id, pn, run_id, now, "failed", error="no_epar_url"))
                continue
            try:
                html = client.fetch_epar_page(medicine.epar_url)
            except requests.RequestException as exc:
                logger.warning("medicine=%s EPAR page fetch failed: %s", pn, exc)
                document_attempt_rows.append(_document_attempt_row(epar_page_id, pn, run_id, now, "failed", error=str(exc)))
                continue
            else:
                document_attempt_rows.append(_document_attempt_row(epar_page_id, pn, run_id, now, "success"))

            for doc in parse_epar_documents(html):
                doc_key = f"{pn}:{doc.filename}"
                try:
                    doc_bytes = client.fetch_document(doc.url)
                except requests.RequestException as exc:
                    logger.warning("document=%s fetch failed: %s", doc_key, exc)
                    failure_logger.info("document=%s error=%s", doc_key, exc)
                    document_attempt_rows.append(_document_attempt_row(doc_key, pn, run_id, now, "failed", error=str(exc)))
                    continue

                doc_hash = sha256_bytes(doc_bytes)
                prior_doc_state = checkpoint_store.get_record_state(checkpoint, doc_key, namespace=DOCUMENT_NAMESPACE)

                if prior_doc_state and prior_doc_state.get("content_hash") == doc_hash:
                    document_attempt_rows.append(
                        _document_attempt_row(doc_key, pn, run_id, now, "skipped_unchanged", content_hash=doc_hash, version=prior_doc_state["version"])
                    )
                    continue

                doc_version = (prior_doc_state["version"] + 1) if prior_doc_state else 1
                doc_dir = raw_dir / "documents"
                doc_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(urlparse(doc.url).path).suffix.lstrip(".") or "pdf"
                doc_path = doc_dir / f"v{doc_version}_{doc.filename}"
                doc_path.write_bytes(doc_bytes)
                checkpoint_store.set_record_state(checkpoint, doc_key, doc_hash, doc_version, now, namespace=DOCUMENT_NAMESPACE)

                document_content_rows.append(
                    new_manifest_row(
                        extra_fields=DOCUMENT_EXTRA_FIELDS,
                        source="ema",
                        source_record_id=doc_key,
                        source_record_type="ema_document",
                        title=f"{doc.doc_type or 'document'} — {medicine.name}",
                        url=doc.url,
                        publication_or_release_date=doc.last_updated,
                        retrieved_at=now,
                        query_id=QUERY_ID,
                        query_text=query_text,
                        raw_file_path=str(doc_path),
                        raw_format=suffix,
                        content_hash=doc_hash,
                        download_status="success",
                        http_status=200,
                        license_or_access_note=LICENSE_NOTE,
                        parent_record_id=pn,
                        version=doc_version,
                        notes=None,
                        doc_type=doc.doc_type,
                    )
                )
                document_attempt_rows.append(
                    _document_attempt_row(doc_key, pn, run_id, now, "success", content_hash=doc_hash, version=doc_version)
                )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=MEDICINE_EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        write_manifest(document_content_rows, documents_manifest_path, extra_fields=DOCUMENT_EXTRA_FIELDS)
        append_only(document_attempt_rows, documents_attempts_path, DOCUMENT_ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)
        checkpoint["last_run_at"] = now
        checkpoint["last_success_max_date"] = until or now[:10]
        checkpoint_store.save(checkpoint)

        real_document_attempt_rows = [r for r in document_attempt_rows if not r["source_record_id"].endswith(EPAR_PAGE_SUFFIX)]
        report_text = build_report(
            result=result,
            manifest_df=manifest_df,
            unique_ids=set(all_ids),
            document_attempted=len(real_document_attempt_rows),
            document_new_or_changed=sum(1 for r in real_document_attempt_rows if r["status"] == "success"),
            document_unchanged=sum(1 for r in real_document_attempt_rows if r["status"] == "skipped_unchanged"),
            document_failed=sum(1 for r in real_document_attempt_rows if r["status"] == "failed"),
        )
        report_path = output_dir.parent / "reports" / "acquisition" / "ema.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
