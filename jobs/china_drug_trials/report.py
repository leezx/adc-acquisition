"""Per-source execution report (source-coverage expansion, China CDE)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _overlap_with_existing_sources(all_ids: list, output_dir: Path) -> dict[str, int]:
    """CDE registration numbers (e.g. "CTR20262727") live in a completely
    different ID namespace from ClinicalTrials.gov's NCT numbers and WHO
    ICTRP's own cross-registry TrialIDs (which for a ChiCTR-sourced trial
    look like "ChiCTR2600000001", a DIFFERENT Chinese registry from CDE's
    own chinadrugtrials.org.cn -- see this job's module docstring). This
    check is a direct measurement of that claim, not an assumption: it
    counts how many of this run's registration numbers happen to also
    appear as a source_record_id in either existing manifest -- expected
    to be ~0.

    IMPORTANT SCOPE LIMIT (reviewer-flagged, round-1 fix): this is an
    ID-NAMESPACE overlap diagnostic, NOT an ADC-asset novelty measurement.
    Zero source_record_id overlap only proves this run acquired records
    from a registry namespace this repo didn't already have a
    source_record_id for -- it says nothing about whether any given
    record's underlying DRUG is a genuinely new ADC asset (that requires
    a real identity crosswalk against DATA/catalog/adc_asset_universe.tsv
    by canonical name/alias/dev-code, deliberately not attempted here).
    A record can score 0 ID overlap while describing an ADC this repo
    already tracks under a different identifier (e.g. Loncastuximab
    tesirine is already known via ADC Therapeutics's own registered
    entries) -- this function cannot and does not distinguish that case."""
    overlaps = {}
    for other_source in ("clinicaltrials", "who_ictrp"):
        path = output_dir / "manifests" / f"{other_source}.parquet"
        if not path.exists():
            overlaps[other_source] = -1  # sentinel: not yet run, not "0 overlap"
            continue
        other_ids = set(pd.read_parquet(path, columns=["source_record_id"])["source_record_id"])
        overlaps[other_source] = sum(1 for rid in all_ids if rid in other_ids)
    return overlaps


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list,
    changed_ids: list,
    unchanged_ids: list,
    export_file_counts: dict,
    outcome_counts: dict,
    corpus_dir: Path,
    output_dir: Path,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    query_breakdown = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["source_record_id"])
        sample_rows = "\n".join(
            f"- {row['source_record_id']} ({row['trial_status']}, query={row['query_id']}): "
            f"{row['drug_name']} -- {row['title'][:80] if row['title'] else '(no title)'}"
            for _, row in sample.head(20).iterrows()
        )
        query_counts = run_df.groupby("query_id").size().sort_values(ascending=False)
        query_breakdown = "\n".join(f"- {qid}: {count}" for qid, count in query_counts.items())

    overlaps = _overlap_with_existing_sources(all_ids, output_dir)

    def _overlap_line(source_name: str) -> str:
        n = overlaps[source_name]
        if n == -1:
            return f"- {source_name}: not yet run in this environment, comparison skipped"
        return f"- {source_name}: {n} of {len(all_ids)} registration numbers also appear there"

    return f"""# China CDE / chinadrugtrials.org.cn (source-coverage expansion)

## Acquisition mechanism

NOT a live query against chinadrugtrials.org.cn -- this job reads a
MANUALLY downloaded search-results export file (the results page's own
"下载" button) dropped into `--corpus-dir`. AUTOMATION PERMISSION STATUS
for this domain is UNKNOWN (no robots.txt exists; the platform's own
Disclaimer page could not be read from this environment) -- until that is
resolved, this job makes zero network requests to chinadrugtrials.org.cn.
See this job's own module docstring for the full access-model writeup and
`configs/china_drug_trials_queries.yaml` for the EXACT search terms used
to produce each export file this run read (verbatim, supplied by the
human who ran each search).

Corpus dir this run: `{corpus_dir}` ({export_file_counts.get('files', 0)} export file(s) read).

## Records by query

{query_breakdown}

**Disclosed finding -- neither query is confirmed precise**: the bare
"ADC" query matches an internal drug-code numbering prefix used for
unrelated products ("ADC189"/"ADC118"/"ADC308" -- an influenza antiviral,
an HIV drug, an endometriosis drug) and the unrelated "AADC" acronym
(expected). More surprisingly, the TARGETED "抗体药物偶联物" query ALSO
returned results with no plausible ADC connection at all (ethambutol, an
anti-tuberculosis drug; an HIV combination pill) -- not explainable by
acronym ambiguity, suggesting the site's search matches a field not
visible in list-page columns (likely a protocol/reference number, not
drug content). Both queries' full result sets are kept as-is under this
repo's "acquire broadly, filter downstream" principle -- see
`configs/china_drug_trials_queries.yaml`'s own file-level comment for the
full writeup and a recommended improved search strategy for a future
round (known ADC asset names/development codes and known ADC company/
applicant names, rather than a single broad term).

## Registry-ID namespace overlap diagnostic (NOT an asset-novelty metric)

{len(all_ids)} new China-CDE registry records acquired from a previously
uncovered registry namespace this run:

{_overlap_line('clinicaltrials')}
{_overlap_line('who_ictrp')}

Near-zero overlap is EXPECTED: CDE's registration numbers live in a
completely different ID namespace from ClinicalTrials.gov's NCT numbers
and WHO ICTRP's own cross-registry TrialIDs (a ChiCTR-sourced WHO ICTRP
trial is a DIFFERENT Chinese registry from CDE's own mandatory drug-trial
disclosure platform) -- any nonzero overlap here would itself be a
surprising finding worth investigating, not routine double-counting.
**This measures registry-ID coverage only** -- it does NOT establish that
any given record's underlying drug is a genuinely new ADC asset (that
would require a real identity crosswalk against
`DATA/catalog/adc_asset_universe.tsv`, not attempted here; see
`_overlap_with_existing_sources`'s own docstring). ADC-relevant records
observed in this run's export include RC48-ADC, F0002-ADC, loncastuximab
tesirine, ATG-022, STI-6129, and SSGJ-612 -- reported as observed content,
not asserted as novel assets.

## Known, disclosed limitations (not silently narrowed)

**Manual export, not live/scheduled acquisition.** This job's own
`--since`/`--until`/`--resume` flags are no-ops beyond default behavior --
"freshness" is entirely a function of how recently a human re-ran the
download, not this job's own cadence. See module docstring for the
interim-access-model rationale.

**List-only fields, no detail-page data this round.** The search-results
export gives only 6 columns (registration_number, trial_status, drug_name,
indication, public_title) -- applicant/sponsor, phase, enrollment, and a
stable per-trial detail URL all live only on the detail page, which this
acquisition-only round does not fetch (see module docstring). A follow-up
increment can add detail-page materialization keyed off the SAME
registration_number identity established here.

**No target/payload/linker/candidate extraction from this source yet**
(same acquisition/extraction boundary every other job in this repo draws
first) -- deferred to a follow-up increment, once this job's own
materialization is reviewed and stable.

## Materialization this run

{len(all_ids)} unique candidate trials (deduplicated by CDE's own
registration_number; a registration number appearing in more than one
downloaded export keeps the MOST RECENTLY DATED file's version).
{len(changed_ids)} new-or-changed, {len(unchanged_ids)} unchanged this run.

**This run's outcomes:** {result.records_downloaded} success (newly materialized),
{result.records_skipped_unchanged} skipped_unchanged -- {result.records_downloaded + result.records_skipped_unchanged} total
attempted/fast-skipped outcomes (must equal the sum of these two; this job
has no network fetch step, so there is no `failed`/`not_available` outcome
class the way network-dependent jobs have).

## Sample materialized trials

{sample_rows}

## Reproduction command

```bash
python -m adc_acquisition china_drug_trials --corpus-dir DATA/raw/chinadrugtrials --output DATA
```
"""
