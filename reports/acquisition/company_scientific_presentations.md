# Company Scientific Presentations (BREADTH_PLAN.md Phase 5 Part 7)

## Acquisition mechanism

Distinct from Job 12 (company press releases): an IR newsroom announces corporate news, but a company's ACTUAL scientific congress presentations/posters (AACR/ASCO/ESMO/ASH/etc.) often live on a separate page -- sometimes a genuinely different domain (see `configs/company_registry.yaml`'s note on ADC Therapeutics' adctmedical.com microsite). Only companies with a real, live-verified scrapable listing are registered here -- not attempted for every company (see "Companies checked but not registered" below). Each company's `presentations_url` is discovered by walking its listing's pagination (or fetching once, for a "single_page" template), using a per-company `presentations_template` to select the correct parser (`jobs/company_scientific_presentations/parser.py`). Only items whose own URL stays on `presentations_url`'s OWN domain (never the company's generic `official_domain` -- see module docstring for why) are accepted.

**Sutro's own listing/detail records are wrapper pages, not necessarily scientific content.** Sutro's presentations-category listing mixes real conference/R&D-day posts with plain corporate announcements under the same WordPress category, and even a real conference post's own detail-page HTML is frequently just an announcement ("Sutro presented at AACR... View presentation here.") rather than the scientific content itself. So the counts below distinguish "Sutro presentation-category listing/detail records" (the wrapper HTML, always kept regardless) from "primary-artifact PDFs" (the embedded poster/slide-deck PDF that actually carries target/payload/linker/platform/preclinical data, materialized as a separate child record -- see "Sutro primary-artifact PDF children" below). ADC Therapeutics' items need no such distinction -- each IS a direct PDF poster/slide-deck already.

## Registered companies this run

- Sutro Biopharma, Inc. (sutro_biopharma): https://www.sutrobio.com/news/presentations/ [sutro_divi_blog]
- ADC Therapeutics SA (adc_therapeutics): https://www.adctmedical.com/congresses/ [adctmedical_congress_listing]

## Companies checked but not registered (live-verified 2026-08-24, disclosed not attempted)

- **AbbVie**: main domain (abbvie.com) is behind the same Cloudflare JS challenge already documented for its pipeline page; no separate public scientific-presentations microsite found.
- **Pfizer**: no distinct presentations archive found; `pfizer.com/news/press-kits/oncology` only has stale 2018-2020 blog-post assets, not real congress presentation content.
- **Seagen, ImmunoGen, Mersana**: acquired/absorbed, domains redirect to their respective acquirers (Pfizer, AbbVie, Day One Biopharmaceuticals) with no standalone page of their own -- same situation as their pipeline/press-release coverage.
- **Zymeworks**: DOES have a real `www.zymeworks.com/publications/` page with genuine AACR/ESMO/PEGS poster PDFs (confirmed live, 8 pages, ~96 entries) -- deferred to a future round rather than included here: its markup is Elementor page-builder-generated with per-instance auto-generated element IDs, a genuinely higher parsing-fragility risk than the two templates registered this phase, and its current pipeline is more multispecific-antibody-focused than ADC-focused.

## Materialization this run

0 presentations discovered across 2 companies. 0 never-attempted (fresh), 0 unresolved-retry (backlog), 0 pending recovery (raw durable but ledger stale), 0 already successful and skipped with no request. 0 newly downloaded (new or changed content), 0 unchanged, 0 failed.

## Sample materialized presentations

n/a

## Sutro primary-artifact PDF children

189 Sutro presentation-category listing/detail records (wrapper HTML, always kept regardless of whether a primary artifact was found; a record with more than one content-version row over time is counted once here). 83 of those have at least one primary presentation/poster PDF discovered on their own detail page. 107 artifact PDFs successfully materialized so far as separate child records (source_record_type=company_scientific_presentation_artifact, parent_record_id set to their Sutro HTML parent's own source_record_id) -- a single detail page can legitimately bundle more than one artifact (e.g. a multi-author conference wrap-up post links one poster PDF per author). A page with no primary artifact is not a failure of any kind -- its wrapper HTML is still the correct acquisition artifact for that record.

## Failed downloads

0 (see DATA/logs/company_scientific_presentations_failures.log and company_scientific_presentations_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run.

## Discovery failures

Isolated per company, same discipline as Job 12: a company's own listing fetch/parse failing does not abort other companies' discovery or block materializing whatever was already found.

None this run.

## Known coverage gaps

- ADC Therapeutics' items have NO date finer than the congress year (e.g. "ASH 2025") -- preserved in the `congress` column, never fabricated into a false-precision date; `--since`/`--until` cannot filter these items.
- Sutro's presentations-category listing mixes real conference/R&D-day presentation posts with some plain announcement posts under the same WordPress category -- same "acquire broadly, filter downstream" principle already used throughout this repo (e.g. AbbVie/Pfizer's non-ADC-specific pipeline/press-release volume). See "Sutro primary-artifact PDF children" above for how many of these 189 listing/detail records actually carry a primary scientific-content PDF, as opposed to being announcement-only wrapper pages.
- Individual presentation BODY content (poster figures, slide text) is not extracted -- only the raw page/PDF snapshot and the listing page's own title/date/congress are preserved. For Sutro, the primary-artifact PDF child IS materialized as its own raw snapshot (one hop from the wrapper HTML); its own body content (poster figures, slide text) is likewise not further extracted.

## Reproduction command

```bash
python -m adc_acquisition company_scientific_presentations --output DATA
```
