"""Per-source execution report (Prompt.md sections 11 and 26)."""

from __future__ import annotations

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list[str],
    fresh_ids: list[str],
    backlog_ids: list[str],
    reverify_ids: list[str],
    companies: list,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values("source_record_id")
        sample_rows = "\n".join(
            f"- {row['company']}: {row['title'] or 'n/a'} ({row['url']}, version {row['version']})"
            for _, row in sample.iterrows()
        )

    registry_rows = "\n".join(
        f"- {c.canonical_name} ({c.company_id}): {len(c.pipeline_urls)} registered pipeline_url(s)"
        for c in companies
    )

    return f"""# Company Pipeline Pages (Job 11)

## Acquisition mechanism

No official API exists for these pages — "fundamentally different from database APIs" (Prompt.md's own framing). Every (company, pipeline_url) pair processed this run comes directly from the curated `configs/company_registry.yaml` (shared with Job 05/SEC), not from a live search/discovery step. A company with no standalone pipeline page (e.g. Seagen/ImmunoGen/Mersana, all acquired/absorbed — see the registry's notes) simply has an empty `pipeline_urls` list.

## Registered companies this run

{registry_rows}

## Materialization this run

{result.records_discovered} registered (company, pipeline_url) pairs. {len(fresh_ids)} never-attempted (fresh), {len(backlog_ids)} unresolved-retry (backlog), {len(reverify_ids)} already-resolved reverify candidates. {result.records_downloaded} newly downloaded (new or changed content), {result.records_skipped_unchanged} unchanged, {result.records_failed} failed. Every pair is refetched and hash-compared every run (Prompt.md: "company pipeline pages change over time... snapshots are essential") — there is no skip-by-default the way Job 08/WIPO and Job 10/EPO have.

{sample_rows}

## Failed downloads

{result.records_failed} (see DATA/logs/company_pipeline_failures.log and company_pipeline_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run.

## Known access limitation

AbbVie's registered pipeline page (https://www.abbvie.com/science/pipeline.html) is behind an active Cloudflare JS challenge (HTTP 403, "Just a moment..." interstitial) — confirmed live 2026-08-14 that a descriptive User-Agent (the fix that resolved fda.gov's simpler bot detection) does NOT get past it. This repo does not attempt to defeat the challenge (Prompt.md prohibits CAPTCHA/bot-challenge bypassing) — every attempt is recorded as a normal, logged `failed` attempt, not silently dropped, until AbbVie offers an alternative official machine-readable route.

## Known coverage gaps

- Individual pipeline program entries (drug names, phases, indications) are NOT extracted from the page — only the raw page snapshot and its `<title>` tag are preserved. Program-level extraction is downstream knowledge extraction (Prompt.md section 1), not acquisition.
- Seagen, ImmunoGen, and Mersana have no standalone pipeline page of their own as of this run (all acquired/absorbed) — their former ADC assets appear only in their acquirers' own pipeline pages (Pfizer, AbbVie) or, for Mersana's Emi-Le, in Day One Biopharmaceuticals' pipeline (Day One is not yet a registered company in this file — a scope decision left for a future round).
- `--since`/`--until` are not applicable (a pipeline page has no natural publication/release date of its own).

## Reproduction command

```bash
python -m adc_acquisition company_pipeline --output DATA
```
"""
