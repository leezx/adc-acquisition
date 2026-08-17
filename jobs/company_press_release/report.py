"""Per-source execution report (Prompt.md sections 12 and 26)."""

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
    companies: list,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["company", "publication_or_release_date"], ascending=[True, False])
        sample_rows = "\n".join(
            f"- {row['company']}: {row['title'] or 'n/a'} ({row['publication_or_release_date'] or 'date unknown'}, "
            f"{row['url']}, version {row['version']})"
            for _, row in sample.head(20).iterrows()
        )

    registry_rows = "\n".join(
        f"- {c.canonical_name} ({c.company_id}): {c.press_release_url or 'no press_release_url registered'}"
        + (f" [{c.press_release_template}]" if c.press_release_template else "")
        for c in companies
    )

    return f"""# Company Press Releases (Job 12)

## Acquisition mechanism

No official API exists for any of these IR newsrooms — "fundamentally different from database APIs" (Prompt.md's own framing, same as Job 11). Every company's `press_release_url` (`configs/company_registry.yaml`, shared with Job 05/SEC and Job 11) is a curated LISTING page; the individual releases behind it are discovered by walking that listing's pagination, using a per-company `press_release_template` to select the correct parser (jobs/company_press_release/parser.py). Only releases whose own URL stays on the company's registered `official_domain` (or a subdomain of it) are accepted — "do not mix media reports into this source" (Prompt.md).

## Registered companies this run

{registry_rows}

## Materialization this run

{result.records_discovered} releases discovered across {result.queries_run} companies. {len(fresh_ids)} never-attempted (fresh), {len(backlog_ids)} unresolved-retry (backlog), {len(pending_recovery_ids)} pending recovery (raw durable but ledger stale), {len(fast_skip_ids)} already successful and skipped with no request. {result.records_downloaded} newly downloaded (new or changed content), {result.records_skipped_unchanged} unchanged, {result.records_failed} failed.

## Sample materialized releases (most recent 20 by company)

{sample_rows}

## Failed downloads

{result.records_failed} (see DATA/logs/company_press_release_failures.log and company_press_release_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run.

## Known access limitation

Zymeworks' registered press_release_url (ir.zymeworks.com/news-releases) is on a subdomain that is currently entirely unreachable (confirmed live 2026-08-17: a direct request with a descriptive User-Agent hangs to a read timeout, distinct from a bot-detection block) — every attempt is recorded as a normal, logged `failed` attempt, not silently dropped.

## Known coverage gaps

- Individual press-release BODY TEXT is not extracted — only the raw page snapshot and the listing page's own headline/date are preserved. Categorizing releases (clinical trial initiation, regulatory approval, licensing, etc. — Prompt.md's own list) is downstream knowledge extraction (Prompt.md section 1), not acquisition.
- AbbVie's and Pfizer's press-release feeds cover their ENTIRE newsroom (all therapeutic areas), not just ADC-relevant announcements — same "acquire broadly, filter downstream" caveat already documented for their pipeline pages (Job 11).
- Seagen, ImmunoGen, and Mersana have no standalone press-release feed of their own (all acquired/absorbed, `press_release_url: null`), same as their pipeline-page situation.

## Reproduction command

```bash
python -m adc_acquisition company_press_release --output DATA
```
"""
