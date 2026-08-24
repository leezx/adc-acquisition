"""Company scientific-presentation source (BREADTH_PLAN.md Phase 5 Part
7) -- NOT a Prompt.md job (Prompt.md's job list stops at Job 15). Part of
the breadth-layer initiative, following Job 11 (company pipeline pages)
and Job 12 (company press releases)'s established architecture closely,
but for a genuinely different kind of page: a company's IR newsroom
announces corporate news (Job 12), but its ACTUAL scientific congress
presentations/posters (AACR/ASCO/ESMO/ASH/etc.) -- the early-seed
breadth signal this initiative most wants -- often live on a separate
page, sometimes even a separate domain, that Job 11/12 never touch.

REUSE SEARCH DONE FIRST (Part 7's own instruction, same discipline as
Phase 4's conference-corpus reuse check): live-checked all 8 companies in
configs/company_registry.yaml for a genuine, scrapable scientific-
presentations page before writing any code. Only 2 have one:
- ADC Therapeutics (adctmedical.com/congresses/, a separate medical-
  affairs microsite, NOT adctherapeutics.com/ir.adctherapeutics.com).
- Sutro Biopharma (sutrobio.com/news/presentations/, a WordPress category
  page on the main corporate domain).
The other 6 do NOT get a fabricated/guessed entry: AbbVie's main domain is
behind the same Cloudflare challenge already documented for its pipeline
page (confirmed live 2026-08-24, no separate public microsite found);
Pfizer has no distinct presentations archive (only stale 2018-2020 press-
kit assets, not real congress presentation content); Seagen/ImmunoGen/
Mersana are acquired/absorbed with no standalone page of their own, same
as their pipeline/press-release situation (confirmed live 2026-08-24
that their domains still redirect to the same acquirers already
documented). See configs/company_registry.yaml's presentations_url/
presentations_template comment for the full per-company disclosure.

OWN-DOMAIN CHECK IS ANCHORED TO presentations_url'S OWN HOST, NOT
official_domain -- a deliberate departure from Job 12's
_is_official_domain(url, company.official_domain). ADC Therapeutics'
scientific-presentations microsite (adctmedical.com) is a genuinely
different domain from its registered official_domain
(adctherapeutics.com), confirmed to be ADC Therapeutics' own official
medical-affairs site (not a third party) via its page branding/title --
checking against official_domain would incorrectly exclude every item
this source finds. Each company's presentations_url is itself a curated,
individually-verified entry (same trust model as pipeline_urls in Job
11, which does no domain-matching at all) -- the domain check here exists
only to guard against off-domain SYNDICATION links a listing page might
also contain (e.g. a wire-service mirror), anchored to whatever domain
that specific company's presentations_url was actually verified on.

TWO GENUINELY DIFFERENT PAGINATION SHAPES (jobs/company_scientific_
presentations/parser.py's PAGINATION_CONFIGS), unlike Job 12 where all
three templates share a query-string `?param=N` shape:
- "single_page" (ADC Therapeutics): fetched exactly once, no cursor at
  all -- all ~115 entries load on the one page (confirmed live, no
  pagination controls exist). A single_page template's discovery walk is
  therefore just one fetch, not a loop.
- "wordpress_path" (Sutro): standard WordPress `/page/N/` PATH-based
  pagination (not a query-string parameter) -- confirmed live that pages
  past the real end parse to zero items (a static always-present
  "page"-type post exists on every page but never matches the entry-title
  pattern used to find real items), so the SAME "stop when this page
  contributes zero NOT-already-known items" rule Job 12 established
  applies here too, and is a genuine empty-page stop for this template
  (not a clamp/wraparound the way 2 of Job 12's 3 templates are).

MATERIALIZATION mirrors Job 12's fully-hardened design UNMODIFIED --
same checkpoint-based skip/version-bump logic, same query_id/query_text
provenance-consistency discipline (Job 12's round-1 fix), same discovery-
failure isolation per company. An item's own URL may be a direct PDF
(ADC Therapeutics) or an HTML detail page (Sutro) -- transparent to this
job's generic fetch/store logic, which already infers raw_format from the
response Content-Type/URL (adc_acquisition.html_utils.infer_raw_format),
same as every other job. Deliberately NOT following a Sutro item one hop
deeper to find an embedded PDF within its detail page -- same
"acquisition preserves raw evidence, it does not chase every embedded
asset" principle already established for Job 12's press-release detail
pages.

Three tables: company_scientific_presentations.parquet (content-version
manifest), company_scientific_presentations_discovery.parquet (every
(presentation, company, run) triple this run's live pagination actually
observed, plus the listing-provided title/date/congress so a presentation
can be reconstructed WITHOUT re-fetching a listing page), company_
scientific_presentations_attempts.parquet (every fetch attempt).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.company_registry import Company, load_companies
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.html_utils import extract_html_title, infer_raw_format
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.web_snapshot_client import DEFAULT_RATE_LIMIT as RATE_LIMIT
from adc_acquisition.web_snapshot_client import WebSnapshotClient
from jobs.company_scientific_presentations.parser import (
    PAGINATION_CONFIGS,
    TEMPLATE_PARSERS,
    PresentationListingItem,
    page_url,
)
from jobs.company_scientific_presentations.report import build_report

REGISTRY_PATH = Path("configs/company_registry.yaml")
EXTRA_FIELDS = ["company_id", "company", "official_domain", "congress"]
LICENSE_NOTE = "Company-published scientific congress presentation/poster, public disclosure."

# Safety cap on discovery pagination per company per run -- same
# reasoning as Job 12's MAX_PAGES (a "wordpress_path" company could in
# principle publish a very long history). "single_page" templates never
# approach this since they fetch exactly once regardless.
MAX_PAGES = 200

RAW_NAMESPACE = "raw_records"

DISCOVERY_COLUMNS = [
    "source", "source_record_id", "company_id", "url", "title", "presentation_date", "congress",
    "query_id", "query_version", "query_text", "discovered_at", "run_id",
]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]

UNRESOLVED_STATUSES = {"failed"}
RESOLVED_STATUSES = {"success", "skipped_unchanged"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _presentation_id(company_id: str, url: str) -> str:
    return f"SCIPRESENTATION_{company_id.upper()}_{sha256_bytes(url.encode('utf-8'))[:12]}"


def _is_on_presentations_domain(url: str, presentations_url: str) -> bool:
    """Anchored to presentations_url's OWN host, never official_domain --
    see module docstring for why (ADC Therapeutics' presentations
    microsite is a genuinely different, but still officially theirs,
    domain)."""
    netloc = urlparse(url).netloc.lower()
    domain = urlparse(presentations_url).netloc.lower()
    return bool(domain) and (netloc == domain or netloc.endswith("." + domain))


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="company_scientific_presentations", source_record_id=source_record_id, run_id=run_id,
        attempted_at=attempted_at, status=status, http_status=http_status, error=error,
        query_id=query_id, query_text=query_text, content_hash=content_hash, version=version,
    )


def _manifest_row(
    company: Company, item: PresentationListingItem, source_record_id: str, query_id: str, query_text: str,
    title: str | None, raw_path: Path, raw_format: str, content_hash: str, version: int, now: str, http_status: int,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="company_scientific_presentations",
        source_record_id=source_record_id,
        source_record_type="company_scientific_presentation",
        title=title,
        url=item.url,
        publication_or_release_date=item.presentation_date,
        retrieved_at=now,
        query_id=query_id,
        query_text=query_text,
        raw_file_path=str(raw_path),
        raw_format=raw_format,
        content_hash=content_hash,
        download_status="success",
        http_status=http_status,
        license_or_access_note=LICENSE_NOTE,
        parent_record_id=None,
        version=version,
        notes=None,
        company_id=company.company_id,
        company=company.canonical_name,
        official_domain=company.official_domain,
        congress=item.congress,
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


def _classify_presentation_ids(all_ids: list, latest_attempts: dict, checkpoint_store, checkpoint) -> tuple:
    """Same pattern as jobs/company_press_release/job.py's
    _classify_release_ids: a resolved attempt is only safe to fast-skip
    if its own recorded version matches RAW_NAMESPACE's CURRENT version."""
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


def _discovery_history_state(
    discovery_path: Path, latest_attempts: dict, checkpoint_store, checkpoint, companies_by_id: dict,
) -> tuple:
    """Same shape as jobs/company_press_release/job.py's
    _discovery_history_state -- see that module's docstring for the full
    reasoning (a not-genuinely-resolved presentation must re-enter this
    run's scope regardless of whether this run's live pagination happens
    to re-reach its page)."""
    if not discovery_path.exists():
        return {}, {}
    df = pd.read_parquet(discovery_path)
    if df.empty:
        return {}, {}
    latest_rows = df.sort_values("discovered_at").groupby("source_record_id", as_index=False).tail(1)
    all_ids_ever = latest_rows["source_record_id"].tolist()
    resolved_ids_ever, _ = _classify_presentation_ids(all_ids_ever, latest_attempts, checkpoint_store, checkpoint)
    known_urls_by_company: dict[str, set] = {}
    unresolved_backlog_by_id: dict[str, tuple] = {}
    for _, row in latest_rows.iterrows():
        rid = row["source_record_id"]
        if rid in resolved_ids_ever:
            known_urls_by_company.setdefault(row["company_id"], set()).add(row["url"])
            continue
        company = companies_by_id.get(row["company_id"])
        if company is None:
            continue
        item = PresentationListingItem(
            url=row["url"], title=row["title"], presentation_date=row["presentation_date"], congress=row["congress"],
        )
        unresolved_backlog_by_id[rid] = (company, item)
    return known_urls_by_company, unresolved_backlog_by_id


class CompanyScientificPresentationsJob(AcquisitionJob):
    name = "company_scientific_presentations"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--registry-file", type=str, default=str(REGISTRY_PATH),
            help="Path to the shared company registry YAML.",
        )
        parser.add_argument(
            "--company", type=str, default=None,
            help="Only process this company_id from the registry (default: all active companies with presentations_url).",
        )
        parser.add_argument(
            "--refresh", action="store_true",
            help=(
                "Re-fetch and hash-compare EVERY discovered presentation, including ones already "
                "successfully materialized (run periodically, not on every incremental run)."
            ),
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        client = WebSnapshotClient(RetryingClient(RateLimiter(RATE_LIMIT)))

        companies = [c for c in load_companies(Path(args.registry_file)) if c.active and c.presentations_url]
        if args.company:
            companies = [c for c in companies if c.company_id == args.company]
            if not companies:
                raise RuntimeError(f"company_id={args.company!r} not found among active companies with presentations_url")
        if not companies:
            raise RuntimeError(f"no active companies with presentations_url found in {args.registry_file}")

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        now = _now_iso()
        run_id = now

        discovery_path = output_dir / "manifests" / "company_scientific_presentations_discovery.parquet"
        attempts_path = output_dir / "manifests" / "company_scientific_presentations_attempts.parquet"
        companies_by_id = {c.company_id: c for c in companies}
        latest_attempts = _latest_attempt_by_id(attempts_path)
        known_urls_by_company, unresolved_backlog_by_id = _discovery_history_state(
            discovery_path, latest_attempts, checkpoint_store, checkpoint, companies_by_id,
        )

        hits_by_id: dict[str, tuple] = {}  # source_record_id -> (Company, PresentationListingItem)
        first_query_by_id: dict[str, tuple] = {}
        newly_discovered_ids: set = set()
        discovery_failures: list = []

        for company in companies:
            template = company.presentations_template
            parser_fn = TEMPLATE_PARSERS.get(template)
            config = PAGINATION_CONFIGS.get(template)
            query_id = f"SCIPRESENTATION_LISTING_{company.company_id.upper()}"
            query_text = company.presentations_url
            base_url = company.presentations_url

            if parser_fn is None or config is None:
                try:
                    response = client.fetch(base_url)
                    if response.status_code != 200:
                        discovery_failures.append(dict(
                            company_id=company.company_id, reason="HTTP_NON_200", detail=f"http_{response.status_code}",
                        ))
                    else:
                        discovery_failures.append(dict(
                            company_id=company.company_id, reason="UNKNOWN_TEMPLATE",
                            detail="listing page reachable but no presentations_template registered",
                        ))
                except requests.RequestException as exc:
                    discovery_failures.append(dict(company_id=company.company_id, reason="REQUEST_EXCEPTION", detail=str(exc)))
                    failure_logger.info("company=%s url=%s error=%s", company.company_id, base_url, exc)
                continue

            known_urls = set() if args.refresh else set(known_urls_by_company.get(company.company_id, set()))
            single_page = config["mode"] == "single_page"
            hit_max_pages = True
            is_first_page = True
            try:
                page_range = [1] if single_page else range(config["start"], config["start"] + MAX_PAGES)
                for page_num in page_range:
                    fetch_url = base_url if single_page else page_url(base_url, template, page_num)
                    response = client.fetch(fetch_url)
                    if response.status_code != 200:
                        discovery_failures.append(dict(
                            company_id=company.company_id, reason="HTTP_NON_200",
                            detail=f"http_{response.status_code} at {fetch_url}",
                        ))
                        logger.warning("company=%s page=%s: HTTP %d", company.company_id, fetch_url, response.status_code)
                        hit_max_pages = False
                        break
                    page_items = parser_fn(response.content, base_url)
                    if is_first_page and not page_items:
                        discovery_failures.append(dict(
                            company_id=company.company_id, reason="FIRST_PAGE_PARSE_ZERO",
                            detail=f"parser found 0 items on first page ({fetch_url}) -- possible template drift",
                        ))
                        logger.warning(
                            "company=%s first page parsed 0 items (%s) -- possible template drift",
                            company.company_id, fetch_url,
                        )
                        hit_max_pages = False
                        break
                    is_first_page = False
                    on_domain_items = [it for it in page_items if _is_on_presentations_domain(it.url, base_url)]
                    if len(on_domain_items) != len(page_items):
                        logger.info(
                            "company=%s excluded %d off-presentations-domain listing item(s) on %s",
                            company.company_id, len(page_items) - len(on_domain_items), fetch_url,
                        )
                    new_items = [it for it in on_domain_items if it.url not in known_urls]
                    if not on_domain_items or not new_items:
                        hit_max_pages = False
                        break
                    for it in new_items:
                        known_urls.add(it.url)
                        source_record_id = _presentation_id(company.company_id, it.url)
                        hits_by_id.setdefault(source_record_id, (company, it))
                        first_query_by_id.setdefault(source_record_id, (query_id, query_text))
                        newly_discovered_ids.add(source_record_id)
                    if single_page:
                        hit_max_pages = False
                        break
                if hit_max_pages and not single_page:
                    discovery_failures.append(dict(
                        company_id=company.company_id, reason="MAX_PAGES_REACHED",
                        detail=f"hit MAX_PAGES={MAX_PAGES} safety cap -- some history may not have been walked this run",
                    ))
            except requests.RequestException as exc:
                discovery_failures.append(dict(company_id=company.company_id, reason="REQUEST_EXCEPTION", detail=str(exc)))
                logger.warning("company=%s discovery pagination failed: %s", company.company_id, exc)
                failure_logger.info("company=%s error=%s", company.company_id, exc)

        for rid, (company, item) in unresolved_backlog_by_id.items():
            hits_by_id.setdefault(rid, (company, item))
            first_query_by_id.setdefault(
                rid, (f"SCIPRESENTATION_LISTING_{company.company_id.upper()}", company.presentations_url)
            )

        result.queries_run = len(companies)
        result.records_discovered = len(hits_by_id)
        if discovery_failures:
            result.notes.append(
                f"{len(discovery_failures)} discovery failure(s) this run (see report's Discovery "
                "failures section): " + "; ".join(f"{f['company_id']}:{f['reason']}" for f in discovery_failures)
            )

        if not args.dry_run:
            discovery_rows = []
            for source_record_id in newly_discovered_ids:
                company, item = hits_by_id[source_record_id]
                query_id, query_text = first_query_by_id[source_record_id]
                discovery_rows.append(dict(
                    source="company_scientific_presentations", source_record_id=source_record_id,
                    company_id=company.company_id, url=item.url, title=item.title,
                    presentation_date=item.presentation_date, congress=item.congress,
                    query_id=query_id, query_version=1, query_text=query_text,
                    discovered_at=now, run_id=run_id,
                ))
            append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        unresolved_ids = {rid for rid, att in latest_attempts.items() if att["status"] in UNRESOLVED_STATUSES}

        all_ids = list(hits_by_id.keys())
        resolved_ids, pending_recovery_ids = _classify_presentation_ids(all_ids, latest_attempts, checkpoint_store, checkpoint)
        pending_recovery_id_set = set(pending_recovery_ids)
        fresh_ids = sorted(
            rid for rid in all_ids
            if rid not in resolved_ids and rid not in unresolved_ids and rid not in pending_recovery_id_set
        )
        backlog_ids = sorted(rid for rid in all_ids if rid in unresolved_ids)
        already_skipped_ids = sorted(resolved_ids)

        if args.since or args.until:
            since = args.since or "0000-00-00"
            until = args.until or "9999-99-99"

            def _in_range(rid: str) -> bool:
                _, item = hits_by_id[rid]
                return item.presentation_date is None or (since <= item.presentation_date <= until)

            fresh_ids = [rid for rid in fresh_ids if _in_range(rid)]
            backlog_ids = [rid for rid in backlog_ids if _in_range(rid)]
            pending_recovery_ids = [rid for rid in pending_recovery_ids if _in_range(rid)]
            already_skipped_ids = [rid for rid in already_skipped_ids if _in_range(rid)]
            result.notes.append(
                "--since/--until filter which already-discovered presentations are materialized this run "
                "(client-side, by each presentation's own listing-provided date); a presentation whose date "
                "could not be parsed (e.g. every ADC Therapeutics item -- congress year only) is never "
                "excluded by this filter."
            )

        if args.refresh:
            ordered_work = fresh_ids + backlog_ids + pending_recovery_ids + already_skipped_ids
            fast_skip_ids: list = []
        else:
            ordered_work = fresh_ids + backlog_ids + pending_recovery_ids
            fast_skip_ids = already_skipped_ids
        target_ids = ordered_work[: args.limit] if args.limit else ordered_work

        if args.dry_run:
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered presentations "
                f"({len(fresh_ids)} never attempted, {len(backlog_ids)} unresolved retries, "
                f"{len(pending_recovery_ids)} pending recovery, "
                f"{len(fast_skip_ids)} already successful and skipped with no request"
                + (", 0 refresh re-checks (--refresh not set)" if not args.refresh else "")
                + ")"
            )
            return result

        manifest_path = output_dir / "manifests" / "company_scientific_presentations.parquet"
        content_rows = []
        attempt_rows = []
        already_skipped_id_set = set(already_skipped_ids)

        for source_record_id in fast_skip_ids:
            result.records_skipped_unchanged += 1
            query_id, query_text = first_query_by_id[source_record_id]
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id, namespace=RAW_NAMESPACE)
            attempt_rows.append(
                _record_row(
                    source_record_id, run_id, now, "skipped_unchanged", query_id, query_text,
                    content_hash=raw_prior_state["content_hash"] if raw_prior_state else None,
                    version=raw_prior_state["version"] if raw_prior_state else None,
                )
            )

        for source_record_id in target_ids:
            company, item = hits_by_id[source_record_id]
            query_id, query_text = first_query_by_id[source_record_id]
            try:
                response = client.fetch(item.url)
            except requests.RequestException as exc:
                logger.warning("presentation=%s url=%s fetch failed: %s", source_record_id, item.url, exc)
                failure_logger.info("presentation=%s url=%s error=%s", source_record_id, item.url, exc)
                result.records_failed += 1
                attempt_rows.append(_record_row(source_record_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if response.status_code != 200:
                logger.warning("presentation=%s url=%s: HTTP %d", source_record_id, item.url, response.status_code)
                failure_logger.info("presentation=%s url=%s error=http_%d", source_record_id, item.url, response.status_code)
                result.records_failed += 1
                attempt_rows.append(
                    _record_row(
                        source_record_id, run_id, now, "failed", query_id, query_text,
                        http_status=response.status_code, error=f"http_{response.status_code}",
                    )
                )
                continue

            content_bytes = response.content
            content_hash = sha256_bytes(content_bytes)
            raw_format = infer_raw_format(response.headers.get("Content-Type"), item.url)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id, namespace=RAW_NAMESPACE)
            raw_dir = (
                output_dir / "raw" / "company_scientific_presentations" / company.company_id
                / sha256_bytes(item.url.encode("utf-8"))[:12]
            )

            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                version = raw_prior_state["version"]
                raw_path = raw_dir / f"v{version}.{raw_format}"
                if source_record_id in already_skipped_id_set:
                    result.records_skipped_unchanged += 1
                    attempt_rows.append(
                        _record_row(
                            source_record_id, run_id, now, "skipped_unchanged", query_id, query_text,
                            content_hash=content_hash, version=version,
                        )
                    )
                    continue
            else:
                version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.{raw_format}"
                raw_path.write_bytes(content_bytes)
                checkpoint_store.set_record_state(checkpoint, source_record_id, content_hash, version, now, namespace=RAW_NAMESPACE)
                checkpoint_store.save(checkpoint)

            title = item.title or (extract_html_title(content_bytes) if raw_format == "html" else None)

            result.records_downloaded += 1
            attempt_rows.append(
                _record_row(source_record_id, run_id, now, "success", query_id, query_text, content_hash=content_hash, version=version)
            )
            content_rows.append(
                _manifest_row(
                    company, item, source_record_id, query_id, query_text, title,
                    raw_path, raw_format, content_hash, version, now, response.status_code,
                )
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / "company_scientific_presentations.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(
                result, manifest_df, all_ids, fresh_ids, backlog_ids, pending_recovery_ids, fast_skip_ids,
                companies, discovery_failures,
            ),
            encoding="utf-8",
        )

        return result
