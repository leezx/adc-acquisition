"""Per-source execution report (Prompt.md sections 10 and 26)."""

from __future__ import annotations

from collections import Counter

import pandas as pd

from adc_acquisition.job_base import JobRunResult
from adc_acquisition.query_registry import QuerySpec


def build_report(
    result: JobRunResult,
    manifest_df: pd.DataFrame,
    queries: list[QuerySpec],
    query_id_counts: Counter,
    unique_ids: set[str],
    duplicate_ids: set[str],
    since: str | None = None,
    until: str | None = None,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(unique_ids)] if not manifest_df.empty else manifest_df

    with_phase = int(run_df["phases"].apply(lambda p: p is not None and len(p) > 0).sum()) if not run_df.empty else 0
    with_enrollment = int(run_df["enrollment"].notna().sum()) if not run_df.empty else 0
    status_counts = run_df["overall_status"].value_counts().to_dict() if not run_df.empty else {}

    missing_fields = []
    for col in ["brief_title", "official_title", "overall_status", "start_date"]:
        if col in run_df.columns:
            missing = int(run_df[col].isna().sum())
            if missing:
                missing_fields.append(f"{col} missing in {missing}/{len(run_df)} records")

    queries_used = "\n".join(f"- `{q.query_id}` (v{q.query_version}): `{q.query_text}` — {q.purpose}" for q in queries)
    records_per_query = "\n".join(f"- {qid}: {count}" for qid, count in sorted(query_id_counts.items()))
    status_summary = ", ".join(f"{status}: {count}" for status, count in sorted(status_counts.items())) or "n/a"

    return f"""# ClinicalTrials.gov (Job 03)

## Acquisition mechanism

ClinicalTrials.gov API v2 (`GET /studies`), official REST API. No scraping, no API key required.

## Official endpoint / API / dataset

https://clinicaltrials.gov/api/v2/studies — https://clinicaltrials.gov/data-api/api

## Queries used

{queries_used}

## Date coverage

since={since or "(no lower bound)"}, until={until or "(no upper bound)"} (filtered via `AREA[LastUpdatePostDate]RANGE[...]` when set)

## Records discovered

{sum(query_id_counts.values())} query-hits across {len(queries)} active queries; {len(unique_ids)} unique NCT IDs.

## Records downloaded

{result.records_downloaded} new/changed trial snapshots, {result.records_skipped_unchanged} skipped as unchanged (matched checkpoint content hash).

## Duplicates

{len(duplicate_ids)} NCT IDs were discovered by more than one query. As with PubMed/Europe PMC, the content manifest attributes one primary query_id per record; the full multi-query history lives in `clinicaltrials_discovery.parquet`.

### Records per query

{records_per_query}

## Missing fields

{chr(10).join(f"- {m}" for m in missing_fields) if missing_fields else "- none observed in this run"}

- records with at least one phase recorded: {with_phase}
- records with enrollment count: {with_enrollment}
- overall status distribution: {status_summary}

## Failed downloads

{result.records_failed} ({'see DATA/logs/clinicaltrials_failures.log and clinicaltrials_attempts.parquet (status=failed)' if result.records_failed else 'none'}). Failed attempts never occupy a content-manifest version slot.

## Rate/access limitations

No API key or authentication required. No officially published numeric rate limit; ~50 req/min (~0.83 req/s) is the figure commonly cited by third-party users, so this job uses 0.7 req/s to stay under it.

## Data quality observations

- Unlike PubMed/Europe PMC, ClinicalTrials.gov's search endpoint returns each trial's *complete* record inline (identification/status/sponsor/design/arms/outcomes/eligibility/contacts modules) — there is no separate "fetch full record" step, so the content-version snapshot is exactly the search-result JSON for that NCT ID.
- ClinicalTrials.gov's search engine (Essie) tokenizes on hyphens, so hyphenated and unhyphenated phrase forms return identical hit counts — confirmed live, one query form covers both (see `configs/clinicaltrials_queries.yaml`).
- No decision is made here about whether `drug = ADC`, `trial = relevant`, or `trial status = final asset status` (Prompt.md section 10) — those are downstream decisions.

## Known coverage gaps

- Query family covers phrase/abbreviation/immunoconjugate forms plus one intervention-name-restricted query; same terminology-coverage caveat as other literature/registry jobs.
- Known-asset lookup (`--intervention "<name>"`, Prompt.md section 10.B) is implemented but not yet exercised as part of a systematic asset-expansion pass — that's Job 15.

## Reproduction command

```bash
python -m adc_acquisition clinicaltrials --limit {result.records_discovered or 20} --output DATA
```
"""
