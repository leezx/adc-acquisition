"""Job 12: company press releases / investor relations (Prompt.md section
12, execution order section 29).

"Separate this from company pipeline pages" (Prompt.md's own instruction)
— Job 11 archives a company's current-state pipeline snapshot; this job
acquires the company's own discrete, dated ANNOUNCEMENTS (clinical trial
initiation, first patient dosed, Phase I/II/III results, regulatory
submission, FDA/EMA approval, clinical hold, trial discontinuation,
program termination, licensing, option agreements, acquisition, M&A,
preclinical candidate nomination, IND clearance — Prompt.md's own list).
Those categories are NOT classified here: "acquisition only, no final
knowledge extraction" (Prompt.md section 1) applies exactly as it does to
every other job — every release from the registered feed is archived
regardless of category, same "acquire broadly, filter downstream"
principle already used for AbbVie/Pfizer's broad, non-ADC-specific
pipeline pages (jobs/company_pipeline/job.py).

Genuinely DOES need a discovery ledger (unlike Job 11's curated
pipeline_urls): each company's press_release_url is a curated LISTING
page, but the individual releases behind it are a discovery outcome that
grows over time — structurally the same as PubMed/FDA/EPO's discovery
step, not SEC's static CIK level. Three tables:
company_press_release.parquet (content-version manifest, one row per
release, raw HTML/PDF preserved verbatim), company_press_release_discovery
.parquet (every (release, company, run) triple, url included since the
discovery ledger IS the durable record of which URLs are already known —
see _known_urls_by_company), company_press_release_attempts.parquet
(every fetch attempt).

DISCOVERY MECHANISM: no official API exists for any of these IR
newsrooms — same "fundamentally different from database APIs" framing
Prompt.md gives Job 11. Live-verified 2026-08-17 that the registered
companies' listing pages reduce to a small number of REUSED third-party
IR-platform templates (jobs/company_press_release/parser.py's
TEMPLATE_PARSERS/PAGINATION_CONFIGS), selected per company via the
registry's new `press_release_template` field — not one bespoke parser
per company. Pagination is walked page-by-page per company, accumulating
newly-seen release URLs; the STOP CONDITION is "this page contributed
zero NOT-already-known items" (checked against BOTH this run's own
accumulated set AND every release ever discovered in a PRIOR run, read
from the discovery ledger at the very start) rather than "this page came
back empty" — live-verified that 2 of the 3 templates (Sutro's `?page=`,
Pfizer's `?page=`) CLAMP/WRAP to repeat an already-seen page once you
request past the real end, rather than emptying out the way ADC
Therapeutics/AbbVie's `?o=` offset template genuinely does; the
already-known-items rule handles both behaviors uniformly and, on every
incremental run after the first, stops after essentially one page instead
of re-walking a company's entire history every time (same efficiency
motivation as EMA's metadata-driven skip). A MAX_PAGES safety cap bounds
worst-case work (some companies, e.g. AbbVie, publish a large
non-ADC-specific volume) — hit, it's logged and surfaced in
`result.notes`, never silently truncated.

"Only collect from official company domains... do not mix media reports"
(Prompt.md) is enforced at DISCOVERY time: a listing item is only
accepted into scope if its own URL's domain is the registered company's
`official_domain` (or a subdomain of it) — see `_is_official_domain`.
Live-verified this is a non-issue in practice for all 4 currently-
reachable companies (every release detail URL stays on the company's own
domain, no wire-service redirect found), but the check stays as a general
safeguard for future registry entries.

MATERIALIZATION mirrors Job 10 (EPO)'s fully-hardened design UNMODIFIED,
proactively applied from the start rather than re-deriving it and risking
the same review rounds: default skip-without-fetch once a release is
successfully materialized (`--refresh` opts a run into re-verifying
already-successful releases too, versioning on genuine change — press
releases are treated as ordinarily immutable once published, but not
ASSUMED permanently so, same reasoning WIPO/EPO already established for
patent bibliographic data). Because DISCOVERY's own early-stop
optimization (above) means an already-known release never re-enters this
run's scope at all on an ordinary incremental run, `--refresh` ALSO
disables that early-stop and walks each company's full listing history
again — otherwise there would be nothing for `--refresh` to actually
reverify. The skip decision requires BOTH unchanged raw
bytes (own `raw_records` checkpoint namespace, saved to disk immediately
after every raw write, before any further step) AND the attempts ledger's
own most-recent status already being resolved AND that resolved attempt's
own recorded version matching the raw checkpoint's CURRENT version — a
version mismatch is `pending_recovery`, routed through the ordinary
per-item loop (like backlog) rather than trusted as a safe fast-skip; this
is the exact fix Job 10 (EPO)'s round-1 review required and Job 11
(company pipeline pages)'s round-1 review required via a different
mechanism (see _classify_release_ids and jobs/epo/job.py's
_classify_publication_ids, which this directly mirrors). Unlike WIPO/EPO,
there is no separate "parse" step that can independently fail here — the
release's title/date come from the LISTING page's own already-clean text
(preserved in the discovery ledger), not from re-parsing the detail
page's HTML — so there is no `parse_failed` attempt status, only
`failed` (a fetch-level failure) alongside `success`/`skipped_unchanged`.

`--since`/`--until` genuinely apply here (unlike Job 11, which has no
natural per-page date) — DISCOVERY always finds every release regardless
(the early-stop optimization above is about not re-walking already-KNOWN
pages, not about restricting to a date window), and `--since`/`--until`
only restrict which of the already-discovered releases get MATERIALIZED
this run, filtered client-side by the release's own listing-provided date
(no company site here exposes a server-side date-range parameter) — same
justified client-side-filtering pattern as SEC's `filing_date`. A release
whose date could not be parsed from its listing text is never excluded by
a date filter (can't filter what wasn't extracted). `--resume` is a
no-op beyond the default behavior, for the same reason as Job 08
(WIPO)/Job 10 (EPO): discovery already always re-sweeps (with the
early-stop optimization), so there is no separate cursor to narrow.
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
from jobs.company_press_release.parser import TEMPLATE_PARSERS, PAGINATION_CONFIGS, ReleaseListingItem
from jobs.company_press_release.report import build_report

REGISTRY_PATH = Path("configs/company_registry.yaml")
EXTRA_FIELDS = ["company_id", "company", "official_domain"]
LICENSE_NOTE = "Company-published press release / investor-relations announcement, public disclosure."

# Safety cap on discovery pagination per company per run -- some
# registered companies (e.g. AbbVie) publish a large, non-ADC-specific
# volume; hit, it's logged and surfaced in result.notes, never a silent
# truncation.
MAX_PAGES = 200

RAW_NAMESPACE = "raw_records"

DISCOVERY_COLUMNS = [
    "source", "source_record_id", "company_id", "url",
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


def _release_id(company_id: str, url: str) -> str:
    return f"PRESSRELEASE_{company_id.upper()}_{sha256_bytes(url.encode('utf-8'))[:12]}"


def _is_official_domain(url: str, official_domain: str | None) -> bool:
    if not official_domain:
        return False
    netloc = urlparse(url).netloc.lower()
    domain = official_domain.lower()
    return netloc == domain or netloc.endswith("." + domain)


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="company_press_release", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _press_release_manifest_row(
    company: Company, item: ReleaseListingItem, source_record_id: str, query_id: str, title: str | None,
    raw_path: Path, raw_format: str, content_hash: str, version: int, now: str, http_status: int,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="company_press_release",
        source_record_id=source_record_id,
        source_record_type="company_press_release",
        title=title,
        url=item.url,
        publication_or_release_date=item.release_date,
        retrieved_at=now,
        query_id=query_id,
        query_text=item.url,
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


def _classify_release_ids(
    all_ids: list, latest_attempts: dict, checkpoint_store, checkpoint,
) -> tuple:
    """Same pattern as jobs/epo/job.py's _classify_publication_ids: a
    resolved attempt (success/skipped_unchanged) is only safe to
    fast-skip if its own recorded version matches RAW_NAMESPACE's CURRENT
    version -- otherwise it's pending_recovery (raw durable, ledger
    stale), routed through the ordinary per-item loop instead of trusted
    as a no-request skip."""
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


def _known_resolved_urls_by_company(
    discovery_path: Path, latest_attempts: dict, checkpoint_store, checkpoint,
) -> dict[str, set]:
    """Every release URL whose MOST RECENT attempt is genuinely, safely
    resolved (see _classify_release_ids) across ALL prior runs -- read
    fresh at the start of THIS run, before any pagination happens, so an
    incremental run's discovery sweep can stop as soon as it re-encounters
    only this kind of content (see module docstring).

    Deliberately NOT "every URL ever discovered": a release whose most
    recent attempt is `failed` (backlog) or `pending_recovery` (ledger
    stale relative to the raw checkpoint) must NOT count as "known" here,
    or it would never re-enter `hits_by_id` on an ordinary run either --
    the exact same "discovered is not resolved" conflation Job 09
    (USPTO)'s round-1 review caught, one level up (at the discovery-sweep
    level instead of the per-record skip-decision level)."""
    if not discovery_path.exists():
        return {}
    df = pd.read_parquet(discovery_path)
    if df.empty:
        return {}
    all_ids_ever = df["source_record_id"].unique().tolist()
    resolved_ids_ever, _ = _classify_release_ids(all_ids_ever, latest_attempts, checkpoint_store, checkpoint)
    resolved_rows = df[df["source_record_id"].isin(resolved_ids_ever)]
    out: dict[str, set] = {}
    for company_id, group in resolved_rows.groupby("company_id"):
        out[company_id] = set(group["url"])
    return out


class CompanyPressReleaseJob(AcquisitionJob):
    name = "company_press_release"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--registry-file", type=str, default=str(REGISTRY_PATH),
            help="Path to the shared company registry YAML.",
        )
        parser.add_argument(
            "--company", type=str, default=None,
            help="Only process this company_id from the registry (default: all active companies with press_release_url).",
        )
        parser.add_argument(
            "--refresh", action="store_true",
            help=(
                "Re-fetch and hash-compare EVERY discovered release, including ones already "
                "successfully materialized, to pick up rare post-publication corrections (run "
                "periodically, not on every incremental run)."
            ),
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        client = WebSnapshotClient(RetryingClient(RateLimiter(RATE_LIMIT)))

        companies = [c for c in load_companies(Path(args.registry_file)) if c.active and c.press_release_url]
        if args.company:
            companies = [c for c in companies if c.company_id == args.company]
            if not companies:
                raise RuntimeError(f"company_id={args.company!r} not found among active companies with press_release_url")
        if not companies:
            raise RuntimeError(f"no active companies with press_release_url found in {args.registry_file}")

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        now = _now_iso()
        run_id = now

        discovery_path = output_dir / "manifests" / "company_press_release_discovery.parquet"
        attempts_path = output_dir / "manifests" / "company_press_release_attempts.parquet"
        # Computed BEFORE discovery: the early-stop pre-seed below must
        # only treat a release as "known, safe to stop at" if it's
        # actually resolved (not merely previously discovered) -- see
        # _known_resolved_urls_by_company's docstring.
        latest_attempts = _latest_attempt_by_id(attempts_path)
        known_urls_by_company = _known_resolved_urls_by_company(discovery_path, latest_attempts, checkpoint_store, checkpoint)

        hits_by_id: dict[str, tuple] = {}  # source_record_id -> (Company, ReleaseListingItem)
        first_query_by_id: dict[str, tuple] = {}  # source_record_id -> (query_id, query_text)

        discovery_error: str | None = None
        try:
            for company in companies:
                template = company.press_release_template
                parser_fn = TEMPLATE_PARSERS.get(template)
                config = PAGINATION_CONFIGS.get(template)
                query_id = f"PRESSRELEASE_LISTING_{company.company_id.upper()}"
                query_text = company.press_release_url

                if parser_fn is None or config is None:
                    # No known listing-page template (e.g. zymeworks: page
                    # currently unreachable, template never observed) --
                    # still attempt the listing fetch so failures are
                    # recorded normally, but can't paginate/parse without
                    # a known template.
                    try:
                        client.fetch(company.press_release_url)
                        logger.warning(
                            "company=%s has no registered press_release_template but its listing "
                            "page is reachable -- add a template to configs/company_registry.yaml",
                            company.company_id,
                        )
                    except requests.RequestException as exc:
                        logger.warning("company=%s press-release listing unreachable: %s", company.company_id, exc)
                        failure_logger.info("company=%s url=%s error=%s", company.company_id, company.press_release_url, exc)
                    continue

                # Under --refresh, don't pre-seed with prior runs' known
                # URLs: the early-stop optimization below would otherwise
                # mean an already-materialized release never re-enters
                # `hits_by_id` at all, leaving --refresh nothing to
                # actually reverify (see module docstring's --refresh
                # description). --refresh therefore walks each company's
                # full listing history again, same "occasional, not every
                # incremental run" cost tradeoff WIPO/EPO's --refresh
                # already accepts.
                known_urls = set() if args.refresh else set(known_urls_by_company.get(company.company_id, set()))
                cursor = config["start"]
                base_url = company.press_release_url
                hit_max_pages = True
                for _page_num in range(MAX_PAGES):
                    sep = "&" if "?" in base_url else "?"
                    page_url = f"{base_url}{sep}{config['param']}={cursor}"
                    response = client.fetch(page_url)
                    if response.status_code != 200:
                        logger.warning("company=%s page=%s: HTTP %d", company.company_id, page_url, response.status_code)
                        hit_max_pages = False
                        break
                    page_items = parser_fn(response.content, base_url)
                    official_items = [it for it in page_items if _is_official_domain(it.url, company.official_domain)]
                    if len(official_items) != len(page_items):
                        logger.info(
                            "company=%s excluded %d off-official-domain listing item(s) on %s",
                            company.company_id, len(page_items) - len(official_items), page_url,
                        )
                    new_items = [it for it in official_items if it.url not in known_urls]
                    if not official_items or not new_items:
                        hit_max_pages = False
                        break
                    for it in new_items:
                        known_urls.add(it.url)
                        source_record_id = _release_id(company.company_id, it.url)
                        hits_by_id.setdefault(source_record_id, (company, it))
                        first_query_by_id.setdefault(source_record_id, (query_id, query_text))
                    if config["step_mode"] == "item_count":
                        cursor += len(page_items)
                    else:
                        cursor += config["step"]
                if hit_max_pages:
                    logger.warning(
                        "company=%s hit MAX_PAGES=%d safety cap during discovery -- some history may "
                        "not have been walked this run",
                        company.company_id, MAX_PAGES,
                    )
                    result.notes.append(
                        f"company={company.company_id}: MAX_PAGES safety cap reached, discovery may be incomplete this run"
                    )
        except requests.RequestException as exc:
            # Persist whatever discovery this run DID gather (below)
            # before surfacing the error -- a partial discovery sweep
            # must not lose the provenance it already collected.
            discovery_error = str(exc)
            logger.error("company press-release discovery stopped early: %s", discovery_error)

        result.queries_run = len(companies)
        result.records_discovered = len(hits_by_id)

        if not args.dry_run:
            discovery_rows = []
            for source_record_id, (company, item) in hits_by_id.items():
                query_id, query_text = first_query_by_id[source_record_id]
                discovery_rows.append(dict(
                    source="company_press_release", source_record_id=source_record_id,
                    company_id=company.company_id, url=item.url,
                    query_id=query_id, query_version=1, query_text=query_text,
                    discovered_at=now, run_id=run_id,
                ))
            append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        if discovery_error is not None:
            raise RuntimeError(
                f"company press-release discovery incomplete (partial results already persisted): {discovery_error}"
            )

        # latest_attempts was already computed before discovery (see
        # above) -- reused here rather than re-reading the ledger, and
        # still correct: nothing wrote to it between then and now.
        unresolved_ids = {rid for rid, att in latest_attempts.items() if att["status"] in UNRESOLVED_STATUSES}

        all_ids = list(hits_by_id.keys())
        resolved_ids, pending_recovery_ids = _classify_release_ids(all_ids, latest_attempts, checkpoint_store, checkpoint)
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
                return item.release_date is None or (since <= item.release_date <= until)

            fresh_ids = [rid for rid in fresh_ids if _in_range(rid)]
            backlog_ids = [rid for rid in backlog_ids if _in_range(rid)]
            pending_recovery_ids = [rid for rid in pending_recovery_ids if _in_range(rid)]
            already_skipped_ids = [rid for rid in already_skipped_ids if _in_range(rid)]
            result.notes.append(
                "--since/--until filter which already-discovered releases are materialized this run "
                "(client-side, by each release's own listing-provided date); a release whose date "
                "could not be parsed is never excluded by this filter."
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
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered releases "
                f"({len(fresh_ids)} never attempted, {len(backlog_ids)} unresolved retries, "
                f"{len(pending_recovery_ids)} pending recovery, "
                f"{len(fast_skip_ids)} already successful and skipped with no request"
                + (", 0 refresh re-checks (--refresh not set)" if not args.refresh else "")
                + ")"
            )
            return result

        manifest_path = output_dir / "manifests" / "company_press_release.parquet"
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
                logger.warning("release=%s url=%s fetch failed: %s", source_record_id, item.url, exc)
                failure_logger.info("release=%s url=%s error=%s", source_record_id, item.url, exc)
                result.records_failed += 1
                attempt_rows.append(_record_row(source_record_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            if response.status_code != 200:
                logger.warning("release=%s url=%s: HTTP %d", source_record_id, item.url, response.status_code)
                failure_logger.info("release=%s url=%s error=http_%d", source_record_id, item.url, response.status_code)
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
            raw_dir = output_dir / "raw" / "company_press_release" / company.company_id / sha256_bytes(item.url.encode("utf-8"))[:12]

            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                version = raw_prior_state["version"]
                raw_path = raw_dir / f"v{version}.{raw_format}"
                if source_record_id in already_skipped_id_set:
                    # Already fully resolved before this run (a --refresh
                    # re-check): unchanged content AND the ledger's own
                    # most-recent status is already resolved -- a genuine
                    # no-op, no re-materialization needed.
                    result.records_skipped_unchanged += 1
                    attempt_rows.append(
                        _record_row(
                            source_record_id, run_id, now, "skipped_unchanged", query_id, query_text,
                            content_hash=content_hash, version=version,
                        )
                    )
                    continue
                # Else: fresh/backlog/pending_recovery whose raw content
                # happens to match a PRIOR fetch that was never
                # successfully materialized (e.g. an interrupted run) --
                # fall through and recover, reusing the existing raw file
                # rather than rewriting it.
            else:
                version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.{raw_format}"
                raw_path.write_bytes(content_bytes)
                checkpoint_store.set_record_state(checkpoint, source_record_id, content_hash, version, now, namespace=RAW_NAMESPACE)
                checkpoint_store.save(checkpoint)

            title = item.headline or (extract_html_title(content_bytes) if raw_format == "html" else None)

            result.records_downloaded += 1
            attempt_rows.append(
                _record_row(source_record_id, run_id, now, "success", query_id, query_text, content_hash=content_hash, version=version)
            )
            content_rows.append(
                _press_release_manifest_row(
                    company, item, source_record_id, query_id, title,
                    raw_path, raw_format, content_hash, version, now, response.status_code,
                )
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / "company_press_release.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(result, manifest_df, all_ids, fresh_ids, backlog_ids, pending_recovery_ids, fast_skip_ids, companies),
            encoding="utf-8",
        )

        return result
