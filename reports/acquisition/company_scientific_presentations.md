# Company Scientific Presentations (BREADTH_PLAN.md Phase 5 Part 7)

## Acquisition mechanism

Distinct from Job 12 (company press releases): an IR newsroom announces corporate news, but a company's ACTUAL scientific congress presentations/posters (AACR/ASCO/ESMO/ASH/etc.) often live on a separate page -- sometimes a genuinely different domain (see `configs/company_registry.yaml`'s note on ADC Therapeutics' adctmedical.com microsite). Only companies with a real, live-verified scrapable listing are registered here -- not attempted for every company (see "Companies checked but not registered" below). Each company's `presentations_url` is discovered by walking its listing's pagination (or fetching once, for a "single_page" template), using a per-company `presentations_template` to select the correct parser (`jobs/company_scientific_presentations/parser.py`). Only items whose own URL stays on `presentations_url`'s OWN domain (never the company's generic `official_domain` -- see module docstring for why) are accepted.

## Registered companies this run

- Sutro Biopharma, Inc. (sutro_biopharma): https://www.sutrobio.com/news/presentations/ [sutro_divi_blog]
- ADC Therapeutics SA (adc_therapeutics): https://www.adctmedical.com/congresses/ [adctmedical_congress_listing]

## Companies checked but not registered (live-verified 2026-08-24, disclosed not attempted)

- **AbbVie**: main domain (abbvie.com) is behind the same Cloudflare JS challenge already documented for its pipeline page; no separate public scientific-presentations microsite found.
- **Pfizer**: no distinct presentations archive found; `pfizer.com/news/press-kits/oncology` only has stale 2018-2020 blog-post assets, not real congress presentation content.
- **Seagen, ImmunoGen, Mersana**: acquired/absorbed, domains redirect to their respective acquirers (Pfizer, AbbVie, Day One Biopharmaceuticals) with no standalone page of their own -- same situation as their pipeline/press-release coverage.
- **Zymeworks**: DOES have a real `www.zymeworks.com/publications/` page with genuine AACR/ESMO/PEGS poster PDFs (confirmed live, 8 pages, ~96 entries) -- deferred to a future round rather than included here: its markup is Elementor page-builder-generated with per-instance auto-generated element IDs, a genuinely higher parsing-fragility risk than the two templates registered this phase, and its current pipeline is more multispecific-antibody-focused than ADC-focused.

## Materialization this run

293 presentations discovered across 2 companies. 293 never-attempted (fresh), 0 unresolved-retry (backlog), 0 pending recovery (raw durable but ledger stale), 0 already successful and skipped with no request. 293 newly downloaded (new or changed content), 0 unchanged, 0 failed.

## Sample materialized presentations

- ADC Therapeutics SA: Lonca RW Effectiveness Post CAR-T | N. Epperla (Tandem 2024, https://www.adctmedical.com/wp-content/uploads/2024/02/Tandem-2024_Epperla_Poster_482.pdf, version 1)
- ADC Therapeutics SA: Lonca RW Outcomes Pre CAR-T (CIBMTR) | M . Hamadani (Tandem 2024, https://www.adctmedical.com/wp-content/uploads/2024/02/Tandem-2024_Hamadani_Poster_492.pdf, version 1)
- ADC Therapeutics SA: LOTIS-5: Lonca-R in r/r DLBCL - Safety Run-In [Updated Results] | M. Kwiatek (SOHO 2023, https://www.adctmedical.com/wp-content/uploads/2023/09/Kwiatek_SOHO-402-311-LOTIS-5-poster_updated-FINAL.pdf, version 1)
- ADC Therapeutics SA: LOTIS-5: Lonca-R vs Immunotherapy in r/r DLBCL - Safety Run-in [Initial Results] | E. Kingsley (SOHO 2022, https://www.adctmedical.com/wp-content/uploads/2022/09/SOHO_2022_Kingsley_LOTIS_5_Safety_Run_in_Poster_FINAL.pdf, version 1)
- ADC Therapeutics SA: LOTIS-2: Lonca HRQoL - Skin Toxicity | A. Spira (SOHO 2022, https://www.adctmedical.com/wp-content/uploads/2022/09/SOHO_2022_Spira_HEOR_LOTIS_2_HRQoL_Skin_Toxicity_Poster_FINAL.pdf, version 1)
- ADC Therapeutics SA: LOTIS-2: Lonca r/r DLBCL [Updated Results] - ENCORE | B. Kahl (SOHO 2021, https://www.adctmedical.com/wp-content/uploads/2021/09/SOHO-2021_Kahl_ADCT-402-201-Encore-Oral__ABCL-022_FINAL.pdf, version 1)
- ADC Therapeutics SA: LOTIS-2: Lonca AE Management - Edema and Effusion | J. Alderuccio (SOHO 2021, https://www.adctmedical.com/wp-content/uploads/2021/10/SOHO-2021_Alderuccio_ADCT-402-201-edema-effusion_Eposter_ABCL-396_FINAL_corrected.pdf, version 1)
- ADC Therapeutics SA: Preclinical: Camidanlumab in Solid Cancers | F. Zammarchi (SITC 2020, https://www.adctmedical.com/wp-content/uploads/2023/06/SITC-2020_Zammarchi_CD25-ADC-combo-preclin_poster.pdf, version 1)
- ADC Therapeutics SA: Preclinical: Cami (ADCT-301) MOA in Solid Cancers | F. Zammarchi (SITC 2019, https://www.adctmedical.com/wp-content/uploads/2023/06/SITC-2019_Zammarchi_ADCT-301-preclin_Poster_Final.pdf, version 1)
- ADC Therapeutics SA: Preclinical: Camidanlumab in Solid Tumors alone or w/ anti-PD-1s | F. Zammarchi (SITC 2018, https://www.adctmedical.com/wp-content/uploads/2021/04/SITC_301_2018_SolidTumors.pdf, version 1)
- ADC Therapeutics SA: Lonca + Epcoritamab in DLBCL (QSP modeling) | Y. Li (PPLC 2024, https://www.adctmedical.com/wp-content/uploads/2024/08/PPLC-2024-QSP-Lonca-_-epcor-ePoster_FINAL.pdf, version 1)
- ADC Therapeutics SA: LOTIS-7: Lonca in r/r B-NHL [Trial-In-Progress Update] | E. Ayers (PPLC 2024, https://www.adctmedical.com/wp-content/uploads/2024/07/PPLC-2024_Ayers_LOTIS-7-TiP-Update-Poster_FINAL.pdf, version 1)
- ADC Therapeutics SA: LOTIS-2: Lonca AE Management - Cutaneous Reactions | J. Pruett (ONS 2022, https://www.adctmedical.com/wp-content/uploads/2022/06/ONS_2022_Pruett_402-201_Cutaneous_Reactions_poster_FINAL_63.pdf, version 1)
- ADC Therapeutics SA: LOTIS-2: Lonca AE Management - Edema and Effusion [Updated Results] | C. Grandas (ONS 2022, https://www.adctmedical.com/wp-content/uploads/2022/06/ONS_2022_Grandas_402-201_Edema_and_Effusion_poster_FINAL_14.pdf, version 1)
- ADC Therapeutics SA: LOTIS-2: Lonca in r/r/ DLBCL - HRQoL Older vs Younger | A. Spira (NCCN 2022, https://www.adctmedical.com/wp-content/uploads/2022/06/NCCN_2022_Spira_402-201_HRQoL_Poster_FINAL.pdf, version 1)
- ADC Therapeutics SA: HEOR: Treatment-Related Costs in r/r DLBCL | L. Liao (ISPOR 2021, https://www.adctmedical.com/wp-content/uploads/2021/05/Treatment-Related-Costs-for-Patients-with-RR-DLBCL-with-2-or-More-Prior-Lines-of-Therapy.pdf, version 1)
- ADC Therapeutics SA: LOTIS-7: Lonca + Glofit r/r DLBCL [Initial Results] - ENCORE | J. Alderuccio (ICML 2025, https://www.adctmedical.com/wp-content/uploads/2025/06/ICML-2025_LOTIS-7-Prelim_Encore_Oral-Presentation_FINAL.pdf, version 1)
- ADC Therapeutics SA: LOTIS-2: Lonca in r/r DLBCL [Updated Results] - ENCORE | P. Caimi (ICML 2023, https://www.adctmedical.com/wp-content/uploads/2023/06/ICML_2023_EncoreLOTIS-2-1-and-2-yr-Responders_Oral-Presentation_FINAL.pdf, version 1)
- ADC Therapeutics SA: LOTIS-6: Lonca vs Idelalisib in r/r FL [Trial-In-Progress] | C. Carlo-Stella (ICML 2021, https://www.adctmedical.com/wp-content/uploads/2021/06/Carlo-Stella-et-al-A-Phase-2-randomized-study-of-lonca-vs-idelalisib-in-patients-with-RR-FL-LOTIS-6.pdf, version 1)
- ADC Therapeutics SA: LOTIS-2: Lonca in r/r DLBCL [Updated Results] - ENCORE | P.L. Zinzani (ICML 2021, https://www.adctmedical.com/wp-content/uploads/2021/08/PPLC-2021-Kahl-ADCT-402-201-eposter-encore-ICML-2021.pdf, version 1)

## Failed downloads

0 (see DATA/logs/company_scientific_presentations_failures.log and company_scientific_presentations_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run.

## Discovery failures

Isolated per company, same discipline as Job 12: a company's own listing fetch/parse failing does not abort other companies' discovery or block materializing whatever was already found.

None this run.

## Known coverage gaps

- ADC Therapeutics' items have NO date finer than the congress year (e.g. "ASH 2025") -- preserved in the `congress` column, never fabricated into a false-precision date; `--since`/`--until` cannot filter these items.
- Sutro's presentations-category listing mixes real conference/R&D-day presentation posts with some plain announcement posts under the same WordPress category -- same "acquire broadly, filter downstream" principle already used throughout this repo (e.g. AbbVie/Pfizer's non-ADC-specific pipeline/press-release volume).
- Individual presentation BODY content (poster figures, slide text) is not extracted -- only the raw page/PDF snapshot and the listing page's own title/date/congress are preserved.

## Reproduction command

```bash
python -m adc_acquisition company_scientific_presentations --output DATA
```
