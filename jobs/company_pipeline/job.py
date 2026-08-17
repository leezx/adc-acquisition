"""Job 11: pharmaceutical company pipeline pages (Prompt.md section 11,
execution order section 29).

"Fundamentally different from database APIs" (Prompt.md's own framing):
no live search/discovery step exists here at all. Every (company,
pipeline_url) pair this job processes comes directly from the curated
`configs/company_registry.yaml` (adc_acquisition/company_registry.py,
shared with Job 05/SEC and eventually Job 08/company press releases) —
`pipeline_urls` is itself the fully-known work list, not something
discovered via a query whose result set varies over time. This is the
SAME reason Job 05/SEC never needed its own discovery ledger for the
CIK/company level (a curated identifier is not a discovery outcome) —
applied here at the (company, pipeline_url) level directly, so this job
has no discovery ledger at all: just company_pipeline.parquet (the
content-version manifest) and company_pipeline_attempts.parquet (the
attempts ledger). A company with no standalone pipeline page (e.g.
Seagen/ImmunoGen/Mersana post-acquisition, see the registry's notes) just
has an empty `pipeline_urls` list and is naturally skipped — not marked
inactive, since `active` continues to mean "still worth tracking
historically" for other jobs (SEC) reading the same registry.

Every (company, pipeline_url) pair is refetched and hash-compared EVERY
run — the ordinary SEC/FDA/EMA/USPTO pattern, not WIPO/EPO's skip-by-
default — because Prompt.md is explicit that "company pipeline pages
change over time... snapshots are essential," and the curated set here is
tiny (a handful of companies), so there is no efficiency pressure of the
kind that motivated WIPO's design.

ROUND-1 FIX (2026-08-17): always re-fetching does NOT make this job
immune to the "resolved state stale relative to a raw checkpoint" bug
class Job 08/WIPO and Job 10/EPO's round-1 reviews caught -- an earlier
version of this docstring claimed exactly that immunity, which review
correctly rejected. The checkpoint's content_hash/version is saved to
disk immediately after a raw write, but `company_pipeline.parquet` (the
manifest) and `company_pipeline_attempts.parquet` (the attempts ledger)
are only flushed ONCE, after the entire per-run loop completes. If the
process crashes after `checkpoint_store.save()` for one pair but before
that end-of-run flush, the checkpoint durably remembers "content hash A,
version 1" while the manifest never got a v1 row for it at all. The next
run refetches (as always), sees the SAME content hash A, and — with only
a checkpoint-hash comparison — would wrongly call this `skipped_unchanged`
forever, permanently orphaning that pipeline page from the manifest.
Fixed: a `materialized_state` snapshot is read from the EXISTING
`company_pipeline.parquet` at the START of each run (before this run
writes anything), and a checkpoint-hash match is only treated as a
genuine no-op ("skipped_unchanged") if the manifest itself already has a
row for that same content_hash. If the checkpoint says unchanged but the
manifest doesn't have it yet, this is `pending_recovery`: reuse the
existing raw file (already durable on disk), re-extract the title, and
emit the missing manifest/attempt rows with status `success` -- WITHOUT
bumping the version, since it's the same content that was already
fetched once, not a new one.

query_id/query_text: there is no static query registry YAML for this job
(unlike PubMed/WIPO/EPO/USPTO's configs/*_queries.yaml) — the "query"
IS the specific pipeline_url itself, which is dynamically read from the
company registry, not a fixed search string. Same deterministic-query-id-
via-hash pattern as Crossref's ad hoc --doi lookups:
`query_id = f"PIPELINE_{company_id}_{sha256(url)[:12]}"`, `query_version`
fixed at 1 (there is no evolving "search strategy" to version — a genuine
change to which URL is registered for a company produces a brand new
query_id, since the hash is derived from the URL itself).

Raw evidence: HTML/PDF/JSON bytes preserved verbatim, hash-compared and
versioned exactly like every other job (Prompt.md section 23) — written
to disk immediately, before the (deliberately minimal, regex-only, can't
meaningfully fail) <title> extraction is attempted. No RAW_NAMESPACE
checkpoint split is needed the way WIPO/EPO/USPTO need one: those jobs
need it because XML/JSON parsing can genuinely fail and leave raw/
normalized state disagreeing; title extraction here is wrapped so it can
never raise, so there is only ever one outcome (success) once the raw
bytes are captured.

--since/--until are NOT applicable here (same class of justified N/A as
Crossref's DOI-centric job): a pipeline page is a live, current-state
snapshot with no natural publication/release date of its own to filter
by (Pfizer's page happens to show an "as of <date>" string in its own
text, but that is page-specific and not extracted here — see
jobs/company_pipeline/parser.py's docstring on why individual-program
extraction is out of scope). --resume's retry-safety net still applies
via the standard "most recent attempt status" fresh/backlog/reverify
--limit fairness (fresh: never attempted; backlog: most recent attempt
failed; reverify: most recent attempt already resolved) — reverify comes
last so a small --limit can't get stuck re-verifying already-successful
pairs while starving out newly-registered ones as the registry grows.

LIVE-VERIFIED 2026-08-14 (plain requests + the descriptive User-Agent
above): Zymeworks, Sutro Biopharma, and ADC Therapeutics' pipeline pages
are all plain static HTML with real pipeline content in the raw response
(no JS rendering needed). Pfizer's oncology pipeline page is likewise
plain static HTML and accessible with this User-Agent. AbbVie's pipeline
page is behind an active Cloudflare JS challenge (see
jobs/company_pipeline/client.py) — recorded as a normal failed attempt,
not silently dropped, not worked around.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.company_registry import Company, load_companies
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from jobs.company_pipeline.client import RATE_LIMIT, PipelineClient
from jobs.company_pipeline.parser import extract_html_title, infer_raw_format
from jobs.company_pipeline.report import build_report

REGISTRY_PATH = Path("configs/company_registry.yaml")
EXTRA_FIELDS = ["company_id", "company", "official_domain"]
LICENSE_NOTE = "Company-published pipeline page, public disclosure."

ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]

UNRESOLVED_STATUSES = {"failed"}
RESOLVED_STATUSES = {"success", "skipped_unchanged"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pipeline_query_id(company_id: str, url: str) -> str:
    return f"PIPELINE_{company_id.upper()}_{sha256_bytes(url.encode('utf-8'))[:12]}"


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="company_pipeline", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _latest_status_by_id(attempts_path: Path) -> dict[str, str]:
    if not attempts_path.exists():
        return {}
    df = pd.read_parquet(attempts_path)
    if df.empty:
        return {}
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    return dict(zip(latest["source_record_id"], latest["status"]))


def _materialized_state_by_id(manifest_path: Path) -> dict[str, dict]:
    """The current content_hash/version already durable in the manifest
    ITSELF, read fresh at the start of a run -- the ground truth for
    "already materialized", independent of what the checkpoint or attempts
    ledger separately claim (see module docstring's round-1 fix)."""
    if not manifest_path.exists():
        return {}
    df = pd.read_parquet(manifest_path)
    if df.empty:
        return {}
    latest = df.sort_values("version").groupby("source_record_id", as_index=False).tail(1)
    return {
        row["source_record_id"]: {"content_hash": row["content_hash"], "version": row["version"]}
        for _, row in latest.iterrows()
    }


def _pipeline_manifest_row(
    company: Company, url: str, source_record_id: str, query_id: str, title: str | None,
    raw_path: Path, raw_format: str, content_hash: str, version: int, now: str, http_status: int,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="company_pipeline",
        source_record_id=source_record_id,
        source_record_type="company_pipeline_page",
        title=title,
        url=url,
        publication_or_release_date=None,
        retrieved_at=now,
        query_id=query_id,
        query_text=url,
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


class CompanyPipelineJob(AcquisitionJob):
    name = "company_pipeline"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--registry-file", type=str, default=str(REGISTRY_PATH),
            help="Path to the shared company registry YAML.",
        )
        parser.add_argument(
            "--company", type=str, default=None,
            help="Only process this company_id from the registry (default: all active companies with pipeline_urls).",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        client = PipelineClient(RetryingClient(RateLimiter(RATE_LIMIT)))

        companies = [c for c in load_companies(Path(args.registry_file)) if c.active and c.pipeline_urls]
        if args.company:
            companies = [c for c in companies if c.company_id == args.company]
            if not companies:
                raise RuntimeError(f"company_id={args.company!r} not found among active companies with pipeline_urls")
        if not companies:
            raise RuntimeError(f"no active companies with pipeline_urls found in {args.registry_file}")

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.since or args.until:
            result.notes.append(
                "--since/--until are not applicable: a pipeline page is a live, current-state snapshot with "
                "no natural publication/release date of its own to filter by (see module docstring)."
            )
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: every registered pipeline_url is always "
                "content-hash-checked against the checkpoint every run regardless, so there's no separate "
                "incremental-window narrowing to do."
            )
        now = _now_iso()
        run_id = now

        # --- Every (company, pipeline_url) pair comes directly from the
        # curated registry -- no discovery ledger needed (see module
        # docstring). Build the full work list up front. ---
        pairs: list[tuple[Company, str, str]] = []  # (company, url, source_record_id)
        for company in companies:
            for url in company.pipeline_urls:
                source_record_id = f"{company.company_id}:{sha256_bytes(url.encode('utf-8'))[:12]}"
                pairs.append((company, url, source_record_id))

        result.queries_run = len(pairs)
        result.records_discovered = len(pairs)

        attempts_path = output_dir / "manifests" / "company_pipeline_attempts.parquet"
        latest_status = _latest_status_by_id(attempts_path)

        all_ids = [source_record_id for _, _, source_record_id in pairs]
        pair_by_id = {source_record_id: (company, url) for company, url, source_record_id in pairs}

        fresh_ids = sorted(pid for pid in all_ids if pid not in latest_status)
        backlog_ids = sorted(pid for pid in all_ids if latest_status.get(pid) in UNRESOLVED_STATUSES)
        reverify_ids = sorted(pid for pid in all_ids if latest_status.get(pid) in RESOLVED_STATUSES)
        ordered_work = fresh_ids + backlog_ids + reverify_ids
        target_ids = ordered_work[: args.limit] if args.limit else ordered_work

        if args.dry_run:
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} registered pipeline pages "
                f"({len(fresh_ids)} never attempted, {len(backlog_ids)} unresolved retries, "
                f"{len(reverify_ids)} already-resolved reverify candidates)"
            )
            return result

        manifest_path = output_dir / "manifests" / "company_pipeline.parquet"
        # Read BEFORE this run writes anything -- the ground-truth snapshot
        # of what's actually durable in the manifest, used below to tell a
        # genuine no-op apart from a pending-recovery crash artifact (see
        # module docstring's round-1 fix).
        materialized_state = _materialized_state_by_id(manifest_path)

        content_rows = []
        attempt_rows = []

        for source_record_id in target_ids:
            company, url = pair_by_id[source_record_id]
            query_id = _pipeline_query_id(company.company_id, url)
            try:
                response = client.fetch(url)
            except requests.RequestException as exc:
                logger.warning("company=%s url=%s fetch failed: %s", company.company_id, url, exc)
                failure_logger.info("company=%s url=%s error=%s", company.company_id, url, exc)
                result.records_failed += 1
                attempt_rows.append(_record_row(source_record_id, run_id, now, "failed", query_id, url, error=str(exc)))
                continue

            if response.status_code != 200:
                logger.warning("company=%s url=%s: HTTP %d", company.company_id, url, response.status_code)
                failure_logger.info("company=%s url=%s error=http_%d", company.company_id, url, response.status_code)
                result.records_failed += 1
                attempt_rows.append(
                    _record_row(
                        source_record_id, run_id, now, "failed", query_id, url,
                        http_status=response.status_code, error=f"http_{response.status_code}",
                    )
                )
                continue

            content_bytes = response.content
            content_hash = sha256_bytes(content_bytes)
            prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id)
            raw_format = infer_raw_format(response.headers.get("Content-Type"), url)

            if prior_state and prior_state.get("content_hash") == content_hash:
                materialized = materialized_state.get(source_record_id)
                if materialized and materialized.get("content_hash") == content_hash:
                    # Genuine no-op: the checkpoint AND the manifest itself
                    # already agree this exact content is durable.
                    result.records_skipped_unchanged += 1
                    attempt_rows.append(
                        _record_row(
                            source_record_id, run_id, now, "skipped_unchanged", query_id, url,
                            content_hash=content_hash, version=prior_state["version"],
                        )
                    )
                    continue

                # Pending recovery: the checkpoint says this content is
                # already durable, but the manifest never recorded it (a
                # prior run crashed between the checkpoint save and the
                # end-of-run manifest flush -- see module docstring). Reuse
                # the existing raw file (already durable on disk under this
                # version), re-extract the title, and emit the missing
                # manifest/attempt rows WITHOUT bumping the version.
                version = prior_state["version"]
                raw_dir = output_dir / "raw" / "company_pipeline" / company.company_id / sha256_bytes(url.encode("utf-8"))[:12]
                raw_path = raw_dir / f"v{version}.{raw_format}"
                if not raw_path.exists():
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    raw_path.write_bytes(content_bytes)

                title = extract_html_title(content_bytes) if raw_format == "html" else None

                result.records_downloaded += 1
                attempt_rows.append(
                    _record_row(
                        source_record_id, run_id, now, "success", query_id, url,
                        content_hash=content_hash, version=version,
                    )
                )
                content_rows.append(
                    _pipeline_manifest_row(
                        company, url, source_record_id, query_id, title,
                        raw_path, raw_format, content_hash, version, now, response.status_code,
                    )
                )
                continue

            # New or CHANGED pipeline page: persist raw bytes and save the
            # checkpoint's version state to disk IMMEDIATELY -- same
            # raw-durability discipline as every other job, even though
            # title extraction below can't meaningfully fail (see module
            # docstring for why no RAW_NAMESPACE split is needed here).
            version = (prior_state["version"] + 1) if prior_state else 1
            raw_dir = output_dir / "raw" / "company_pipeline" / company.company_id / sha256_bytes(url.encode("utf-8"))[:12]
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"v{version}.{raw_format}"
            raw_path.write_bytes(content_bytes)
            checkpoint_store.set_record_state(checkpoint, source_record_id, content_hash, version, now)
            checkpoint_store.save(checkpoint)

            title = extract_html_title(content_bytes) if raw_format == "html" else None

            result.records_downloaded += 1
            attempt_rows.append(
                _record_row(
                    source_record_id, run_id, now, "success", query_id, url,
                    content_hash=content_hash, version=version,
                )
            )
            content_rows.append(
                _pipeline_manifest_row(
                    company, url, source_record_id, query_id, title,
                    raw_path, raw_format, content_hash, version, now, response.status_code,
                )
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / "company_pipeline.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(result, manifest_df, all_ids, fresh_ids, backlog_ids, reverify_ids, companies),
            encoding="utf-8",
        )

        return result
