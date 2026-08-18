"""Job 15: known-ADC asset-centric expansion (Prompt.md section 19, "JOB
15", execution order section 29) -- the final job.

Prompt.md's own framing: "After the first discovery pass, another
acquisition loop should operate from known asset names ... DISCOVERY PASS
-> temporary ADC candidates -> ASSET-CENTRIC EXPANSION PASS. Do not
conflate the two passes." Jobs 01-14 together ARE the first (broad,
topic-level) discovery pass. This job is the second: given a CURATED list
of already-known ADC assets (configs/known_adc_assets.yaml -- name,
aliases, dev codes, target, company; an INPUT to this job, not something
it discovers itself), it generates source-specific searches per Prompt.md's
template list ("<name>", "<alias>", "<name>" patent/trial/activity/
cytotoxicity/xenograft/IC50) and executes them against the appropriate
already-existing source jobs.

ARCHITECTURALLY DIFFERENT FROM EVERY OTHER JOB IN THIS REPO, BY DESIGN:
this job has NO content-version manifest, discovery ledger, or attempts
ledger of its own. Prompt.md says to "execute those searches independently
against appropriate source jobs" -- so this job generates query registries
and then calls Jobs 01 (PubMed), 02 (Europe PMC), 03 (ClinicalTrials.gov),
08 (WIPO), 09 (USPTO), and 10 (EPO) IN-PROCESS with those queries. Every
discovered/materialized record lands in THOSE jobs' own manifests
(pubmed.parquet, europe_pmc.parquet, clinicaltrials.parquet, wipo.parquet,
uspto.parquet, epo.parquet), tagged with its own asset-expansion query_id
for full provenance (Prompt.md section 20). Building a SEPARATE, redundant
acquisition/materialization pipeline here would duplicate content-hash
versioning, checkpointing, and rate-limiting logic those 6 jobs already
have fully hardened -- the same "don't re-acquire what an existing job
already legitimately does" discipline Job 13 (USPTO's own SPEC documents)
and Job 14 (Europe PMC) already established, taken to its natural
conclusion: the existing per-source JOBS are the acquisition mechanism,
not a new client this job would have to build and independently harden.

QUERY TRANSLATION PER SOURCE (jobs/known_adc_asset_expansion/query_templates.py):
Prompt.md's 8 templates are each source's OWN query syntax, not literal
English text passed through unchanged (same translation this repo already
does for the broad discovery query family across
configs/{pubmed,europe_pmc,wipo,epo,uspto}_queries.yaml). The 6 suffix
templates (patent/trial/activity/cytotoxicity/xenograft/IC50) are generated
for PubMed, Europe PMC, AND USPTO -- but NOT WIPO/EPO. This is a real,
verified distinction, not an arbitrary one: USPTO's own free-text `q=`
search (jobs/uspto/client.py, verified live) covers the FULL specification
content of an application, not just title/abstract, so experimental-data
language like "xenograft"/"IC50" genuinely can appear in what USPTO
searches. WIPO/EPO's OPS biblio search is restricted to title/abstract
only -- that full-specification text (where such language actually lives)
is what Job 13 already acquires separately for these same publications --
so appending those suffix words to a WIPO/EPO title/abstract query would
search for text that structurally isn't there. WIPO/EPO instead get every
bare identifier (name + every alias + every dev code); USPTO gets BOTH the
bare identifiers AND the 6 suffixes.
ClinicalTrials.gov (Job 03) is NOT driven through a generated query
registry at all -- it already has a purpose-built `--intervention "<name>"`
lookup (Prompt.md section 10.B, built during Job 03 specifically "for the
Job 15 asset expansion" per its own module docstring), called once per
asset identifier; its corpus already IS trials, so a "trial" suffix would
be redundant, and patent/activity/cytotoxicity/xenograft/IC50 don't map
onto its query.intr field. Crossref (Job 04) is deliberately NOT a target:
its own module docstring already established, verified live, that free-
text search is relevance-ranked and unusable for precise discovery --
nothing about this job changes that.

ISOLATION FROM THE BROAD-DISCOVERY PASS (both self-caught before this job
was ever run for real, or fixed on review): calling the SAME job classes
the broad-discovery pass uses (sharing their checkpoint files AND their
report.md files) risks corrupting two things that must stay tied to the
BROAD pass, not this one:

1. RESUME CURSOR -- Jobs 01/02/03/08/09/10 each end their own run() by
   unconditionally writing `checkpoint["last_success_max_date"]`, which
   gates that job's OWN `--resume` behavior on its NEXT invocation. Naively
   invoking them here would silently advance the BROAD pass's resume
   cursor forward to whatever date THIS job happened to run on, even
   though only the asset-expansion queries actually ran that day -- a
   subsequent `python -m adc_acquisition pubmed --resume` would then
   silently skip any real newly-published article matching the BROAD
   topic queries in between.
2. HUMAN-READABLE REPORT -- each of those jobs unconditionally overwrites
   its own `reports/acquisition/<name>.md` at the end of every run() with
   whatever ITS OWN run just did. Since an asset-expansion invocation only
   knows about the asset-expansion queries, it would silently overwrite
   that report's account of the BROAD pass's own discovery (query
   counts, sample records, coverage notes) with an unrelated, much
   narrower asset-expansion-only view -- Prompt.md's "do not conflate the
   two passes" applies to the REPORTING surface just as much as to the
   acquisition mechanism, even though the underlying manifest/checkpoint
   sharing is correct and intentional.

`_invoke_isolated()` fixes both, EXCEPTION-SAFE (a `finally` block, not
just code that happens to run after a successful call -- a sub-job
exception must still propagate to the caller, but must not skip
restoration): it snapshots each sub-job's `last_success_max_date` and its
`report.md` contents (or absence) before the call, lets the sub-job run
normally (per-record content-hash/version checkpoint state, and every
content/discovery/attempts manifest, is left FULLY shared -- a record
discovered by both an asset-expansion query and the broad query family
must still only be fetched/versioned once, and that sharing is what makes
"skipped_unchanged" work correctly across passes), then restores exactly
those two things -- nothing else -- regardless of whether the call
succeeded or raised. This job also never passes `resume=True` through to
a sub-job call in the first place -- its own `--resume` is documented as a
no-op (see below), the restore is defense-in-depth, not the only
safeguard. Full per-record provenance for what THIS pass discovered always
remains available in each source's OWN `*_discovery.parquet`/
`*_attempts.parquet` (every row there is tagged with its own
asset-expansion `query_id`) -- that, not the human-readable report, is the
audit trail for "why is this record in our corpus."

`--resume` is a no-op beyond default behavior: this job always considers
the FULL active asset registry every run (no cursor narrows which assets
get expanded), the same reasoning as Crossref/Job 13/Job 14. `--since`/
`--until` DO pass through to every sub-job call, narrowing each one's own
date-filtered discovery exactly as if that flag had been passed directly
to it. `--limit` also passes through to every sub-job call independently
(it caps EACH sub-invocation's own materialization scope, not a single
combined total across all of them) -- documented, not a silent surprise.
`--sources` is validated against a fixed allowed set -- an unrecognized
value (typo, stray whitespace) raises immediately rather than silently
running a subset smaller than requested while still reporting overall
success.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from jobs.clinicaltrials.job import ClinicalTrialsJob
from jobs.epo.job import EPOJob
from jobs.europe_pmc.job import EuropePMCJob
from jobs.known_adc_asset_expansion.asset_registry import active_assets, load_known_adc_assets
from jobs.known_adc_asset_expansion.query_templates import (
    epo_queries,
    europe_pmc_queries,
    pubmed_queries,
    uspto_queries,
    wipo_queries,
)
from jobs.known_adc_asset_expansion.report import build_report
from jobs.pubmed.job import PubMedJob
from jobs.uspto.job import USPTOJob
from jobs.wipo.job import WIPOJob

ASSETS_PATH = Path("configs") / "known_adc_assets.yaml"

# Each entry: (source label, job class, query-generator function). Order
# matches Prompt.md's own recommended-order framing (literature first,
# then patents) but has no functional significance -- every sub-job call is
# independent (Prompt.md: "Execute those searches independently").
QUERY_DRIVEN_SOURCES = [
    ("pubmed", PubMedJob, pubmed_queries),
    ("europe_pmc", EuropePMCJob, europe_pmc_queries),
    ("wipo", WIPOJob, wipo_queries),
    ("epo", EPOJob, epo_queries),
    ("uspto", USPTOJob, uspto_queries),
]

ALLOWED_SOURCES = {name for name, _cls, _fn in QUERY_DRIVEN_SOURCES} | {"clinicaltrials"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_queries_yaml(path: Path, queries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"queries": queries}, f, sort_keys=False, allow_unicode=True)


def _report_path_for(job_name: str, output_dir: Path) -> Path:
    return output_dir.parent / "reports" / "acquisition" / f"{job_name}.md"


def _invoke_isolated(job_cls, args: argparse.Namespace, output_dir: Path) -> JobRunResult:
    """Run job_cls().run(args), then restore that job's OWN
    last_success_max_date checkpoint field AND its OWN report.md to
    whatever they were before this call -- EXCEPTION-SAFE (a `finally`
    block): a sub-job exception must still propagate to the caller, but
    must not skip restoration, or the exact failure scenario this
    isolation exists for (a crash mid-run) would leave the broad pass's
    own cursor/report corrupted regardless. See module docstring's
    "ISOLATION FROM THE BROAD-DISCOVERY PASS" section for why this
    matters. Per-record content-hash/version checkpoint state (namespaces
    "records"/"raw_records") and every content/discovery/attempts
    manifest are left fully alone -- sharing those IS correct and
    intended."""
    checkpoint_store = CheckpointStore(job_cls.name, output_dir)
    checkpoint_before = checkpoint_store.load()
    had_cursor = "last_success_max_date" in checkpoint_before
    prior_cursor = checkpoint_before.get("last_success_max_date")

    report_path = _report_path_for(job_cls.name, output_dir)
    prior_report = report_path.read_text(encoding="utf-8") if report_path.exists() else None

    try:
        return job_cls().run(args)
    finally:
        checkpoint = checkpoint_store.load()
        if had_cursor:
            checkpoint["last_success_max_date"] = prior_cursor
        else:
            checkpoint.pop("last_success_max_date", None)
        checkpoint_store.save(checkpoint)

        if prior_report is not None:
            report_path.write_text(prior_report, encoding="utf-8")
        elif report_path.exists():
            report_path.unlink()


def _sub_args(output_dir: Path, dry_run: bool, limit: int | None, since: str | None, until: str | None, **extra) -> argparse.Namespace:
    return argparse.Namespace(
        dry_run=dry_run, limit=limit, resume=False, since=since, until=until, output=str(output_dir), **extra,
    )


class KnownADCAssetExpansionJob(AcquisitionJob):
    name = "known_adc_asset_expansion"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--assets-file", type=str, default=str(ASSETS_PATH),
            help="Path to the known-ADC asset registry YAML.",
        )
        parser.add_argument(
            "--generated-queries-dir", type=str, default=None,
            help="Directory to write this run's generated per-source query registries to "
            "(default: <output>/generated_queries).",
        )
        parser.add_argument(
            "--sources", type=str, default=None,
            help=f"Comma-separated subset of {sorted(ALLOWED_SOURCES)} to run against this run "
            "(default: all).",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        assets = active_assets(load_known_adc_assets(Path(args.assets_file)))
        if not assets:
            raise RuntimeError(f"no active assets in {args.assets_file}")

        if args.sources:
            requested = {s.strip() for s in args.sources.split(",") if s.strip()}
            unknown = requested - ALLOWED_SOURCES
            if unknown:
                raise ValueError(
                    f"unknown --sources value(s): {sorted(unknown)} (allowed: {sorted(ALLOWED_SOURCES)})"
                )
            sources = requested
        else:
            sources = set(ALLOWED_SOURCES)
        generated_dir = Path(args.generated_queries_dir) if args.generated_queries_dir else output_dir / "generated_queries"

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: this job always considers the full "
                "active asset registry every run (no cursor narrows which assets get expanded)."
            )

        per_source_results: dict[str, JobRunResult] = {}
        per_source_query_counts: dict[str, int] = {}

        for source_name, job_cls, query_fn in QUERY_DRIVEN_SOURCES:
            if source_name not in sources:
                continue
            queries = query_fn(assets)
            per_source_query_counts[source_name] = len(queries)
            queries_path = generated_dir / f"{source_name}_asset_expansion_queries.yaml"
            _write_queries_yaml(queries_path, queries)
            sub_args = _sub_args(
                output_dir, bool(args.dry_run), args.limit, args.since, args.until,
                queries_file=str(queries_path), refresh=False,
            )
            per_source_results[source_name] = _invoke_isolated(job_cls, sub_args, output_dir)

        if "clinicaltrials" in sources:
            identifiers = [(asset.asset_id, identifier) for asset in assets for identifier in asset.identifiers()]
            per_source_query_counts["clinicaltrials"] = len(identifiers)
            ctgov_result = JobRunResult(job_name="clinicaltrials", dry_run=bool(args.dry_run))
            for _asset_id, identifier in identifiers:
                sub_args = _sub_args(
                    output_dir, bool(args.dry_run), args.limit, args.since, args.until,
                    intervention=identifier, queries_file=None,
                )
                sub_result = _invoke_isolated(ClinicalTrialsJob, sub_args, output_dir)
                ctgov_result.queries_run += sub_result.queries_run
                ctgov_result.records_discovered += sub_result.records_discovered
                ctgov_result.records_downloaded += sub_result.records_downloaded
                ctgov_result.records_skipped_unchanged += sub_result.records_skipped_unchanged
                ctgov_result.records_failed += sub_result.records_failed
            per_source_results["clinicaltrials"] = ctgov_result

        for source_name, sub_result in per_source_results.items():
            result.queries_run += sub_result.queries_run
            result.records_discovered += sub_result.records_discovered
            result.records_downloaded += sub_result.records_downloaded
            result.records_skipped_unchanged += sub_result.records_skipped_unchanged
            result.records_failed += sub_result.records_failed
            result.notes.append(
                f"{source_name}: {per_source_query_counts.get(source_name, 0)} queries generated, "
                f"{sub_result.records_discovered} discovered, {sub_result.records_downloaded} downloaded, "
                f"{sub_result.records_skipped_unchanged} skipped_unchanged, {sub_result.records_failed} failed."
            )

        if args.dry_run:
            return result

        report_path = output_dir.parent / "reports" / "acquisition" / "known_adc_asset_expansion.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(assets, per_source_query_counts, per_source_results),
            encoding="utf-8",
        )
        return result
