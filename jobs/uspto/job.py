"""Job 09: USPTO patent acquisition (Prompt.md section 8, execution order
section 29).

USPTO's own Open Data Portal (data.uspto.gov, "Patent File Wrapper" API) is
the current official mechanism — PatentsView (api.patentsview.org) was shut
down 2026-03-20 and now redirects to ODP's own migration guide; the old
developer.uspto.gov portal is also decommissioned. Unlike WIPO PATENTSCOPE,
there is no automation ban here: a free USPTO.gov account + API key is
required (since 2026-06-18, framed as curbing unregistered bot traffic, not
prohibiting automated access outright). See jobs/uspto/client.py for the
live-verified endpoint shapes, auth, pagination, and rate-limit details.

Discovery: configs/uspto_queries.yaml's 5 free-text queries (the same
Prompt.md search concepts used for Job 08/WIPO, translated to USPTO's
query syntax — verified live to search across full specification content,
not just titles). Search only returns applicationNumberText per hit (a
minimal `fields=` projection keeps each page well under USPTO's 6MB
response cap) — not bibliographic data — so discovery and materialization
are two different API calls, same shape as FDA's label-search-then-
drugsfda-lookup and WIPO's search-then-biblio-fetch.

Three tables: uspto.parquet (application content-version manifest, a
deterministic sort_keys=True serialization of the source's full
patentFileWrapperDataBag record — not the raw HTTP response bytes
verbatim, since the record is extracted from a wrapping envelope and
re-serialized — keyed by application_number), uspto_discovery.parquet
(every (application, query, run) triple, written unconditionally right
after all queries' searches complete, BEFORE any per-application fetch is
attempted — same "discovery must survive a later step's crash" principle
as FDA/EMA/WIPO), uspto_attempts.parquet (success/skipped_unchanged/failed/
parse_failed).

UNLIKE Job 08 (WIPO): a USPTO application's record is NOT treated as
settled once successfully fetched — prosecution status, continuity data,
and assignments genuinely change over time while an application is
pending, same as SEC filings/FDA applications/EMA medicines. So every
discovered application is refetched and hash-compared on every run (the
ordinary SEC/FDA/EMA pattern), not skipped by default the way WIPO's
already-published, essentially-frozen PCT records are. USPTO's generous
weekly quota (5,000,000 metadata / 1,200,000 document retrievals,
verified live) removes the efficiency pressure that motivated WIPO's
skip-by-default design in the first place, so there's no "--refresh" flag
here — always-refetch is simply the right default for this source.

--since/--until: applied SERVER-SIDE via USPTO's own bracket-range date
syntax (`applicationMetaData.filingDate:[YYYY-MM-DD TO YYYY-MM-DD]`,
verified live) whenever the caller supplies them EXPLICITLY — trusted
literally, narrows the search itself (same "explicit scope is trusted,
only the implicit cursor needs a safety net" principle as every other job
here). --resume (the implicit cursor) does NOT narrow the search this
way — doing so would make a not-yet-successfully-materialized application
whose filing predates the cursor undiscoverable by this run's search at
all, the exact SEC-round-2 failure mode. So --resume and the plain
default both run a full undated sweep of all 5 registered queries every
run. Materialization order for a --limit budget is THREE categories, not
two: never-attempted (fresh) first, then unresolved retries (backlog —
most recent attempt was failed OR parse_failed), then already-resolved
applications (reverify — most recent attempt was success OR
skipped_unchanged) due for periodic re-verification. Round-1 review caught
a real bug here: an earlier version only excluded `failed` from `fresh_ids`,
so already-successful applications were wrongly treated as "fresh" too —
under a small --limit, the same handful of already-successful ids would be
re-verified every single run while a genuinely fresh id discovered later
could be starved out forever. The three-category split (with reverify
strictly last) is what makes --limit fairness actually hold.

RAW ACQUISITION STATE IS NOT THE SAME FACT AS "ALREADY FULLY
MATERIALIZED" — round-1 review also caught this, the same class of bug
Job 08/WIPO needed 3 rounds to fully close. An application's raw-fetch
content_hash/version lives in its own RAW_NAMESPACE checkpoint,
updated unconditionally right after every raw write AND saved to disk
IMMEDIATELY (before parsing is attempted) — same invariant as WIPO. But
"this run's freshly-fetched bytes match RAW_NAMESPACE's stored hash" only
proves the RAW bytes are unchanged; it does NOT prove normalization
(parse -> manifest row -> attempts row) ever actually completed for that
content, because manifest/attempts are only flushed to disk once, at the
very end of a run — an uncaught exception anywhere downstream of the raw
write (a parser crash recorded as parse_failed, or any other uncaught bug)
leaves that flush undone. So the skip-without-reparse decision requires
BOTH facts: unchanged raw bytes (RAW_NAMESPACE) AND the attempts ledger's
own most-recent status for this id already being resolved (success or
skipped_unchanged) — not just the first one. If bytes are unchanged but
the ledger's last word on this id was parse_failed, or has no attempt
recorded at all (a crash before the ledger was ever flushed), the raw file
is reused as-is (no rewrite, no new version) but normalization is retried.

Documents (secondary artifact, Prompt.md's "claims/full text where
legally and technically available"): each materialized application's file
wrapper is listed via /documents and filtered to documentCode=="SPEC" (the
actual filed Specification, containing claims — a source-typed filter on
USPTO's own document classification field, same principle as SEC's
EX-*-typed exhibits, not a negative "everything that isn't X" filter).
Document acquisition runs for every application processed this run
regardless of whether that application's own fetch was fresh/backlog/
re-verification, in its own independent try/except (a primary-record
outcome must never gate a secondary artifact's own attempt, same
principle as SEC's exhibits / FDA's documents). Documents have their own
manifest+attempts+checkpoint-namespace triple; there is no separate
documents-discovery ledger because (like SEC/FDA, unlike EMA) there is no
bulk documents feed to discover from independently — a document's
existence is only knowable by listing a specific application's own file
wrapper, so document processing is necessarily scoped to applications
processed this run (this is the SEC/FDA precedent, not the EMA anti-
pattern, because there genuinely is no better alternative here).

DOCUMENT VERSIONING IS IDENTITY-BASED, NOT HASH-BASED, unlike every other
document artifact in this repo — a live-verified USPTO-specific quirk:
its /download endpoints DYNAMICALLY RE-RENDER the PDF/XML on every single
request (confirmed live: two immediately-successive fetches of the exact
same documentIdentifier return DIFFERENT bytes each time — the PDF embeds
a fresh `/CreationDate`, the XML archive differs too). Hash-compare-then-
version — the pattern every other job's documents use — would treat every
re-fetch as "changed" and create an unbounded stream of spurious versions
forever, even though the underlying filed document never changes. Since
`documentIdentifier` IS a stable, permanent identity (a later amendment
gets its own new identifier, not a mutation of an old one), documents are
instead skipped once their most recent attempt succeeded (see
_resolved_document_keys) -- no request, no hash comparison, version is
always 1.

Raw evidence durability (both levels): raw bytes are written to disk and
that record's checkpoint state (content_hash/version) is BOTH updated in
memory AND saved to disk IMMEDIATELY, before parsing/normalization is
attempted — the two-part invariant Job 08/WIPO needed 3 review rounds to
fully establish (RAW FETCH -> RAW SNAPSHOT -> CHECKPOINT SAVED TO DISK ->
PARSE).

DOCUMENT SKIP DECISIONS USE THE CHECKPOINT DIRECTLY, NOT THE ATTEMPTS
LEDGER — round-1 review caught a real overwrite hazard here too. A
document's DOCUMENT_NAMESPACE checkpoint entry is saved to disk
immediately after its raw write, but (like the application manifest/
attempts above) the documents manifest/attempts ledger is only flushed
once, at the very end of a run. If an uncaught exception happens anywhere
after that checkpoint save but before the end-of-run flush, the NEXT run
would see no successful/skipped_unchanged ledger row for this document at
all — and since USPTO's /download bytes are NOT reproducible across
requests (see below), re-fetching it would silently overwrite the
already-durable raw file with different bytes. So the skip test is simply
"does DOCUMENT_NAMESPACE already have a checkpoint entry for this
documentIdentifier" — if yes, skip with NO request and reconstruct this
run's manifest/attempts rows from the checkpoint's own stored hash/version
(self-healing a lost ledger flush without ever re-downloading).
"""

from __future__ import annotations

import argparse
import json
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
from adc_acquisition.query_registry import active_queries, load_queries
from jobs.uspto.client import MAX_PAGE_SIZE, RATE_LIMIT, USPTOClient
from jobs.uspto.parser import parse_application, parse_documents
from jobs.uspto.report import build_report

QUERIES_PATH = Path("configs/uspto_queries.yaml")
APPLICATION_EXTRA_FIELDS = [
    "application_number", "publication_number", "status", "applicants", "inventors",
    "assignees", "cpc_classes", "foreign_priority",
]
DOCUMENT_EXTRA_FIELDS = ["document_code", "document_description"]
LICENSE_NOTE = "USPTO Open Data Portal (Patent File Wrapper), public disclosure."

DOCUMENT_NAMESPACE = "document_records"

# Raw-fetch content/version tracking for APPLICATIONS lives in its own
# checkpoint namespace, updated unconditionally right after every raw write
# AND saved to disk immediately (before parsing) -- see module docstring.
# Deliberately kept separate from the attempts ledger's resolved/unresolved
# status, which is a DIFFERENT fact (whether normalization ever completed).
RAW_NAMESPACE = "raw_records"

RESOLVED_STATUSES = {"success", "skipped_unchanged"}
UNRESOLVED_STATUSES = {"failed", "parse_failed"}

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


def _to_bracket_date(date_str: str | None, default: str) -> str:
    return date_str if date_str else default


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="uspto", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _document_attempt_row(
    doc_key: str, parent_record_id: str, run_id: str, attempted_at: str, status: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="uspto", source_record_id=doc_key, parent_record_id=parent_record_id,
        run_id=run_id, attempted_at=attempted_at, status=status,
        http_status=http_status, error=error, content_hash=content_hash, version=version,
    )


def _latest_status_by_id(attempts_path: Path) -> dict[str, str]:
    """Every application id's MOST RECENTLY recorded attempt status.

    Used for two distinct decisions that both need "what happened last
    time": (1) --limit fairness (fresh / backlog / reverify triage, see
    module docstring) and (2) whether unchanged raw bytes are ALREADY
    fully materialized (a hash match alone doesn't prove that — see
    RAW_NAMESPACE docstring). Recognizes resolved as {"success",
    "skipped_unchanged"} and unresolved as {"failed", "parse_failed"} —
    not just the first status reached in each direction, since a record's
    second consecutive skip produces skipped_unchanged (not success again)
    and a parser crash produces parse_failed (not failed)."""
    if not attempts_path.exists():
        return {}
    df = pd.read_parquet(attempts_path)
    if df.empty:
        return {}
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    return dict(zip(latest["source_record_id"], latest["status"]))


class USPTOJob(AcquisitionJob):
    name = "uspto"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--queries-file", type=str, default=str(QUERIES_PATH),
            help="Path to the USPTO discovery query registry YAML.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        load_dotenv()
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        api_key = os.environ.get("USPTO_API_KEY")
        if not api_key:
            raise RuntimeError(
                "USPTO_API_KEY must be set (free registration at https://data.uspto.gov/) — "
                "PatentsView is shut down and developer.uspto.gov is decommissioned."
            )
        client = USPTOClient(RetryingClient(RateLimiter(RATE_LIMIT)), api_key)

        queries = active_queries(load_queries(Path(args.queries_file)))
        if not queries:
            raise RuntimeError(f"no active queries found in {args.queries_file}")

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        now = _now_iso()
        run_id = now

        date_filter = None
        if args.since or args.until:
            since_bracket = _to_bracket_date(args.since, "1900-01-01")
            until_bracket = _to_bracket_date(args.until, "2099-12-31")
            date_filter = f"applicationMetaData.filingDate:[{since_bracket} TO {until_bracket}]"

        # --- Discovery: full sweep of every registered query. Each hit is
        # attributed to the FIRST query that discovered it for the
        # manifest's single "primary" query_id, but every (application,
        # query) pair still gets its own discovery ledger row below. ---
        first_query_by_id: dict[str, tuple[str, str]] = {}
        discovery_pairs: list[tuple[str, str, str]] = []  # (application_number, query_id, query_text)

        for q in queries:
            query_text = q.query_text if not date_filter else f"{q.query_text} AND {date_filter}"
            offset = 0
            total = None
            while total is None or offset < total:
                ids, total = client.search(query_text, MAX_PAGE_SIZE, offset)
                for app_id in ids:
                    first_query_by_id.setdefault(app_id, (q.query_id, q.query_text))
                    discovery_pairs.append((app_id, q.query_id, q.query_text))
                if not ids:
                    break
                offset += len(ids)

        all_ids = list(first_query_by_id.keys())
        result.queries_run = len(queries)
        result.records_discovered = len(all_ids)

        discovery_path = output_dir / "manifests" / "uspto_discovery.parquet"
        if not args.dry_run:
            discovery_rows = [
                dict(
                    source="uspto", source_record_id=app_id, query_id=qid, query_version=next(
                        qq.query_version for qq in queries if qq.query_id == qid
                    ),
                    query_text=qtext, discovered_at=now, run_id=run_id,
                )
                for app_id, qid, qtext in discovery_pairs
            ]
            append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        attempts_path = output_dir / "manifests" / "uspto_attempts.parquet"
        latest_status = _latest_status_by_id(attempts_path)
        unresolved_ids = {aid for aid, st in latest_status.items() if st in UNRESOLVED_STATUSES}
        resolved_ids = {aid for aid, st in latest_status.items() if st in RESOLVED_STATUSES}

        # THREE categories, not two (round-1 fix): fresh (never attempted)
        # first, then backlog (unresolved retries), then reverify
        # (already-resolved, due for periodic re-verification only because
        # USPTO content is mutable and cheap to re-check). Putting reverify
        # STRICTLY LAST is what prevents a small --limit from re-verifying
        # the same already-successful ids forever while a genuinely fresh
        # id discovered later gets starved out.
        fresh_ids = sorted(app_id for app_id in all_ids if app_id not in unresolved_ids and app_id not in resolved_ids)
        backlog_ids = sorted(app_id for app_id in all_ids if app_id in unresolved_ids)
        reverify_ids = sorted(app_id for app_id in all_ids if app_id in resolved_ids)
        ordered_work = fresh_ids + backlog_ids + reverify_ids
        target_ids = ordered_work[: args.limit] if args.limit else ordered_work

        if args.dry_run:
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered applications "
                f"({len(fresh_ids)} never attempted, {len(backlog_ids)} unresolved retries, "
                f"{len(reverify_ids)} already-resolved reverify candidates)"
            )
            return result

        manifest_path = output_dir / "manifests" / "uspto.parquet"
        documents_manifest_path = output_dir / "manifests" / "uspto_documents.parquet"
        documents_attempts_path = output_dir / "manifests" / "uspto_documents_attempts.parquet"

        content_rows = []
        attempt_rows = []
        document_content_rows = []
        document_attempt_rows = []
        parse_error: str | None = None

        # --- Primary application reconciliation. Documents are handled in
        # a SEPARATE loop below, over the SAME target_ids, so a primary
        # record being skipped_unchanged/failed/parse_failed can never
        # suppress that application's own document acquisition (same
        # principle as SEC's exhibits: "structure the primary-record fetch
        # and the secondary-artifact fetch as two separate, independently-
        # erroring blocks per record, not one fetch nested inside the
        # other's success path"). ---
        for app_id in target_ids:
            query_id, query_text = first_query_by_id[app_id]
            try:
                raw_record = client.get_application(app_id)
            except requests.RequestException as exc:
                logger.warning("application=%s fetch failed: %s", app_id, exc)
                failure_logger.info("application=%s error=%s", app_id, exc)
                result.records_failed += 1
                attempt_rows.append(_record_row(app_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if raw_record is None:
                logger.warning("application=%s: USPTO has no such application (404)", app_id)
                failure_logger.info("application=%s error=not_found", app_id)
                result.records_failed += 1
                attempt_rows.append(_record_row(app_id, run_id, now, "failed", query_id, query_text, error="not_found"))
                continue

            content_bytes = json.dumps(raw_record, sort_keys=True, default=str).encode("utf-8")
            content_hash = sha256_bytes(content_bytes)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, app_id, namespace=RAW_NAMESPACE)

            if (
                raw_prior_state
                and raw_prior_state.get("content_hash") == content_hash
                and latest_status.get(app_id) in RESOLVED_STATUSES
            ):
                # Unchanged bytes AND the ledger's own last word on this id
                # is already resolved (success or skipped_unchanged) -- a
                # genuine no-op, skip re-parsing.
                result.records_skipped_unchanged += 1
                attempt_rows.append(
                    _record_row(app_id, run_id, now, "skipped_unchanged", query_id, query_text, content_hash=content_hash, version=raw_prior_state["version"])
                )
                continue

            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                # Unchanged bytes, but normalization never actually
                # completed last time (parse_failed, or no attempt
                # recorded at all -- e.g. an uncaught exception crashed
                # the run before its end-of-run ledger flush). Reuse the
                # EXISTING raw file rather than rewriting it -- no new
                # version, since the bytes genuinely didn't change -- but
                # retry parsing/normalization.
                version = raw_prior_state["version"]
                raw_path = output_dir / "raw" / "uspto" / app_id / f"v{version}.json"
            else:
                # New or CHANGED application record: persist raw bytes and
                # save the checkpoint's RAW_NAMESPACE version state to disk
                # IMMEDIATELY, before parsing -- a parser crash (or any
                # later exception) must never leave a later run confused
                # about which version number this content already
                # occupies (the invariant Job 08/WIPO needed 3 review
                # rounds to establish; applied here from the start).
                version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
                raw_dir = output_dir / "raw" / "uspto" / app_id
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.json"
                raw_path.write_bytes(content_bytes)
                checkpoint_store.set_record_state(checkpoint, app_id, content_hash, version, now, namespace=RAW_NAMESPACE)
                checkpoint_store.save(checkpoint)

            try:
                parsed = parse_application(raw_record)
            except Exception as exc:  # noqa: BLE001 - any parser bug must not silently lose this record
                logger.error("application=%s parse failed: %s", app_id, exc)
                failure_logger.info("application=%s error=parse_failed: %s", app_id, exc)
                attempt_rows.append(
                    _record_row(app_id, run_id, now, "parse_failed", query_id, query_text, error=str(exc), content_hash=content_hash, version=version)
                )
                parse_error = f"application={app_id}: {exc}"
                break  # a parser bug is likely systematic -- stop rather than push through the whole batch

            result.records_downloaded += 1
            attempt_rows.append(
                _record_row(app_id, run_id, now, "success", query_id, query_text, content_hash=content_hash, version=version)
            )
            content_rows.append(
                new_manifest_row(
                    extra_fields=APPLICATION_EXTRA_FIELDS,
                    source="uspto",
                    source_record_id=app_id,
                    source_record_type="uspto_application",
                    title=parsed.title,
                    url=f"https://patentcenter.uspto.gov/applications/{app_id}",
                    publication_or_release_date=parsed.publication_date,
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
                    notes=parsed.status,
                    application_number=app_id,
                    publication_number=parsed.publication_number,
                    status=parsed.status,
                    applicants=parsed.applicants,
                    inventors=parsed.inventors,
                    assignees=parsed.assignees,
                    cpc_classes=parsed.cpc_classes,
                    foreign_priority=[json.dumps(p, sort_keys=True) for p in parsed.foreign_priority],
                )
            )

        # --- Documents: independent lifecycle. Runs for EVERY application
        # processed this run, regardless of whether that application's own
        # primary-record outcome was success/skipped_unchanged/failed/
        # parse_failed -- a primary-record outcome must never gate
        # secondary-artifact acquisition (same principle as SEC's
        # exhibits). There is no separate documents-discovery ledger
        # because (like SEC/FDA, unlike EMA) there is no bulk documents
        # feed to discover from independently of a specific application's
        # own file wrapper. ---
        for app_id in target_ids:
            query_id, query_text = first_query_by_id[app_id]
            try:
                document_bag = client.list_documents(app_id)
            except requests.RequestException as exc:
                logger.warning("application=%s document listing failed: %s", app_id, exc)
                failure_logger.info("application=%s error=documents_list_failed: %s", app_id, exc)
                document_bag = []

            for doc in parse_documents(app_id, document_bag):
                doc_key = f"{app_id}:{doc.document_identifier}"
                if not doc.download_url:
                    continue

                suffix = (doc.mime_type or "pdf").lower()
                prior_doc_state = checkpoint_store.get_record_state(checkpoint, doc_key, namespace=DOCUMENT_NAMESPACE)

                if prior_doc_state is not None:
                    # DOCUMENT_NAMESPACE already has an entry for this
                    # documentIdentifier -- that checkpoint write is saved
                    # to disk immediately after the raw file is written
                    # (below), so its mere presence PROVES the raw file
                    # already exists, even if a prior run crashed between
                    # that checkpoint save and its own end-of-run ledger
                    # flush (leaving no success/skipped_unchanged row for
                    # this document at all). Skip with NO HTTP request and
                    # reconstruct this run's ledger rows from the
                    # checkpoint's own stored hash/version -- re-fetching
                    # would silently overwrite the already-durable raw
                    # file with DIFFERENT bytes, since USPTO's /download
                    # endpoints dynamically re-render on every request
                    # (see module docstring) and documentIdentifier, not
                    # content, is the permanent identity signal here.
                    doc_version = prior_doc_state["version"]
                    doc_hash = prior_doc_state["content_hash"]
                    doc_path = output_dir / "raw" / "uspto" / app_id / "documents" / f"v{doc_version}_{doc.document_identifier}.{suffix}"
                    document_attempt_rows.append(
                        _document_attempt_row(doc_key, app_id, run_id, now, "skipped_unchanged", content_hash=doc_hash, version=doc_version)
                    )
                    document_content_rows.append(
                        new_manifest_row(
                            extra_fields=DOCUMENT_EXTRA_FIELDS,
                            source="uspto",
                            source_record_id=doc_key,
                            source_record_type="uspto_document",
                            title=f"{doc.document_description or doc.document_code} — {app_id}",
                            url=doc.download_url,
                            publication_or_release_date=doc.official_date,
                            retrieved_at=now,
                            query_id=query_id,
                            query_text=query_text,
                            raw_file_path=str(doc_path),
                            raw_format=suffix,
                            content_hash=doc_hash,
                            download_status="success",
                            http_status=200,
                            license_or_access_note=LICENSE_NOTE,
                            parent_record_id=app_id,
                            version=doc_version,
                            notes=None,
                            document_code=doc.document_code,
                            document_description=doc.document_description,
                        )
                    )
                    continue

                try:
                    doc_bytes = client.fetch_document(doc.download_url)
                except requests.RequestException as exc:
                    logger.warning("document=%s fetch failed: %s", doc_key, exc)
                    failure_logger.info("document=%s error=%s", doc_key, exc)
                    document_attempt_rows.append(_document_attempt_row(doc_key, app_id, run_id, now, "failed", error=str(exc)))
                    continue

                doc_hash = sha256_bytes(doc_bytes)
                doc_version = 1  # documentIdentifier is a permanent identity -- see module docstring.
                doc_dir = output_dir / "raw" / "uspto" / app_id / "documents"
                doc_dir.mkdir(parents=True, exist_ok=True)
                doc_path = doc_dir / f"v{doc_version}_{doc.document_identifier}.{suffix}"
                doc_path.write_bytes(doc_bytes)
                checkpoint_store.set_record_state(checkpoint, doc_key, doc_hash, doc_version, now, namespace=DOCUMENT_NAMESPACE)
                checkpoint_store.save(checkpoint)

                document_content_rows.append(
                    new_manifest_row(
                        extra_fields=DOCUMENT_EXTRA_FIELDS,
                        source="uspto",
                        source_record_id=doc_key,
                        source_record_type="uspto_document",
                        title=f"{doc.document_description or doc.document_code} — {app_id}",
                        url=doc.download_url,
                        publication_or_release_date=doc.official_date,
                        retrieved_at=now,
                        query_id=query_id,
                        query_text=query_text,
                        raw_file_path=str(doc_path),
                        raw_format=suffix,
                        content_hash=doc_hash,
                        download_status="success",
                        http_status=200,
                        license_or_access_note=LICENSE_NOTE,
                        parent_record_id=app_id,
                        version=doc_version,
                        notes=None,
                        document_code=doc.document_code,
                        document_description=doc.document_description,
                    )
                )
                document_attempt_rows.append(
                    _document_attempt_row(doc_key, app_id, run_id, now, "success", content_hash=doc_hash, version=doc_version)
                )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=APPLICATION_EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        write_manifest(document_content_rows, documents_manifest_path, extra_fields=DOCUMENT_EXTRA_FIELDS)
        append_only(document_attempt_rows, documents_attempts_path, DOCUMENT_ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        checkpoint["last_run_at"] = now
        checkpoint["last_success_max_date"] = args.until or now[:10]
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / "uspto.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(result, manifest_df, all_ids, backlog_ids, document_attempt_rows, reverify_ids),
            encoding="utf-8",
        )

        if parse_error is not None:
            raise RuntimeError(
                f"USPTO application parsing failed (raw bytes and prior progress already persisted): {parse_error}"
            )

        return result
