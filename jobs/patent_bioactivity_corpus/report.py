"""Per-source execution report (Prompt.md sections 17 and 26)."""

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
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["upstream_source", "publication_number", "artifact_type"])
        sample_rows = "\n".join(
            f"- [{row['upstream_source']}] {row['publication_number']} ({row['artifact_type']}, version {row['version']})"
            for _, row in sample.head(20).iterrows()
        )

    candidates_by_source_str = ", ".join(f"{source}: {count}" for source, count in candidates_by_source.items())
    authority_rows = "\n".join(
        f"- **{source}**: {candidates_by_source.get(source, 0)} candidate publications this run — "
        f"{outcome_counts.get((source, 'success'), 0)} success, "
        f"{outcome_counts.get((source, 'skipped_unchanged'), 0)} skipped_unchanged, "
        f"{outcome_counts.get((source, 'not_available'), 0)} not_available, "
        f"{outcome_counts.get((source, 'failed'), 0)} failed"
        for source in ("wipo", "epo")
    )

    total_outcomes = (
        result.records_downloaded + result.records_skipped_unchanged + not_available_this_run + result.records_failed
    )

    return f"""# Patent Bioactivity Evidence Corpus (Job 13)

## Acquisition mechanism

SECOND-PASS job — "should NOT search the entire patent universe again" (Prompt.md). Candidates are read directly from Job 08 (WIPO)'s `wipo.parquet` AND Job 10 (EPO)'s `epo.parquet` (latest version per publication_number only), not from a new OPS search. For each candidate publication, two independent artifacts are fetched via EPO OPS's full-text endpoints: `description` (specification body text, where Examples/Experimental/IC50/etc. sections actually live) and `claims`.

## Per-authority coverage this run (empirical, not assumed)

{authority_rows}

Round-1 fix: an earlier version of this job excluded WIPO candidates entirely, reasoning from a single 404'd WO publication that OPS full-text coverage was EP-only. EPO's own OPS documentation lists full-text availability for multiple authorities including WO — a single 404 only proves that one publication/artifact lacks full text, not that the whole authority is unsupported. WIPO candidates are now attempted exactly like EPO candidates; the numbers above are this run's actual, empirical result, not an assumption.

## Known scope limitation (disclosed, not silently narrowed)

**USPTO (Job 09) is NOT duplicated here.** USPTO's own already-acquired SPEC-type documents (`uspto_documents.parquet`) are the as-filed Specification PDF, already bundling description + claims + abstract for the original filing — exactly the raw evidence this job exists to acquire for WIPO/EPO, but which USPTO's own job already has.

## Materialization this run

{sum(candidates_by_source.values())} candidate publications ({candidates_by_source_str}), {result.records_discovered} candidate artifacts (2 per publication: description + claims). {len(fresh_ids)} never-attempted (fresh), {len(backlog_ids)} unresolved-retry (backlog, includes `not_available` 404s — retried every ordinary run, NOT treated as permanently terminal), {len(pending_recovery_ids)} pending recovery (raw durable but ledger stale), {len(fast_skip_ids)} already successful and skipped with no request.

**This run's outcomes:** {result.records_downloaded} success (newly downloaded), {result.records_skipped_unchanged} skipped_unchanged, {not_available_this_run} not_available, {result.records_failed} failed — {total_outcomes} total attempted/fast-skipped outcomes (must equal the sum of these four).

## Sample materialized artifacts

{sample_rows}

## Failed downloads

{result.records_failed} this run (see DATA/logs/patent_bioactivity_corpus_failures.log and patent_bioactivity_corpus_attempts.parquet, status=failed). Separately, `not_available` ({not_available_this_run} this run — OPS confirmed no full text exists) is NOT counted as a failure — it's a genuine negative result, still retried on every ordinary run since it's not assumed permanent.

## OPS quota note

EPO's OPS free tier has a 4GB/WEEK data quota across ALL OPS usage (not just this job) — full-text documents are far larger than biblio XML. See `result.notes` for this run's downloaded byte total.

## Reproduction command

```bash
python -m adc_acquisition patent_bioactivity_corpus --output DATA
```
"""
