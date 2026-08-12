"""Job 06: FDA acquisition (Prompt.md section 14).

Discovery is NOT a manually maintained ADC drug-name list (Prompt.md
section 14 explicitly prohibits that) — it's full-text search over
openFDA's own structured product LABEL text (configs/fda_queries.yaml),
verified live to catch all 15 major FDA-approved ADCs even though FDA's
structured pharmacologic-class tags are not reliably populated for ADCs
(see configs/fda_queries.yaml for the live-verification details). Each
label hit's `openfda.application_number` is the actual discovery unit;
jobs/fda/job.py then reconciles each discovered application_number
against the authoritative /drug/drugsfda.json endpoint (application +
product identity, submissions, application_docs) — same two-step
discover-then-reconcile shape as Crossref's DOI reconciliation.

Three independent levels, each with its own content-version manifest,
discovery/attempts ledger(s), and checkpoint namespace — mirroring SEC
EDGAR's company -> filing -> exhibit model one level deeper, since
Drugs@FDA's own data model
(https://open.fda.gov/apis/drug/drugsfda/understanding-the-api-results/)
genuinely has three parts (application identity, submissions,
application_docs), not two:

    application_number  ~ SEC's CIK, but UNLIKE a CIK it is itself a
                           discovery outcome (from the label search), not
                           a manually curated identifier — so it needs
                           its own discovery+attempts ledger, which SEC's
                           company registry never needed.
    submission            ~ SEC's filing
    application_doc        ~ SEC's exhibit

- fda_applications.parquet            — application/product identity
                                         content-version manifest, keyed
                                         by application_number. Content
                                         is the COMPLETE raw Drugs@FDA
                                         record as returned (not a
                                         reconstructed subset) — Prompt.md
                                         section 14's product
                                         name/active-ingredient key
                                         identifiers live here, not on
                                         the submission row.
- fda_applications_discovery.parquet  — append-only: every
                                         (application_number, query_id)
                                         hit from label search, written
                                         UNCONDITIONALLY, before the
                                         Drugs@FDA reconciliation fetch
                                         is even attempted. A label match
                                         that fails to reconcile must
                                         still leave durable discovery
                                         provenance — it must never look
                                         like the identifier was never
                                         found at all.
- fda_applications_attempts.parquet   — append-only: success / not_found
                                         (openFDA's 404-no-match
                                         convention) / failed (network
                                         error), one row per application
                                         per run.
- fda_submissions.parquet             — submission content-version
                                         manifest, keyed by submission_key
                                         ("{application_number}_{TYPE}{NUMBER}",
                                         e.g. "BLA125388_ORIG1"),
                                         parent_record_id = application_number.
                                         A submission's "content" is its
                                         own metadata (status/date/docs
                                         list) — there is no separate
                                         network fetch for the submission
                                         row itself, so it can never
                                         itself fail; it only versions
                                         when that metadata changes.
- fda_submissions_discovery.parquet   — append-only: every submission
                                         inherits its parent application's
                                         discovering query_id(s) — same
                                         pattern as SEC filings inheriting
                                         their company's query.
- fda_submissions_attempts.parquet    — append-only: success /
                                         skipped_unchanged (never
                                         "failed" — see above).
- fda_documents.parquet                — the actual downloadable documents
                                         (labels, approval letters, review
                                         documents, ... — Prompt.md's
                                         explicit list) as a SEPARATE,
                                         independently versioned artifact,
                                         keyed by "{submission_key}:{doc_id}",
                                         parent_record_id = submission_key —
                                         same fix as Europe PMC's full text
                                         / SEC's exhibits.
- fda_documents_attempts.parquet       — its own append-only attempts
                                         ledger.

--since/--until filter by each submission's own submission_status_date,
applied client-side (openFDA's date-range search only determines whether
an APPLICATION matches at all, not which of its submissions to return —
verified live: a date-bounded search still returns every submission for
a matching application). Applications themselves are NOT date-filtered —
every discovered application's Drugs@FDA record is always fetched and
materialized in full every run (cheap; there are ~15 of them), the same
way SEC always pulls each company's complete filing list every run
regardless of date.

--resume reuses the prior run's --until (or now) as an implicit --since
for SUBMISSIONS, with the SAME failure-safe design SEC EDGAR's Job 05
needed three review rounds to arrive at (applied proactively here from
the start rather than being caught on it again): the cursor advances
unconditionally every run, but any submission not yet in the success
checkpoint, or with an unresolved (most-recent-status still "failed")
document, is unioned back into scope regardless of its own date; and when
--limit is set, fresh/in-range submissions always get priority over that
backlog so a persistently-failing old document can never starve out new
submissions. No terminal-failure category is classified yet (unlike SEC's
confirmed-permanent no_primary_document) — none has been observed live
for FDA; add one if a genuinely permanent FDA-side gap is ever confirmed,
per the same reasoning.

openFDA's authentication is optional (unlike SEC's mandatory contact
requirement): 240 req/min either way; 1,000 req/day without a key vs.
120,000 req/day with one (verified live). FDA_API_KEY is read from the
environment if present but never required.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from dotenv import load_dotenv

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.query_registry import active_queries, load_queries
from jobs.fda.client import MAX_PAGE_SIZE, RATE_LIMIT, FDAClient
from jobs.fda.parser import parse_application, parse_submissions, within_date_range
from jobs.fda.report import build_report

QUERIES_PATH = Path("configs/fda_queries.yaml")
APPLICATION_EXTRA_FIELDS = ["application_number", "sponsor_name", "brand_names", "active_ingredients", "product_numbers"]
SUBMISSION_EXTRA_FIELDS = [
    "application_number", "submission_type", "submission_number", "submission_status",
    "submission_class_code", "submission_class_code_description",
]
DOCUMENT_EXTRA_FIELDS = ["doc_type", "doc_date"]
LICENSE_NOTE = "FDA regulatory record (openFDA / Drugs@FDA), public disclosure."

APPLICATION_NAMESPACE = "application_records"
SUBMISSION_NAMESPACE = "submission_records"
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

_APP_NUMBER_DIGITS_RE = re.compile(r"(\d+)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _application_overview_url(application_number: str) -> str:
    m = _APP_NUMBER_DIGITS_RE.search(application_number)
    digits = m.group(1) if m else application_number
    return f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={digits}"


def _submission_content_bytes(ps) -> bytes:
    payload = {
        "submission_type": ps.submission_type,
        "submission_number": ps.submission_number,
        "submission_status": ps.submission_status,
        "submission_status_date": ps.submission_status_date,
        "submission_class_code": ps.submission_class_code,
        "submission_class_code_description": ps.submission_class_code_description,
        "docs": sorted(
            [{"id": d.doc_id, "type": d.doc_type, "url": d.url, "date": d.doc_date} for d in ps.docs],
            key=lambda d: d["id"],
        ),
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="fda", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _document_attempt_row(
    doc_key: str, parent_record_id: str, run_id: str, attempted_at: str, status: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="fda", source_record_id=doc_key, parent_record_id=parent_record_id,
        run_id=run_id, attempted_at=attempted_at, status=status,
        http_status=http_status, error=error, content_hash=content_hash, version=version,
    )


def _unresolved_document_parent_keys(documents_attempts_path: Path) -> set[str]:
    """submission_keys with a document whose MOST RECENT recorded attempt
    was a failure with no later success — see jobs/sec/job.py's identical
    _unresolved_exhibit_parent_ids for the full rationale (a later success
    self-heals the identity out of this set automatically)."""
    if not documents_attempts_path.exists():
        return set()
    df = pd.read_parquet(documents_attempts_path)
    if df.empty:
        return set()
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    failed_ids = set(latest.loc[latest["status"] == "failed", "source_record_id"])
    return {doc_key.split(":", 1)[0] for doc_key in failed_ids}


class FDAJob(AcquisitionJob):
    name = "fda"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--queries-file", type=str, default=str(QUERIES_PATH),
            help="Path to the FDA label-search discovery query registry YAML.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        load_dotenv()
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        api_key = os.environ.get("FDA_API_KEY") or None
        client = FDAClient(RetryingClient(RateLimiter(RATE_LIMIT)), api_key=api_key)

        queries = active_queries(load_queries(Path(args.queries_file)))
        if not queries:
            raise RuntimeError(f"no active queries found in {args.queries_file}")
        query_text_by_id = {q.query_id: q.query_text for q in queries}
        query_version_by_id = {q.query_id: q.query_version for q in queries}

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        result.notes.append("used FDA_API_KEY (120,000 req/day)" if api_key else "no FDA_API_KEY configured (1,000 req/day)")

        # --- Discovery: full-text label search, never a manual drug list ---
        application_first_query: dict[str, tuple[str, str]] = {}
        application_query_hits: dict[str, set[str]] = defaultdict(set)
        query_id_counts: Counter = Counter()

        for query in queries:
            skip = 0
            hits_for_query = 0
            while True:
                try:
                    results = client.search_label(query.query_text, skip=skip, limit=MAX_PAGE_SIZE)
                except requests.RequestException as exc:
                    logger.error("query=%s label search failed: %s", query.query_id, exc)
                    failure_logger.info("query=%s error=%s", query.query_id, exc)
                    break
                for r in results:
                    for app in (r.get("openfda") or {}).get("application_number") or []:
                        application_query_hits[app].add(query.query_id)
                        if app not in application_first_query:
                            application_first_query[app] = (query.query_id, query.query_text)
                hits_for_query += len(results)
                skip += len(results)
                if len(results) < MAX_PAGE_SIZE:
                    break
            query_id_counts[query.query_id] = hits_for_query
            logger.info("query %s: %d label hits", query.query_id, hits_for_query)

        all_applications = list(application_first_query.keys())
        duplicate_applications = {app for app, qids in application_query_hits.items() if len(qids) > 1}

        # --- Application-level discovery ledger: written UNCONDITIONALLY
        # right after label search, BEFORE the Drugs@FDA reconciliation
        # loop below is even entered — discovery durability must not
        # depend on reconciliation succeeding, or even running to
        # completion. (Not written on --dry-run, same as every other
        # job's discovery ledger, since dry-run persists nothing.) ---
        now = _now_iso()
        run_id = now
        applications_discovery_path = output_dir / "manifests" / "fda_applications_discovery.parquet"
        if not args.dry_run:
            applications_discovery_rows = [
                dict(
                    source="fda", source_record_id=app, query_id=qid, query_version=query_version_by_id[qid],
                    query_text=query_text_by_id[qid], discovered_at=now, run_id=run_id,
                )
                for app, qids in application_query_hits.items()
                for qid in sorted(qids)
            ]
            append_only(applications_discovery_rows, applications_discovery_path, DISCOVERY_COLUMNS)

        since = args.since
        used_resume_cursor = False
        if args.resume and not since:
            since = checkpoint.get("last_success_max_date")
            used_resume_cursor = True
        until = args.until

        # Same failure-safe --resume design as SEC EDGAR's (post-review)
        # Job 05: the implicit resume cursor is a discovery-efficiency
        # bound, not caller-requested scope, so an unresolved document
        # must be unioned back into scope regardless of its own date.
        unresolved_document_parent_keys: set[str] = set()
        if used_resume_cursor:
            unresolved_document_parent_keys = _unresolved_document_parent_keys(
                output_dir / "manifests" / "fda_documents_attempts.parquet"
            )

        # --- Reconciliation: pull each discovered application's full
        # Drugs@FDA record (application/product identity + submissions).
        # An application's outcome is tracked regardless of whether it
        # resolves, so label-search discovery provenance is never lost
        # just because reconciliation later fails or comes up empty. ---
        application_outcomes: dict[str, dict] = {}  # app -> {status, record, error}
        submission_first_query: dict[str, tuple[str, str]] = {}
        submission_query_hits: dict[str, set[str]] = defaultdict(set)
        record_submissions: dict[str, object] = {}  # submission_key -> ParsedSubmission
        fresh_submission_keys: set[str] = set()

        for application_number in sorted(all_applications):
            try:
                drugsfda_record = client.get_drugsfda_by_application(application_number)
            except requests.RequestException as exc:
                logger.error("application=%s drugsfda fetch failed: %s", application_number, exc)
                failure_logger.info("application=%s error=%s", application_number, exc)
                application_outcomes[application_number] = {"status": "failed", "record": None, "error": str(exc)}
                continue
            if drugsfda_record is None:
                logger.warning("application=%s label-discovered but no drugsfda record found", application_number)
                application_outcomes[application_number] = {"status": "not_found", "record": None, "error": None}
                continue
            application_outcomes[application_number] = {"status": "success", "record": drugsfda_record, "error": None}

            parsed_submissions = parse_submissions(drugsfda_record)
            q_ids = application_query_hits[application_number]
            q_id_primary, q_text_primary = application_first_query[application_number]

            if since or until:
                in_range = [ps for ps in parsed_submissions if within_date_range(ps.submission_status_date, since, until)]
            else:
                in_range = parsed_submissions
            fresh_submission_keys.update(ps.submission_key for ps in in_range)
            chosen = in_range

            if used_resume_cursor:
                in_scope_keys = {ps.submission_key for ps in in_range}
                resolved_keys = checkpoint.get(SUBMISSION_NAMESPACE, {})
                unresolved = [
                    ps for ps in parsed_submissions
                    if ps.submission_key not in in_scope_keys
                    and (
                        ps.submission_key not in resolved_keys
                        or ps.submission_key in unresolved_document_parent_keys
                    )
                ]
                chosen = in_range + unresolved

            for ps in chosen:
                key = ps.submission_key
                submission_query_hits[key] |= q_ids
                if key not in submission_first_query:
                    submission_first_query[key] = (q_id_primary, q_text_primary)
                record_submissions[key] = ps

        all_ids = list(submission_first_query.keys())
        duplicate_ids = {sid for sid, qids in submission_query_hits.items() if len(qids) > 1}

        result.queries_run = len(queries)
        result.records_discovered = len(all_ids)
        if duplicate_applications:
            result.notes.append(
                f"{len(duplicate_applications)} application(s) matched more than one discovery query "
                "(expected overlap between mechanism_of_action/description full-text hits, not a data-quality concern)"
            )

        # Fresh/in-range submissions always get priority for a --limit
        # budget over backlog retries carried in by --resume's unresolved
        # union — see jobs/sec/job.py for why this matters (a backlog of
        # still-failing old documents must never be able to starve out
        # new submissions).
        retry_backlog_ids = sorted(sid for sid in all_ids if sid not in fresh_submission_keys)
        ordered_ids = sorted(fresh_submission_keys & set(all_ids)) + retry_backlog_ids
        target_ids = ordered_ids[: args.limit] if args.limit else ordered_ids

        if args.dry_run:
            result.notes.append(f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered submissions")
            if retry_backlog_ids:
                result.notes.append(
                    f"{len(retry_backlog_ids)} of those are --resume backlog retries (unresolved, predate the cursor) — "
                    "fresh/in-range submissions are prioritized first within --limit"
                )
            return result

        applications_manifest_path = output_dir / "manifests" / "fda_applications.parquet"
        applications_attempts_path = output_dir / "manifests" / "fda_applications_attempts.parquet"
        submissions_manifest_path = output_dir / "manifests" / "fda_submissions.parquet"
        submissions_discovery_path = output_dir / "manifests" / "fda_submissions_discovery.parquet"
        submissions_attempts_path = output_dir / "manifests" / "fda_submissions_attempts.parquet"
        documents_manifest_path = output_dir / "manifests" / "fda_documents.parquet"
        documents_attempts_path = output_dir / "manifests" / "fda_documents_attempts.parquet"

        # --- Application-level content + attempts: success / not_found / failed. ---
        application_content_rows = []
        application_attempt_rows = []
        for application_number in sorted(all_applications):
            outcome = application_outcomes[application_number]
            query_id, query_text = application_first_query[application_number]

            if outcome["status"] != "success":
                application_attempt_rows.append(
                    _record_row(application_number, run_id, now, outcome["status"], query_id, query_text, error=outcome["error"])
                )
                continue

            record = outcome["record"]
            parsed_app = parse_application(record)
            raw_bytes = json.dumps(record, sort_keys=True).encode("utf-8")
            content_hash = sha256_bytes(raw_bytes)
            prior_state = checkpoint_store.get_record_state(checkpoint, application_number, namespace=APPLICATION_NAMESPACE)
            app_raw_dir = output_dir / "raw" / "fda" / application_number

            if prior_state and prior_state.get("content_hash") == content_hash:
                version = prior_state["version"]
                status = "skipped_unchanged"
            else:
                version = (prior_state["version"] + 1) if prior_state else 1
                app_raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = app_raw_dir / f"v{version}.json"
                raw_path.write_bytes(raw_bytes)
                checkpoint_store.set_record_state(checkpoint, application_number, content_hash, version, now, namespace=APPLICATION_NAMESPACE)
                status = "success"
                application_content_rows.append(
                    new_manifest_row(
                        extra_fields=APPLICATION_EXTRA_FIELDS,
                        source="fda",
                        source_record_id=application_number,
                        source_record_type="fda_application",
                        title=f"{', '.join(parsed_app.brand_names) or application_number} ({application_number})",
                        url=_application_overview_url(application_number),
                        publication_or_release_date=parsed_app.earliest_submission_date,
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
                        application_number=application_number,
                        sponsor_name=parsed_app.sponsor_name,
                        brand_names=parsed_app.brand_names,
                        active_ingredients=parsed_app.active_ingredients,
                        product_numbers=parsed_app.product_numbers,
                    )
                )

            application_attempt_rows.append(
                _record_row(application_number, run_id, now, status, query_id, query_text, http_status=200, content_hash=content_hash, version=version)
            )

        applications_manifest_df = write_manifest(application_content_rows, applications_manifest_path, extra_fields=APPLICATION_EXTRA_FIELDS)
        append_only(application_attempt_rows, applications_attempts_path, ATTEMPT_COLUMNS)

        # --- Submission-level discovery ledger (inherits parent
        # application's discovering query(ies), same pattern SEC uses for
        # filings inheriting their company's query). ---
        submissions_discovery_rows = [
            dict(
                source="fda", source_record_id=sid, query_id=qid, query_version=query_version_by_id[qid],
                query_text=query_text_by_id[qid], discovered_at=now, run_id=run_id,
            )
            for sid, qids in submission_query_hits.items()
            for qid in sorted(qids)
        ]
        append_only(submissions_discovery_rows, submissions_discovery_path, DISCOVERY_COLUMNS)

        submission_content_rows = []
        submission_attempt_rows = []
        document_content_rows = []
        document_attempt_rows = []

        for key in target_ids:
            ps = record_submissions[key]
            query_id, query_text = submission_first_query[key]
            raw_dir = output_dir / "raw" / "fda" / ps.application_number / "submissions" / key

            content_bytes = _submission_content_bytes(ps)
            content_hash = sha256_bytes(content_bytes)
            prior_state = checkpoint_store.get_record_state(checkpoint, key, namespace=SUBMISSION_NAMESPACE)

            if prior_state and prior_state.get("content_hash") == content_hash:
                result.records_skipped_unchanged += 1
                version = prior_state["version"]
                status = "skipped_unchanged"
            else:
                version = (prior_state["version"] + 1) if prior_state else 1
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.json"
                raw_path.write_bytes(content_bytes)
                checkpoint_store.set_record_state(checkpoint, key, content_hash, version, now, namespace=SUBMISSION_NAMESPACE)
                result.records_downloaded += 1
                status = "success"
                submission_content_rows.append(
                    new_manifest_row(
                        extra_fields=SUBMISSION_EXTRA_FIELDS,
                        source="fda",
                        source_record_id=key,
                        source_record_type="fda_submission",
                        title=f"{ps.application_number} {ps.submission_type}-{ps.submission_number} "
                        f"({ps.submission_class_code_description or ps.submission_class_code or 'n/a'})",
                        url=_application_overview_url(ps.application_number),
                        publication_or_release_date=ps.submission_status_date,
                        retrieved_at=now,
                        query_id=query_id,
                        query_text=query_text,
                        raw_file_path=str(raw_path),
                        raw_format="json",
                        content_hash=content_hash,
                        download_status="success",
                        http_status=200,
                        license_or_access_note=LICENSE_NOTE,
                        parent_record_id=ps.application_number,
                        version=version,
                        notes=None,
                        application_number=ps.application_number,
                        submission_type=ps.submission_type,
                        submission_number=ps.submission_number,
                        submission_status=ps.submission_status,
                        submission_class_code=ps.submission_class_code,
                        submission_class_code_description=ps.submission_class_code_description,
                    )
                )

            submission_attempt_rows.append(
                _record_row(key, run_id, now, status, query_id, query_text, http_status=200, content_hash=content_hash, version=version)
            )

            # Documents: independent lifecycle, attempted regardless of
            # whether the submission's own content changed this run.
            for doc in ps.docs:
                doc_key = f"{key}:{doc.doc_id}"
                try:
                    doc_bytes = client.fetch_document(doc.url)
                except requests.RequestException as exc:
                    logger.warning("document=%s fetch failed: %s", doc_key, exc)
                    failure_logger.info("document=%s error=%s", doc_key, exc)
                    document_attempt_rows.append(_document_attempt_row(doc_key, key, run_id, now, "failed", error=str(exc)))
                    continue

                doc_hash = sha256_bytes(doc_bytes)
                prior_doc_state = checkpoint_store.get_record_state(checkpoint, doc_key, namespace=DOCUMENT_NAMESPACE)

                if prior_doc_state and prior_doc_state.get("content_hash") == doc_hash:
                    document_attempt_rows.append(
                        _document_attempt_row(doc_key, key, run_id, now, "skipped_unchanged", content_hash=doc_hash, version=prior_doc_state["version"])
                    )
                    continue

                doc_version = (prior_doc_state["version"] + 1) if prior_doc_state else 1
                doc_dir = raw_dir / "documents"
                doc_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(urlparse(doc.url).path).suffix.lstrip(".") or "bin"
                doc_path = doc_dir / f"v{doc_version}_{doc.doc_id}.{suffix}"
                doc_path.write_bytes(doc_bytes)
                checkpoint_store.set_record_state(checkpoint, doc_key, doc_hash, doc_version, now, namespace=DOCUMENT_NAMESPACE)

                document_content_rows.append(
                    new_manifest_row(
                        extra_fields=DOCUMENT_EXTRA_FIELDS,
                        source="fda",
                        source_record_id=doc_key,
                        source_record_type="fda_document",
                        title=f"{doc.doc_type or 'document'} — {ps.application_number} {ps.submission_type}-{ps.submission_number}",
                        url=doc.url,
                        publication_or_release_date=doc.doc_date,
                        retrieved_at=now,
                        query_id=query_id,
                        query_text=query_text,
                        raw_file_path=str(doc_path),
                        raw_format=suffix,
                        content_hash=doc_hash,
                        download_status="success",
                        http_status=200,
                        license_or_access_note=LICENSE_NOTE,
                        parent_record_id=key,
                        version=doc_version,
                        notes=None,
                        doc_type=doc.doc_type,
                        doc_date=doc.doc_date,
                    )
                )
                document_attempt_rows.append(
                    _document_attempt_row(doc_key, key, run_id, now, "success", content_hash=doc_hash, version=doc_version)
                )

        submissions_manifest_df = write_manifest(submission_content_rows, submissions_manifest_path, extra_fields=SUBMISSION_EXTRA_FIELDS)
        append_only(submission_attempt_rows, submissions_attempts_path, ATTEMPT_COLUMNS)
        write_manifest(document_content_rows, documents_manifest_path, extra_fields=DOCUMENT_EXTRA_FIELDS)
        append_only(document_attempt_rows, documents_attempts_path, DOCUMENT_ATTEMPT_COLUMNS)
        result.manifest_path = str(submissions_manifest_path)
        checkpoint["last_run_at"] = now
        checkpoint["last_success_max_date"] = until or now[:10]
        checkpoint_store.save(checkpoint)

        report_text = build_report(
            result=result,
            applications_manifest_df=applications_manifest_df,
            submissions_manifest_df=submissions_manifest_df,
            query_id_counts=query_id_counts,
            unique_ids=set(all_ids),
            duplicate_ids=duplicate_ids,
            application_attempted=len(application_attempt_rows),
            application_success=sum(1 for r in application_attempt_rows if r["status"] in ("success", "skipped_unchanged")),
            application_not_found=sum(1 for r in application_attempt_rows if r["status"] == "not_found"),
            application_failed=sum(1 for r in application_attempt_rows if r["status"] == "failed"),
            document_attempted=len(document_attempt_rows),
            document_new_or_changed=sum(1 for r in document_attempt_rows if r["status"] == "success"),
            document_unchanged=sum(1 for r in document_attempt_rows if r["status"] == "skipped_unchanged"),
            document_failed=sum(1 for r in document_attempt_rows if r["status"] == "failed"),
        )
        report_path = output_dir.parent / "reports" / "acquisition" / "fda.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
