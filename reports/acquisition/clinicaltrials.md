# ClinicalTrials.gov (Job 03)

## Acquisition mechanism

ClinicalTrials.gov API v2 (`GET /studies`), official REST API. No scraping, no API key required.

## Official endpoint / API / dataset

https://clinicaltrials.gov/api/v2/studies — https://clinicaltrials.gov/data-api/api

## Queries used

- `CTGOV_ADC_001` (v1): `"antibody-drug conjugate"` — Primary phrase form (hyphen-invariant under Essie tokenization; covers the unhyphenated form too).
- `CTGOV_ADC_002` (v1): `ADC AND antibody AND conjugate` — Abbreviation form, constrained by co-occurring antibody/conjugate terms to avoid unrelated "ADC" hits.
- `CTGOV_ADC_003` (v1): `immunoconjugate AND cytotoxic` — Older/alternative terminology for the same asset class.
- `CTGOV_ADC_004` (v1): `AREA[InterventionName]ADC` — Higher-precision supplementary query restricted to the structured intervention-name field.

## Date coverage

since=(no lower bound), until=(no upper bound) (filtered via `AREA[LastUpdatePostDate]RANGE[...]` when set)

## Records discovered

830 query-hits across 4 active queries; 715 unique NCT IDs.

## Records downloaded

600 new/changed trial snapshots, 0 skipped as unchanged (matched checkpoint content hash).

## Duplicates

107 NCT IDs were discovered by more than one query. As with PubMed/Europe PMC, the content manifest attributes one primary query_id per record; the full multi-query history lives in `clinicaltrials_discovery.parquet`.

### Records per query

- CTGOV_ADC_001: 600
- CTGOV_ADC_002: 100
- CTGOV_ADC_003: 30
- CTGOV_ADC_004: 100

## Missing fields

- official_title missing in 3/721 records
- start_date missing in 3/721 records

- records with at least one phase recorded: 693
- records with enrollment count: 713
- overall status distribution: ACTIVE_NOT_RECRUITING: 115, COMPLETED: 199, ENROLLING_BY_INVITATION: 1, NOT_YET_RECRUITING: 24, NO_LONGER_AVAILABLE: 2, RECRUITING: 212, SUSPENDED: 1, TERMINATED: 84, UNKNOWN: 67, WITHDRAWN: 16

## Failed downloads

0 (none). Failed attempts never occupy a content-manifest version slot.

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
python -m adc_acquisition clinicaltrials --limit 715 --output DATA
```
