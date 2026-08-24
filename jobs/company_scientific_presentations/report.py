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
    run_df = (
        manifest_df[manifest_df["source_record_id"].isin(all_ids) | manifest_df["parent_record_id"].isin(all_ids)]
        if not manifest_df.empty else manifest_df
    )
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["company", "congress"], ascending=[True, False])
        sample_rows = "\n".join(
            f"- {row['company']}: {row['title'] or 'n/a'} "
            f"({row['congress'] or row['publication_or_release_date'] or 'date unknown'}, {row['url']}, "
            f"{row['source_record_type']}, version {row['version']})"
            for _, row in sample.head(20).iterrows()
        )

    sutro_parents = manifest_df[manifest_df["source_record_type"] == "company_scientific_presentation"] if not manifest_df.empty else manifest_df
    sutro_parents = sutro_parents[sutro_parents["company"] == "Sutro Biopharma, Inc."] if not sutro_parents.empty else sutro_parents
    sutro_parent_count = sutro_parents["source_record_id"].nunique() if not sutro_parents.empty else 0
    sutro_artifacts = manifest_df[manifest_df["source_record_type"] == "company_scientific_presentation_artifact"] if not manifest_df.empty else manifest_df
    sutro_parents_with_artifact = sutro_artifacts["parent_record_id"].nunique() if not sutro_artifacts.empty else 0
    sutro_artifact_count = sutro_artifacts["source_record_id"].nunique() if not sutro_artifacts.empty else 0

    registry_rows = "\n".join(
        f"- {c.canonical_name} ({c.company_id}): {c.presentations_url or 'no presentations_url registered'}"
        + (f" [{c.presentations_template}]" if c.presentations_template else "")
        for c in companies
    )

    return f"""# Company Scientific Presentations (BREADTH_PLAN.md Phase 5 Part 7)

## Acquisition mechanism

Distinct from Job 12 (company press releases): an IR newsroom announces corporate news, but a company's ACTUAL scientific congress presentations/posters (AACR/ASCO/ESMO/ASH/etc.) often live on a separate page -- sometimes a genuinely different domain (see `configs/company_registry.yaml`'s note on ADC Therapeutics' adctmedical.com microsite). Only companies with a real, live-verified scrapable listing are registered here -- not attempted for every company (see "Companies checked but not registered" below). Each company's `presentations_url` is discovered by walking its listing's pagination (or fetching once, for a "single_page" template), using a per-company `presentations_template` to select the correct parser (`jobs/company_scientific_presentations/parser.py`). Only items whose own URL stays on `presentations_url`'s OWN domain (never the company's generic `official_domain` -- see module docstring for why) are accepted.

**Sutro's own listing/detail records are wrapper pages, not necessarily scientific content.** Sutro's presentations-category listing mixes real conference/R&D-day posts with plain corporate announcements under the same WordPress category, and even a real conference post's own detail-page HTML is frequently just an announcement ("Sutro presented at AACR... View presentation here.") rather than the scientific content itself. So the counts below distinguish "Sutro presentation-category listing/detail records" (the wrapper HTML, always kept regardless) from "primary-artifact PDFs" (the embedded poster/slide-deck PDF that actually carries target/payload/linker/platform/preclinical data, materialized as a separate child record -- see "Sutro primary-artifact PDF children" below). ADC Therapeutics' items need no such distinction -- each IS a direct PDF poster/slide-deck already.

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

## Sutro primary-artifact PDF children

{sutro_parent_count} Sutro presentation-category listing/detail records (wrapper HTML, always kept regardless of whether a primary artifact was found; a record with more than one content-version row over time is counted once here). {sutro_parents_with_artifact} of those have at least one primary presentation/poster PDF discovered on their own detail page. {sutro_artifact_count} artifact PDFs successfully materialized so far as separate child records (source_record_type=company_scientific_presentation_artifact, parent_record_id set to their Sutro HTML parent's own source_record_id) -- a single detail page can legitimately bundle more than one artifact (e.g. a multi-author conference wrap-up post links one poster PDF per author). A page with no primary artifact is not a failure of any kind -- its wrapper HTML is still the correct acquisition artifact for that record.

## Failed downloads

{result.records_failed} (see DATA/logs/company_scientific_presentations_failures.log and company_scientific_presentations_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run.

## Discovery failures

Isolated per company, same discipline as Job 12: a company's own listing fetch/parse failing does not abort other companies' discovery or block materializing whatever was already found.

{discovery_failure_rows}

## Known coverage gaps

- ADC Therapeutics' items have NO date finer than the congress year (e.g. "ASH 2025") -- preserved in the `congress` column, never fabricated into a false-precision date; `--since`/`--until` cannot filter these items.
- Sutro's presentations-category listing mixes real conference/R&D-day presentation posts with some plain announcement posts under the same WordPress category -- same "acquire broadly, filter downstream" principle already used throughout this repo (e.g. AbbVie/Pfizer's non-ADC-specific pipeline/press-release volume). See "Sutro primary-artifact PDF children" above for how many of these 189 listing/detail records actually carry a primary scientific-content PDF, as opposed to being announcement-only wrapper pages.
- Individual presentation BODY content (poster figures, slide text) is not extracted -- only the raw page/PDF snapshot and the listing page's own title/date/congress are preserved. For Sutro, the primary-artifact PDF child IS materialized as its own raw snapshot (one hop from the wrapper HTML); its own body content (poster figures, slide text) is likewise not further extracted.

## Reproduction command

```bash
python -m adc_acquisition company_scientific_presentations --output DATA
```
"""
