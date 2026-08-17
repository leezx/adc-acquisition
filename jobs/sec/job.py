"""Job 05: SEC EDGAR acquisition (Prompt.md section 13).

Company-centric, not query-based: for each active company's CIK(s) in
configs/company_registry.yaml, pull the full filing history from the
submissions API, filter to relevant-form filings (jobs/sec/parser.py:
10-K, 10-Q, 8-K, S-1, 20-F, 6-K + amendments), and materialize each
filing's primary document as an immutable content-version snapshot.
A company can have more than one CIK (a corporate redomicile/reincorporation
creates a new SEC filer identity — e.g. Zymeworks Inc. redomiciled from BC to
Delaware in 2022, leaving its full pre-2022 filing history under the
predecessor's CIK) — `Company.ciks` is a list, and each CIK gets its own
query_id (`SEC_FILINGS_{company_id}_{cik}`) so provenance always identifies
which filer entity a filing actually came from.

Exhibits are a SEPARATE, independently versioned artifact — same fix as
Europe PMC's full text (Prompt.md still asks to "preserve raw filing,
exhibits", and a secondary/derived artifact must never be bolted onto the
primary record's own content-version row):

- sec.parquet               — filing content-version manifest, keyed by
                               accession_number.
- sec_exhibits.parquet      — exhibit content-version manifest, keyed by
                               "{accession_number}:{filename}", with
                               parent_record_id pointing back to the filing.
- sec_exhibits_attempts.parquet — its own append-only attempts ledger.

A real exhibit is a document SEC's own filing index typed as "EX-*" (parsed
from the `{accession-number}-index.htm` page's "Document Format Files"
table via jobs/sec/parser.py:parse_document_format_table) — not "every file
in the filing directory besides the primary document", which would also
sweep in GRAPHIC/embedded-image and XBRL data files that are not exhibits.
Exhibit acquisition is attempted for every target filing regardless of
whether that filing's own primary-document fetch succeeded, failed, or was
skipped as unchanged — a primary-document failure must never suppress
exhibit acquisition for the same filing.

An exhibit is only fetched once per accession/filename (SEC filings are
immutable once filed — there's no "not available yet, retry" dynamic like
Europe PMC's open-access flag), but the same hash-compare-then-version
machinery is reused rather than special-cased, so a fetch that failed
previously (no checkpoint state was recorded) is naturally retried on the
next run.

Same three-table model as Jobs 01-04 for filings themselves:
sec_discovery.parquet is an append-only every-company-every-run ledger,
sec_attempts.parquet is an append-only every-attempt ledger. Failures never
occupy a content-version slot.

--since/--until filter discovered filings by SEC's own filing_date (the
submissions API has no server-side date filter, so this is applied
client-side after the full history is pulled); --resume reuses the prior
run's --until (or now) as an implicit --since, same convention as
Jobs 01/03. Crucially, the resume cursor advances unconditionally each
run even when some filings failed (some historical gaps are permanent —
e.g. the pre-2002 primaryDocument issue below — and must not block all
future incremental progress), so a not-yet-successful filing or exhibit
from BEFORE the resume cursor is explicitly unioned back into this run's
scope rather than silently aging out of every future --resume run once
its filing_date falls behind the cursor. This union only applies when
the --since in effect came from the resume cursor itself, not from an
explicit --since the caller typed — an explicit date range is trusted
literally, same as every other job.

Two further protections keep that retry union itself well-behaved:
(1) the filing-index page fetch has its own success/failure attempt
identity (f"{accession}{FILING_INDEX_SUFFIX}" in sec_exhibits_attempts),
so a resolved filing-index failure actually leaves the retry set instead
of being permanently stuck on its one and only ever-recorded "failed"
row; (2) a small set of unambiguously PERMANENT source-side conditions
(TERMINAL_PRIMARY_ERRORS — currently just "no_primary_document") are
excluded from the retry set for their primary document, and fresh/
in-range filings always get priority over backlog retries within a
--limit budget — otherwise a handful of permanently-broken historical
filings could occupy every --resume run's --limit budget forever and
starve out genuinely new filings.

SEC's fair access policy is unusually strict and officially documented:
max 10 req/s, and every request MUST carry an identifying User-Agent
(name/tool + contact) or SEC returns HTTP 403 and may briefly block the
source IP. SEC_CONTACT_EMAIL must be set (via .env or the environment) —
this job refuses to run without it rather than sending a placeholder that
would violate SEC's policy.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.company_registry import Company, load_companies
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from jobs.sec.client import RATE_LIMIT, SEC_ARCHIVES_BASE, SECClient
from jobs.sec.parser import filings_from_recent_block, filter_relevant_forms, list_exhibit_entries, parse_document_format_table, within_date_range
from jobs.sec.report import build_report

REGISTRY_PATH = Path("configs/company_registry.yaml")
EXTRA_FIELDS = [
    "cik", "company", "accession_number", "filing_type", "filing_date", "report_date",
    "primary_document", "item_codes", "file_number", "film_number",
]
EXHIBIT_EXTRA_FIELDS = ["exhibit_type", "exhibit_description"]
LICENSE_NOTE = "SEC EDGAR filing, public disclosure."
EXHIBIT_NAMESPACE = "exhibit_records"

DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]
EXHIBIT_ATTEMPT_COLUMNS = [
    "source", "source_record_id", "parent_record_id", "run_id", "attempted_at",
    "status", "http_status", "error", "content_hash", "version",
]

# A distinct "artifact identity" for the filing-index page fetch itself
# (as opposed to any individual exhibit filename) -- gets its OWN success/
# failure attempt row every run, keyed by f"{accession_number}{FILING_INDEX_SUFFIX}",
# so a filing-index failure can self-heal out of the unresolved retry set
# once a later run's filing-index fetch actually succeeds. Without this,
# nothing ever records a "success" for the filing-index step itself (only
# individual exhibits get success rows), so its one and only recorded
# attempt would stay "failed" forever, in a book that only ever records
# the *most recent* row -- permanently unresolved even after the real
# problem is long gone.
FILING_INDEX_SUFFIX = ":__filing_index__"

# SEC's own submissions-API metadata provided no primaryDocument for this
# filing at all (pre-2002 filings sometimes lack one) -- a permanent,
# source-side condition, not a fetch failure that might resolve on retry.
# Excluded from --resume's unresolved retry set for the PRIMARY document
# specifically; the filing's exhibits (if any) are still tracked
# independently via _unresolved_exhibit_parent_ids.
TERMINAL_PRIMARY_ERRORS = {"no_primary_document"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unresolved_exhibit_parent_ids(checkpoint: dict, exhibits_attempts_path: Path) -> set[str]:
    """Accession numbers with an exhibit, OR the filing-index page fetch
    itself (identity f"{accession_number}{FILING_INDEX_SUFFIX}"), whose
    MOST RECENT recorded attempt was a failure with no later success —
    i.e. still genuinely unresolved, not just "failed once, ages ago,
    then fixed." Used so --resume's date-bounded discovery doesn't let an
    unresolved exhibit/filing-index failure permanently drop out of scope
    once its filing predates the resume cursor."""
    if not exhibits_attempts_path.exists():
        return set()
    df = pd.read_parquet(exhibits_attempts_path)
    if df.empty:
        return set()
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    failed_ids = set(latest.loc[latest["status"] == "failed", "source_record_id"])
    return {exhibit_id.split(":", 1)[0] for exhibit_id in failed_ids}


def _terminal_primary_accession_ids(attempts_path: Path) -> set[str]:
    """Accession numbers whose most recent primary-document attempt is a
    known-permanent, source-side condition (see TERMINAL_PRIMARY_ERRORS) —
    excluded from --resume's unresolved retry set for their primary
    document specifically, so a handful of permanently-broken historical
    filings can never starve out fresh/in-range filings from a --limit
    budget by occupying the retry set forever."""
    if not attempts_path.exists():
        return set()
    df = pd.read_parquet(attempts_path)
    if df.empty:
        return set()
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    terminal = latest[(latest["status"] == "failed") & (latest["error"].isin(TERMINAL_PRIMARY_ERRORS))]
    return set(terminal["source_record_id"])


def _attempt_row(
    accession_number: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="sec", source_record_id=accession_number, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _exhibit_attempt_row(
    exhibit_id: str, parent_record_id: str, run_id: str, attempted_at: str, status: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="sec", source_record_id=exhibit_id, parent_record_id=parent_record_id,
        run_id=run_id, attempted_at=attempted_at, status=status,
        http_status=http_status, error=error, content_hash=content_hash, version=version,
    )


class SECJob(AcquisitionJob):
    name = "sec"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--registry-file", type=str, default=str(REGISTRY_PATH),
            help="Path to the company registry YAML.",
        )
        parser.add_argument(
            "--company", type=str, default=None,
            help="Only process this company_id from the registry (default: all active companies).",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        load_dotenv()
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        contact_email = os.environ.get("SEC_CONTACT_EMAIL")
        if not contact_email:
            raise RuntimeError(
                "SEC_CONTACT_EMAIL must be set (.env or environment) — SEC's fair access policy "
                "requires every request to carry a real identifying contact, and this job refuses "
                "to send a placeholder that would violate that policy"
            )
        user_agent = f"adc-acquisition ({contact_email})"
        client = SECClient(RetryingClient(RateLimiter(RATE_LIMIT)), user_agent=user_agent)

        companies = [c for c in load_companies(Path(args.registry_file)) if c.active]
        if args.company:
            companies = [c for c in companies if c.company_id == args.company]
        if not companies:
            raise RuntimeError(f"no matching active companies in {args.registry_file}")

        since = args.since
        used_resume_cursor = False
        if args.resume and not since:
            since = checkpoint.get("last_success_max_date")
            used_resume_cursor = True
        until = args.until

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))

        # --resume's implicit --since is a discovery-efficiency cursor, not
        # a scope the caller actually asked for (unlike an explicit
        # --since) — so any filing/exhibit that's still unresolved from a
        # prior run must be unioned back in even if it now falls before
        # the cursor, or it would silently and permanently drop out of
        # every future --resume run the moment the cursor passes its date.
        # A handful of PERMANENT source-side gaps are excluded from this
        # (TERMINAL_PRIMARY_ERRORS) so they can't occupy the retry set
        # forever; everything else in the retry set is still tracked
        # separately from fresh/in-range candidates (fresh_accession_ids
        # below) so a --limit budget always favors fresh filings first —
        # a backlog of old, still-unresolved-but-not-terminal failures
        # (e.g. a run of 404s that might genuinely resolve later) must
        # never be able to starve new filings out of every run forever.
        unresolved_exhibit_parent_ids: set[str] = set()
        terminal_primary_ids: set[str] = set()
        if used_resume_cursor:
            unresolved_exhibit_parent_ids = _unresolved_exhibit_parent_ids(
                checkpoint, output_dir / "manifests" / "sec_exhibits_attempts.parquet"
            )
            terminal_primary_ids = _terminal_primary_accession_ids(attempts_path=output_dir / "manifests" / "sec_attempts.parquet")

        record_first_query: dict[str, tuple[str, str]] = {}
        record_query_hits: dict[str, set[str]] = defaultdict(set)
        record_filings: dict[str, tuple] = {}  # accession_number -> (ParsedFiling, Company, cik)
        query_id_counts: Counter = Counter()
        query_text_by_id: dict[str, str] = {}
        companies_used: list[str] = []
        fresh_accession_ids: set[str] = set()

        for company in companies:
            for cik in company.ciks:
                query_id = f"SEC_FILINGS_{company.company_id.upper()}_{cik}"
                query_text = (
                    f"all relevant-form filings (10-K/10-Q/8-K/S-1/20-F/6-K + amendments) "
                    f"for CIK {cik} ({company.canonical_name})"
                )
                try:
                    submissions = client.get_submissions(cik)
                    all_filings = filings_from_recent_block(submissions["filings"]["recent"])
                    for page_ref in submissions["filings"].get("files", []):
                        page = client.get_submissions_page(page_ref["name"])
                        all_filings.extend(filings_from_recent_block(page))
                except requests.RequestException as exc:
                    logger.error("company=%s cik=%s submissions fetch failed: %s", company.company_id, cik, exc)
                    failure_logger.info("company=%s cik=%s error=%s", company.company_id, cik, exc)
                    continue

                relevant_all = filter_relevant_forms(all_filings)
                if since or until:
                    relevant_in_scope = [f for f in relevant_all if within_date_range(f.filing_date, since, until)]
                else:
                    relevant_in_scope = relevant_all
                fresh_accession_ids.update(f.accession_number for f in relevant_in_scope)
                relevant = relevant_in_scope

                if used_resume_cursor:
                    in_scope_ids = {f.accession_number for f in relevant_in_scope}
                    resolved_primary_ids = checkpoint.get("records", {})
                    unresolved = [
                        f for f in relevant_all
                        if f.accession_number not in in_scope_ids
                        and (
                            (f.accession_number not in resolved_primary_ids and f.accession_number not in terminal_primary_ids)
                            or f.accession_number in unresolved_exhibit_parent_ids
                        )
                    ]
                    relevant = relevant_in_scope + unresolved

                query_id_counts[query_id] = len(relevant)
                query_text_by_id[query_id] = query_text
                companies_used.append(f"{company.canonical_name} (CIK {cik})")
                for pf in relevant:
                    record_query_hits[pf.accession_number].add(query_id)
                    if pf.accession_number not in record_first_query:
                        record_first_query[pf.accession_number] = (query_id, query_text)
                    record_filings[pf.accession_number] = (pf, company, cik)

        all_ids = list(record_first_query.keys())
        duplicate_ids = {aid for aid, qids in record_query_hits.items() if len(qids) > 1}

        result.queries_run = len(companies_used)
        result.records_discovered = len(all_ids)
        if args.limit:
            result.notes.append(
                "per-company filing counts reflect each company's full relevant-form filing history "
                "regardless of --limit; --limit only caps how many are materialized"
            )

        # Fresh/in-range candidates always get priority for a --limit
        # budget over backlog retries carried in by --resume's unresolved
        # union — otherwise a backlog of old, still-unresolved failures
        # could occupy every slot every run and starve out new filings
        # indefinitely (see TERMINAL_PRIMARY_ERRORS above for the other
        # half of this fix: excluding known-permanent gaps from the
        # backlog entirely). With no --resume backlog in play, this is
        # simply every discovered id, sorted, same as before.
        retry_backlog_ids = sorted(aid for aid in all_ids if aid not in fresh_accession_ids)
        ordered_ids = sorted(fresh_accession_ids & set(all_ids)) + retry_backlog_ids
        target_ids = ordered_ids[: args.limit] if args.limit else ordered_ids

        if args.dry_run:
            result.notes.append(f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered filings")
            if retry_backlog_ids:
                result.notes.append(
                    f"{len(retry_backlog_ids)} of those are --resume backlog retries (unresolved, predate the cursor) — "
                    "fresh/in-range filings are prioritized first within --limit"
                )
            return result

        now = _now_iso()
        run_id = now

        manifest_path = output_dir / "manifests" / "sec.parquet"
        discovery_path = output_dir / "manifests" / "sec_discovery.parquet"
        attempts_path = output_dir / "manifests" / "sec_attempts.parquet"
        exhibits_manifest_path = output_dir / "manifests" / "sec_exhibits.parquet"
        exhibits_attempts_path = output_dir / "manifests" / "sec_exhibits_attempts.parquet"

        discovery_rows = [
            dict(
                source="sec",
                source_record_id=aid,
                query_id=qid,
                query_version=1,
                query_text=query_text_by_id[qid],
                discovered_at=now,
                run_id=run_id,
            )
            for aid, query_ids in record_query_hits.items()
            for qid in sorted(query_ids)
        ]
        append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        content_rows = []
        attempt_rows = []
        exhibit_content_rows = []
        exhibit_attempt_rows = []

        for accession_number in target_ids:
            pf, company, cik = record_filings[accession_number]
            query_id, query_text = record_first_query[accession_number]
            raw_dir = output_dir / "raw" / "sec" / accession_number

            # --- Primary filing document: its own independent attempt. ---
            if not pf.primary_document:
                logger.warning("accession=%s has no primaryDocument", accession_number)
                failure_logger.info("accession=%s error=no_primary_document", accession_number)
                result.records_failed += 1
                attempt_rows.append(_attempt_row(accession_number, run_id, now, "failed", query_id, query_text, error="no_primary_document"))
            else:
                try:
                    raw_bytes = client.fetch_document(cik, accession_number, pf.primary_document)
                except requests.RequestException as exc:
                    logger.error("accession=%s primary document fetch failed: %s", accession_number, exc)
                    failure_logger.info("accession=%s error=%s", accession_number, exc)
                    result.records_failed += 1
                    attempt_rows.append(_attempt_row(accession_number, run_id, now, "failed", query_id, query_text, error=str(exc)))
                else:
                    content_hash = sha256_bytes(raw_bytes)
                    prior_state = checkpoint_store.get_record_state(checkpoint, accession_number)

                    if prior_state and prior_state.get("content_hash") == content_hash:
                        result.records_skipped_unchanged += 1
                        version = prior_state["version"]
                        status = "skipped_unchanged"
                    else:
                        version = (prior_state["version"] + 1) if prior_state else 1
                        raw_dir.mkdir(parents=True, exist_ok=True)
                        raw_path = raw_dir / f"v{version}_{pf.primary_document}"
                        raw_path.write_bytes(raw_bytes)
                        checkpoint_store.set_record_state(checkpoint, accession_number, content_hash, version, now)
                        result.records_downloaded += 1
                        status = "success"
                        content_rows.append(
                            new_manifest_row(
                                extra_fields=EXTRA_FIELDS,
                                source="sec",
                                source_record_id=accession_number,
                                source_record_type="sec_filing",
                                title=f"{pf.form} — {company.canonical_name}",
                                url=f"{SEC_ARCHIVES_BASE}/{int(cik)}/{accession_number.replace('-', '')}/{pf.primary_document}",
                                publication_or_release_date=pf.filing_date,
                                retrieved_at=now,
                                query_id=query_id,
                                query_text=query_text,
                                raw_file_path=str(raw_path),
                                raw_format=Path(pf.primary_document).suffix.lstrip(".") or "html",
                                content_hash=content_hash,
                                download_status="success",
                                http_status=200,
                                license_or_access_note=LICENSE_NOTE,
                                parent_record_id=None,
                                version=version,
                                notes=None,
                                cik=cik,
                                company=company.canonical_name,
                                accession_number=pf.accession_number,
                                filing_type=pf.form,
                                filing_date=pf.filing_date,
                                report_date=pf.report_date,
                                primary_document=pf.primary_document,
                                item_codes=pf.item_codes,
                                file_number=pf.file_number,
                                film_number=pf.film_number,
                            )
                        )

                    attempt_rows.append(
                        _attempt_row(accession_number, run_id, now, status, query_id, query_text, http_status=200, content_hash=content_hash, version=version)
                    )

            # --- Exhibits: independent lifecycle, attempted regardless of
            # whether the primary filing document above succeeded, failed,
            # or was unchanged — a primary-document failure must never
            # suppress exhibit acquisition for the same filing. ---
            filing_index_id = f"{accession_number}{FILING_INDEX_SUFFIX}"
            try:
                index_html = client.get_filing_index_page(cik, accession_number)
                document_entries = parse_document_format_table(index_html)
                exhibit_entries = list_exhibit_entries(document_entries, pf.primary_document)
            except requests.RequestException as exc:
                logger.warning("accession=%s filing index page fetch failed: %s", accession_number, exc)
                exhibit_attempt_rows.append(
                    _exhibit_attempt_row(filing_index_id, accession_number, run_id, now, "failed", error=f"filing_index_fetch_failed: {exc}")
                )
                continue
            else:
                # A success row for the filing-index step itself (distinct
                # from any individual exhibit's row) so a prior failure can
                # self-heal out of the unresolved retry set — otherwise
                # this identity's one and only recorded attempt would stay
                # "failed" forever, since nothing else ever writes to it.
                exhibit_attempt_rows.append(
                    _exhibit_attempt_row(filing_index_id, accession_number, run_id, now, "success")
                )

            for entry in exhibit_entries:
                filename = entry.filename
                exhibit_id = f"{accession_number}:{filename}"
                try:
                    exhibit_bytes = client.fetch_document(cik, accession_number, filename)
                except requests.RequestException as exc:
                    logger.warning("exhibit=%s fetch failed: %s", exhibit_id, exc)
                    failure_logger.info("exhibit=%s error=%s", exhibit_id, exc)
                    exhibit_attempt_rows.append(_exhibit_attempt_row(exhibit_id, accession_number, run_id, now, "failed", error=str(exc)))
                    continue

                exhibit_hash = sha256_bytes(exhibit_bytes)
                prior_exhibit_state = checkpoint_store.get_record_state(checkpoint, exhibit_id, namespace=EXHIBIT_NAMESPACE)

                if prior_exhibit_state and prior_exhibit_state.get("content_hash") == exhibit_hash:
                    exhibit_attempt_rows.append(
                        _exhibit_attempt_row(exhibit_id, accession_number, run_id, now, "skipped_unchanged", content_hash=exhibit_hash, version=prior_exhibit_state["version"])
                    )
                    continue

                exhibit_version = (prior_exhibit_state["version"] + 1) if prior_exhibit_state else 1
                exhibit_dir = raw_dir / "exhibits"
                exhibit_dir.mkdir(parents=True, exist_ok=True)
                exhibit_path = exhibit_dir / f"v{exhibit_version}_{filename}"
                exhibit_path.write_bytes(exhibit_bytes)
                checkpoint_store.set_record_state(checkpoint, exhibit_id, exhibit_hash, exhibit_version, now, namespace=EXHIBIT_NAMESPACE)

                exhibit_content_rows.append(
                    new_manifest_row(
                        extra_fields=EXHIBIT_EXTRA_FIELDS,
                        source="sec",
                        source_record_id=exhibit_id,
                        source_record_type="sec_exhibit",
                        title=filename,
                        url=f"{SEC_ARCHIVES_BASE}/{int(cik)}/{accession_number.replace('-', '')}/{filename}",
                        publication_or_release_date=pf.filing_date,
                        retrieved_at=now,
                        query_id=query_id,
                        query_text=query_text,
                        raw_file_path=str(exhibit_path),
                        raw_format=Path(filename).suffix.lstrip(".") or "html",
                        content_hash=exhibit_hash,
                        download_status="success",
                        http_status=200,
                        license_or_access_note=LICENSE_NOTE,
                        parent_record_id=accession_number,
                        version=exhibit_version,
                        notes=None,
                        exhibit_type=entry.doc_type,
                        exhibit_description=entry.description,
                    )
                )
                exhibit_attempt_rows.append(
                    _exhibit_attempt_row(exhibit_id, accession_number, run_id, now, "success", content_hash=exhibit_hash, version=exhibit_version)
                )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        write_manifest(exhibit_content_rows, exhibits_manifest_path, extra_fields=EXHIBIT_EXTRA_FIELDS)
        append_only(exhibit_attempt_rows, exhibits_attempts_path, EXHIBIT_ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)
        checkpoint["last_run_at"] = now
        checkpoint["last_success_max_date"] = until or now[:10]
        checkpoint_store.save(checkpoint)

        # The filing-index step's own success/failure rows (identity
        # f"{accession}{FILING_INDEX_SUFFIX}") live in the same ledger for
        # retry-set bookkeeping, but aren't themselves exhibit-content
        # outcomes — exclude them from the exhibit acquisition stats below.
        real_exhibit_attempt_rows = [r for r in exhibit_attempt_rows if not r["source_record_id"].endswith(FILING_INDEX_SUFFIX)]

        report_text = build_report(
            result=result,
            manifest_df=manifest_df,
            companies_used=companies_used,
            query_id_counts=query_id_counts,
            unique_ids=set(all_ids),
            duplicate_ids=duplicate_ids,
            exhibit_attempted=len(real_exhibit_attempt_rows),
            exhibit_new_or_changed=sum(1 for r in real_exhibit_attempt_rows if r["status"] == "success"),
            exhibit_unchanged=sum(1 for r in real_exhibit_attempt_rows if r["status"] == "skipped_unchanged"),
            exhibit_failed=sum(1 for r in real_exhibit_attempt_rows if r["status"] == "failed"),
        )
        report_path = output_dir.parent / "reports" / "acquisition" / "sec.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
