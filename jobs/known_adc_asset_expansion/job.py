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
08 (WIPO), and 10 (EPO) IN-PROCESS with those queries. Every discovered/
materialized record lands in THOSE jobs' own manifests
(pubmed.parquet, europe_pmc.parquet, clinicaltrials.parquet, wipo.parquet,
epo.parquet), tagged with its own asset-expansion query_id for full
provenance (Prompt.md section 20). Building a SEPARATE, redundant
acquisition/materialization pipeline here would duplicate content-hash
versioning, checkpointing, and rate-limiting logic those 5 jobs already
have fully hardened -- the same "don't re-acquire what an existing job
already legitimately does" discipline Job 13 (USPTO) and Job 14 (Europe
PMC) already established, taken to its natural conclusion: the existing
per-source JOBS are the acquisition mechanism, not a new client this job
would have to build and independently harden.

QUERY TRANSLATION PER SOURCE (jobs/known_adc_asset_expansion/query_templates.py):
Prompt.md's 8 templates are each source's OWN query syntax, not literal
English text passed through unchanged (same translation this repo already
does for the broad discovery query family across
configs/{pubmed,europe_pmc,wipo,epo}_queries.yaml). The 6 suffix templates
(patent/trial/activity/cytotoxicity/xenograft/IC50) are generated ONLY for
PubMed and Europe PMC -- disclosed, not silently narrowed: WIPO/EPO's
searchable fields (OPS biblio's title/abstract) essentially never contain
experimental-data language like "xenograft"/"IC50" (that lives in the full
specification text, which Job 13 already acquires separately for these
same publications), so appending those words to a title/abstract query
would search for text that structurally isn't there. WIPO/EPO instead get
every bare identifier (name + every alias + every dev code).
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

RESUME-CURSOR ISOLATION (self-caught before this job was ever run for
real): Jobs 01/02/03/08/10 each end their own run() by unconditionally
writing `checkpoint["last_success_max_date"] = args.until or now`, which
gates that job's OWN `--resume` behavior on its NEXT invocation. Since this
job calls those SAME job classes (sharing the SAME per-source checkpoint
file), naively invoking them would silently advance the BROAD discovery
pass's resume cursor forward to whatever date this job happened to run on
-- even though only the asset-expansion queries actually ran that day. A
subsequent plain `python -m adc_acquisition pubmed --resume` would then
start from that date, silently skipping any real newly-published article
matching the BROAD topic queries in between. Fixed with
`_invoke_preserving_resume_cursor()`: snapshot each sub-job's
`last_success_max_date` before the call, let the sub-job run normally
(content-hash/version checkpoint state under the `records`/`raw_records`
namespaces is fully SHARED and SHOULD be -- a record discovered by both an
asset-expansion query and the broad query family must still only be
fetched/versioned once), then restore just that one field afterward. This
job also never passes `resume=True` through to a sub-job call in the first
place -- its own `--resume` is documented as a no-op (see below), the
restore is defense-in-depth, not the only safeguard.

`--resume` is a no-op beyond default behavior: this job always considers
the FULL active asset registry every run (no cursor narrows which assets
get expanded), the same reasoning as Crossref/Job 13/Job 14. `--since`/
`--until` DO pass through to every sub-job call, narrowing each one's own
date-filtered discovery exactly as if that flag had been passed directly
to it. `--limit` also passes through to every sub-job call independently
(it caps EACH sub-invocation's own materialization scope, not a single
combined total across all of them) -- documented, not a silent surprise.
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
from jobs.known_adc_asset_expansion.query_templates import epo_queries, europe_pmc_queries, pubmed_queries, wipo_queries
from jobs.known_adc_asset_expansion.report import build_report
from jobs.pubmed.job import PubMedJob
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
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_queries_yaml(path: Path, queries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"queries": queries}, f, sort_keys=False, allow_unicode=True)


def _invoke_preserving_resume_cursor(job_cls, args: argparse.Namespace, output_dir: Path) -> JobRunResult:
    """Run job_cls().run(args), then restore that job's OWN
    last_success_max_date checkpoint field to whatever it was before this
    call -- see module docstring's "RESUME-CURSOR ISOLATION" section for
    why this matters. Per-record content-hash/version checkpoint state
    (namespaces "records"/"raw_records") is left fully alone -- sharing
    that IS correct and intended."""
    checkpoint_store = CheckpointStore(job_cls.name, output_dir)
    prior_cursor = checkpoint_store.load().get("last_success_max_date")
    result = job_cls().run(args)
    checkpoint = checkpoint_store.load()
    checkpoint["last_success_max_date"] = prior_cursor
    checkpoint_store.save(checkpoint)
    return result


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
            help="Comma-separated subset of {pubmed,europe_pmc,wipo,epo,clinicaltrials} to run "
            "against this run (default: all five).",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        assets = active_assets(load_known_adc_assets(Path(args.assets_file)))
        if not assets:
            raise RuntimeError(f"no active assets in {args.assets_file}")

        sources = set(args.sources.split(",")) if args.sources else {"pubmed", "europe_pmc", "wipo", "epo", "clinicaltrials"}
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
            per_source_results[source_name] = _invoke_preserving_resume_cursor(job_cls, sub_args, output_dir)

        if "clinicaltrials" in sources:
            identifiers = [(asset.asset_id, identifier) for asset in assets for identifier in asset.identifiers()]
            per_source_query_counts["clinicaltrials"] = len(identifiers)
            ctgov_result = JobRunResult(job_name="clinicaltrials", dry_run=bool(args.dry_run))
            for _asset_id, identifier in identifiers:
                sub_args = _sub_args(
                    output_dir, bool(args.dry_run), args.limit, args.since, args.until,
                    intervention=identifier, queries_file=None,
                )
                sub_result = _invoke_preserving_resume_cursor(ClinicalTrialsJob, sub_args, output_dir)
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
