"""Per-source execution report (source-coverage expansion, WHO ICTRP)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _overlap_with_clinicaltrials_job(all_ids: list, source_register_counts: dict, ctgov_manifest_path: Path) -> tuple[int, int, int]:
    """Returns (ctgov_sourced_in_export, already_in_our_own_job, ctgov_sourced_not_yet_in_our_own_job).
    A ClinicalTrials.gov-`Source_Register` trial's own TrialID IS the NCT
    number -- this is a direct provenance cross-check against Job 03's own
    manifest, not a guess, and demonstrates WHO ICTRP's real incremental
    value: every non-ClinicalTrials.gov `Source_Register` trial here is
    global-registry coverage Job 03 structurally cannot reach at all."""
    ctgov_sourced = len(all_ids) - sum(v for k, v in source_register_counts.items() if k != "ClinicalTrials.gov")
    if not ctgov_manifest_path.exists():
        return ctgov_sourced, 0, ctgov_sourced
    our_nct_ids = set(pd.read_parquet(ctgov_manifest_path, columns=["source_record_id"])["source_record_id"])
    overlap = sum(1 for tid in all_ids if tid in our_nct_ids)
    return ctgov_sourced, overlap, ctgov_sourced - overlap


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list,
    changed_ids: list,
    unchanged_ids: list,
    source_register_counts: dict,
    export_file_counts: dict,
    outcome_counts: dict,
    corpus_dir: Path,
    ctgov_manifest_path: Path,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["source_register", "source_record_id"])
        sample_rows = "\n".join(
            f"- {row['source_register']} {row['source_record_id']} (version {row['version']}): {row['title'][:100]}"
            for _, row in sample.head(20).iterrows()
        )

    non_ctgov_count = len(all_ids) - source_register_counts.get("ClinicalTrials.gov", 0)
    register_lines = "\n".join(
        f"- {register}: {count}" for register, count in sorted(source_register_counts.items(), key=lambda kv: -kv[1])
    )
    ctgov_sourced, overlap, ctgov_not_yet_ours = _overlap_with_clinicaltrials_job(all_ids, source_register_counts, ctgov_manifest_path)

    return f"""# WHO ICTRP (source-coverage expansion)

## Acquisition mechanism

NOT a live query against WHO ICTRP -- this job reads a MANUALLY exported
`ICTRP-Results-YYYYMMDD.xml` file (WHO's own Search Portal "Export results
to XML" button, https://trialsearch.who.int/) dropped into `--corpus-dir`.
Real, automated/scheduled ("crawling") access to WHO ICTRP requires WHO-
issued credentials (email ictrpinfo@who.int) -- until that access exists,
this job makes zero network requests to WHO. See this job's own module
docstring for the full access-model writeup and
`configs/who_ictrp_queries.yaml` for the EXACT search terms/filters used
to produce the export file(s) this run read (verbatim, supplied by the
human who ran the search -- this job cannot re-derive it).

Corpus dir this run: `{corpus_dir}` ({export_file_counts.get('files', 0)} export file(s) read).

## Why this source: real, measured global-registry coverage this run

Of {len(all_ids)} distinct trials in the export(s):

{register_lines}

**{non_ctgov_count} of {len(all_ids)} trials ({non_ctgov_count / len(all_ids) * 100:.0f}%) come from a
`Source_Register` OTHER than ClinicalTrials.gov** -- genuinely new global
trial coverage Job 03 (ClinicalTrials.gov) structurally cannot reach on
its own, this repo's exact motivating case for adding this source.

Of the {ctgov_sourced} ClinicalTrials.gov-sourced trials in this export
(TrialID == NCT number for these), {overlap} are ALREADY in our own Job 03
`clinicaltrials.parquet` (expected/healthy overlap, not double-counted as
new source coverage), and {ctgov_not_yet_ours} are NOT yet in our own Job
03 manifest -- worth investigating as a possible Job 03 recall gap in a
future round, not this job's own scope.

## Known, disclosed limitations (not silently narrowed)

**Manual export, not live/scheduled acquisition.** This job's own
`--since`/`--until`/`--resume` flags are no-ops beyond default behavior --
"freshness" is entirely a function of how recently a human re-ran the
export, not this job's own cadence. See module docstring for the interim-
access-model rationale.

**`other_records` is a flag, not a resolved cross-reference.** WHO ICTRP
marks a trial `other_records=Yes` when it believes a linked/duplicate
registration exists in another registry, but the export does not carry
that OTHER registry's own TrialID -- this job cannot deduplicate across
those linked registrations, only record the flag as-is (materialized in
the `other_records` column).

**No target/payload/linker/candidate extraction from this source yet**
(same acquisition/extraction boundary every other job in this repo draws
first) -- deferred to a follow-up increment, once this job's own
materialization is reviewed and stable.

## Materialization this run

{len(all_ids)} unique candidate trials (deduplicated by WHO ICTRP's own
cross-registry TrialID; a trial appearing in more than one dated export
file keeps the MOST RECENTLY DATED file's version). {len(changed_ids)}
new-or-changed, {len(unchanged_ids)} unchanged this run.

**This run's outcomes:** {result.records_downloaded} success (newly materialized),
{result.records_skipped_unchanged} skipped_unchanged -- {result.records_downloaded + result.records_skipped_unchanged} total
attempted/fast-skipped outcomes (must equal the sum of these two; this job
has no network fetch step, so there is no `failed`/`not_available` outcome
class the way network-dependent jobs have).

## Sample materialized trials

{sample_rows}

## Reproduction command

```bash
python -m adc_acquisition who_ictrp --corpus-dir DATA/raw/WHO_ICTRP --output DATA
```
"""
