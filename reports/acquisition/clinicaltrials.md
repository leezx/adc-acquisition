# ClinicalTrials.gov (Job 03)

## Acquisition mechanism

ClinicalTrials.gov API v2 (`GET /studies`), official REST API. No scraping, no API key required.

## Official endpoint / API / dataset

https://clinicaltrials.gov/api/v2/studies — https://clinicaltrials.gov/data-api/api

## Queries used

- `CTGOV_LOOKUP_INTR_592ad6122143` (v1): `query.intr=SGN-35` — known-asset lookup for intervention 'SGN-35'

## Date coverage

since=(no lower bound), until=(no upper bound) (filtered via `AREA[LastUpdatePostDate]RANGE[...]` when set)

## Records discovered

100 query-hits across 1 active queries; 100 unique NCT IDs.

## Records downloaded

0 new/changed trial snapshots, 3 skipped as unchanged (matched checkpoint content hash).

## Duplicates

0 NCT IDs were discovered by more than one query. As with PubMed/Europe PMC, the content manifest attributes one primary query_id per record; the full multi-query history lives in `clinicaltrials_discovery.parquet`.

### Records per query

- CTGOV_LOOKUP_INTR_592ad6122143: 100

## Missing fields

- start_date missing in 1/3 records

- records with at least one phase recorded: 3
- records with enrollment count: 3
- overall status distribution: COMPLETED: 3

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
python -m adc_acquisition clinicaltrials --limit 100 --output DATA
```
