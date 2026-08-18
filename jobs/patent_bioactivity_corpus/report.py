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
    candidate_publication_count: int,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["publication_number", "artifact_type"])
        sample_rows = "\n".join(
            f"- {row['publication_number']} ({row['artifact_type']}, version {row['version']})"
            for _, row in sample.head(20).iterrows()
        )

    return f"""# Patent Bioactivity Evidence Corpus (Job 13)

## Acquisition mechanism

SECOND-PASS job — "should NOT search the entire patent universe again" (Prompt.md). Candidates are read directly from Job 10 (EPO)'s already-materialized `epo.parquet` manifest (latest version per publication_number only), not from a new OPS search. For each EP publication, two independent artifacts are fetched via EPO OPS's full-text endpoints: `description` (specification body text, where Examples/Experimental/IC50/etc. sections actually live) and `claims`.

## Known scope limitation (disclosed, not silently narrowed)

**WIPO (Job 08)'s WO-prefixed candidates are NOT processed by this job.** Live-verified 2026-08-19: EPO OPS's full-text retrieval is EP-only — a real WO publication (confirmed to exist via live search, biblio succeeds) returns HTTP 404 on description/claims/fulltext. This is a hard OPS data-coverage limitation, not a rate/access issue. WO-only patent families currently have no full text available through any legitimate machine-readable channel this repo uses.

**USPTO (Job 09) is NOT duplicated here.** USPTO's own already-acquired SPEC-type documents (`uspto_documents.parquet`) are the as-filed Specification PDF, already bundling description + claims + abstract for the original filing — exactly the raw evidence this job exists to acquire for EPO, but which USPTO's own job already has.

## Materialization this run

{candidate_publication_count} EP publication candidates ({result.records_discovered} candidate artifacts, 2 per publication: description + claims). {len(fresh_ids)} never-attempted (fresh), {len(backlog_ids)} unresolved-retry (backlog, includes `not_available` 404s — retried every ordinary run, NOT treated as permanently terminal), {len(pending_recovery_ids)} pending recovery (raw durable but ledger stale), {len(fast_skip_ids)} already successful and skipped with no request. {result.records_downloaded} newly downloaded (new or changed content), {result.records_skipped_unchanged} unchanged, {result.records_failed} failed.

## Sample materialized artifacts

{sample_rows}

## Failed downloads

{result.records_failed} (see DATA/logs/patent_bioactivity_corpus_failures.log and patent_bioactivity_corpus_attempts.parquet, status=failed). Separately, `not_available` (OPS confirmed no full text exists for this specific publication/artifact) is NOT counted as a failure — it's a genuine negative result, still retried on every ordinary run since it's not assumed permanent.

## OPS quota note

EPO's OPS free tier has a 4GB/month data quota across ALL OPS usage (not just this job) — full-text documents are far larger than biblio XML. See `result.notes` for this run's downloaded byte total.

## Reproduction command

```bash
python -m adc_acquisition patent_bioactivity_corpus --output DATA
```
"""
