"""Per-source execution report (Prompt.md sections 18 and 26)."""

from __future__ import annotations

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list,
    fresh_ids: list,
    backlog_ids: list,
    pending_recovery_ids: list,
    fast_skip_ids: list,
    candidates_by_source: dict,
    outcome_counts: dict,
    not_available_this_run: int,
    already_covered_count: int,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["doi"])
        sample_rows = "\n".join(
            f"- {row['doi']} (host_type={row['host_type']}, oa_status={row['oa_status']}, "
            f"upstream={row['upstream_sources']}, version {row['version']})"
            for _, row in sample.head(20).iterrows()
        )

    candidates_by_source_str = ", ".join(f"{source}: {count}" for source, count in candidates_by_source.items())
    total_outcomes = (
        result.records_downloaded + result.records_skipped_unchanged + not_available_this_run + result.records_failed
    )

    return f"""# Publication Bioactivity Evidence Corpus (Job 14)

## Acquisition mechanism

SECOND-PASS job -- Prompt.md's input is "PMIDs / PMCIDs / DOIs / known ADC aliases", not a new literature search. DOI candidates are read directly from Job 01 (PubMed)'s `pubmed.parquet`, Job 02 (Europe PMC)'s `europe_pmc.parquet`, and Job 04 (Crossref)'s `crossref.parquet` (latest version per record only), not from a new discovery query. For each candidate DOI: (1) an Unpaywall (https://unpaywall.org) lookup for OA status and locations; (2) a content fetch of the actual bytes, trying Unpaywall's ordered location list until one succeeds (a publisher landing page can block a bot while a repository mirror of the same work succeeds).

## Known scope limitation (disclosed, not silently narrowed)

**Job 02 (Europe PMC)'s own already-resolved full text is NOT duplicated here.** {already_covered_count} candidate DOI(s) this run were excluded because Europe PMC's own `europe_pmc_fulltext.parquet` already has a successfully materialized full-text artifact for them (joined via pmcid -> doi). This mirrors Job 13's USPTO exclusion: re-downloading the identical article's OA full text under a second table would be pure duplication of Job 02's own work. This count is empirical (checked against real data every run), not an assumption baked into candidate selection -- Unpaywall's coverage is NOT a strict subset of Europe PMC's OA subset (it also covers DOIs Job 02 never discovered, and DOIs where Europe PMC's own is_open_access flag is false/absent but a legal OA copy exists elsewhere), so every other candidate DOI is still attempted here.

## Candidate provenance this run

{candidates_by_source_str} (upstream mentions across Jobs 01/02/04; a DOI can appear in more than one, so these do not sum to the number of unique candidate DOIs).

## Materialization this run

{len(all_ids)} unique candidate DOIs (after excluding {already_covered_count} already covered by Job 02). {len(fresh_ids)} never-attempted (fresh), {len(backlog_ids)} unresolved-retry (backlog, includes `not_available` -- retried every ordinary run, NOT treated as permanently terminal), {len(pending_recovery_ids)} pending recovery (raw durable but ledger stale), {len(fast_skip_ids)} already successful and skipped with no request.

**This run's outcomes:** {result.records_downloaded} success (newly downloaded), {result.records_skipped_unchanged} skipped_unchanged, {not_available_this_run} not_available, {result.records_failed} failed -- {total_outcomes} total attempted/fast-skipped outcomes (must equal the sum of these four).

## Sample materialized artifacts

{sample_rows}

## Failed downloads

{result.records_failed} this run (see DATA/logs/publication_bioactivity_corpus_failures.log and publication_bioactivity_corpus_attempts.parquet, status=failed). Separately, `not_available` ({not_available_this_run} this run -- Unpaywall confirmed no OA copy exists, or the DOI is unknown to Unpaywall) is NOT counted as a failure -- it's a genuine negative result, still retried on every ordinary run since it's not assumed permanent.

## Reproduction command

```bash
python -m adc_acquisition publication_bioactivity_corpus --output DATA
```
"""
