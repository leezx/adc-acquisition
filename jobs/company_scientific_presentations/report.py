"""Per-source execution report (BREADTH_PLAN.md Phase 5 Part 7)."""

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
    discovery_failures: list | None = None,
) -> str:
    discovery_failures = discovery_failures or []
    discovery_failure_rows = "\n".join(
        f"- {f['company_id']}: {f['reason']} -- {f['detail']}" for f in discovery_failures
    ) or "None this run."
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["company", "congress"], ascending=[True, False])
        sample_rows = "\n".join(
            f"- {row['company']}: {row['title'] or 'n/a'} "
            f"({row['congress'] or row['publication_or_release_date'] or 'date unknown'}, {row['url']}, version {row['version']})"
            for _, row in sample.head(20).iterrows()
        )

    registry_rows = "\n".join(
        f"- {c.canonical_name} ({c.company_id}): {c.presentations_url or 'no presentations_url registered'}"
        + (f" [{c.presentations_template}]" if c.presentations_template else "")
        for c in companies
    )

    return f"""# Company Scientific Presentations (BREADTH_PLAN.md Phase 5 Part 7)

## Acquisition mechanism

Distinct from Job 12 (company press releases): an IR newsroom announces corporate news, but a company's ACTUAL scientific congress presentations/posters (AACR/ASCO/ESMO/ASH/etc.) often live on a separate page -- sometimes a genuinely different domain (see `configs/company_registry.yaml`'s note on ADC Therapeutics' adctmedical.com microsite). Only companies with a real, live-verified scrapable listing are registered here -- not attempted for every company (see "Companies checked but not registered" below). Each company's `presentations_url` is discovered by walking its listing's pagination (or fetching once, for a "single_page" template), using a per-company `presentations_template` to select the correct parser (`jobs/company_scientific_presentations/parser.py`). Only items whose own URL stays on `presentations_url`'s OWN domain (never the company's generic `official_domain` -- see module docstring for why) are accepted.

## Registered companies this run

{registry_rows}

## Companies checked but not registered (live-verified 2026-08-24, disclosed not attempted)

- **AbbVie**: main domain (abbvie.com) is behind the same Cloudflare JS challenge already documented for its pipeline page; no separate public scientific-presentations microsite found.
- **Pfizer**: no distinct presentations archive found; `pfizer.com/news/press-kits/oncology` only has stale 2018-2020 blog-post assets, not real congress presentation content.
- **Seagen, ImmunoGen, Mersana**: acquired/absorbed, domains redirect to their respective acquirers (Pfizer, AbbVie, Day One Biopharmaceuticals) with no standalone page of their own -- same situation as their pipeline/press-release coverage.
- **Zymeworks**: DOES have a real `www.zymeworks.com/publications/` page with genuine AACR/ESMO/PEGS poster PDFs (confirmed live, 8 pages, ~96 entries) -- deferred to a future round rather than included here: its markup is Elementor page-builder-generated with per-instance auto-generated element IDs, a genuinely higher parsing-fragility risk than the two templates registered this phase, and its current pipeline is more multispecific-antibody-focused than ADC-focused.

## Materialization this run

{result.records_discovered} presentations discovered across {result.queries_run} companies. {len(fresh_ids)} never-attempted (fresh), {len(backlog_ids)} unresolved-retry (backlog), {len(pending_recovery_ids)} pending recovery (raw durable but ledger stale), {len(fast_skip_ids)} already successful and skipped with no request. {result.records_downloaded} newly downloaded (new or changed content), {result.records_skipped_unchanged} unchanged, {result.records_failed} failed.

## Sample materialized presentations

{sample_rows}

## Failed downloads

{result.records_failed} (see DATA/logs/company_scientific_presentations_failures.log and company_scientific_presentations_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run.

## Discovery failures

Isolated per company, same discipline as Job 12: a company's own listing fetch/parse failing does not abort other companies' discovery or block materializing whatever was already found.

{discovery_failure_rows}

## Known coverage gaps

- ADC Therapeutics' items have NO date finer than the congress year (e.g. "ASH 2025") -- preserved in the `congress` column, never fabricated into a false-precision date; `--since`/`--until` cannot filter these items.
- Sutro's presentations-category listing mixes real conference/R&D-day presentation posts with some plain announcement posts under the same WordPress category -- same "acquire broadly, filter downstream" principle already used throughout this repo (e.g. AbbVie/Pfizer's non-ADC-specific pipeline/press-release volume).
- Individual presentation BODY content (poster figures, slide text) is not extracted -- only the raw page/PDF snapshot and the listing page's own title/date/congress are preserved.

## Reproduction command

```bash
python -m adc_acquisition company_scientific_presentations --output DATA
```
"""
