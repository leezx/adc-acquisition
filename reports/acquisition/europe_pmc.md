# Europe PMC (Job 02)

## Acquisition mechanism

Europe PMC RESTful Web Service (`search` + `fullTextXML`), official REST API. No scraping, no API key required.

## Official endpoint / API / dataset

https://www.ebi.ac.uk/europepmc/webservices/rest/ — https://europepmc.org/RestfulWebService

## Queries used

- `EPMC_ADC_001` (v1): `(TITLE:"antibody-drug conjugate" OR ABSTRACT:"antibody-drug conjugate" OR TITLE:"antibody-drug conjugates" OR ABSTRACT:"antibody-drug conjugates")` — Primary hyphenated phrase form, singular and plural.
- `EPMC_ADC_002` (v1): `(TITLE:"antibody drug conjugate" OR ABSTRACT:"antibody drug conjugate" OR TITLE:"antibody drug conjugates" OR ABSTRACT:"antibody drug conjugates")` — Unhyphenated phrase form, singular and plural.
- `EPMC_ADC_003` (v1): `(TITLE:"ADC" OR ABSTRACT:"ADC") AND (TITLE:"antibody" OR ABSTRACT:"antibody") AND (TITLE:"conjugate" OR ABSTRACT:"conjugate")` — Abbreviation form, constrained by co-occurring antibody/conjugate terms to avoid unrelated "ADC" hits.
- `EPMC_ADC_004` (v1): `(TITLE:"immunoconjugate" OR ABSTRACT:"immunoconjugate") AND (TITLE:"cytotoxic" OR ABSTRACT:"cytotoxic")` — Older/alternative terminology for the same asset class.

## Date coverage

since=(no lower bound), until=(no upper bound) (filtered via `FIRST_PDATE:[...]` when set)

## Records discovered

1180 query-hits across 4 active queries; 835 unique records.

## Records downloaded

580 new/changed metadata snapshots, 20 skipped as unchanged (matched checkpoint content hash).

## Duplicates

307 records were discovered by more than one query. As with PubMed, the content manifest attributes one primary query_id per record; the full multi-query history lives in `europe_pmc_discovery.parquet` (append-only, one row per (record, query, run)).

### Records per query

- EPMC_ADC_001: 600
- EPMC_ADC_002: 200
- EPMC_ADC_003: 200
- EPMC_ADC_004: 180

## Missing fields

- abstract missing in 1/600 records
- doi missing in 24/600 records
- journal missing in 2/600 records

- records with abstract: 599
- records with DOI: 576
- open access: 247

## Full text (independent artifact, see `europe_pmc_fulltext.parquet`)

247 full-text fetches attempted this run (247 new/changed, 0 unchanged, 0 failed). Full text is tracked as its own content-version manifest, keyed by pmcid with `parent_record_id` pointing back to the metadata record — never as a field on the metadata row itself, so a full-text fetch failure or a later successful retry can never touch the metadata snapshot.

## Failed downloads

0 (none). As with PubMed, failed attempts never occupy a content-manifest version slot. Full-text failures are tracked separately in `europe_pmc_fulltext_attempts.parquet` and likewise never touch a content-manifest version slot (metadata's or full text's own).

## Rate/access limitations

No API key or authentication required. No officially published numeric rate limit; ~10 req/s is the figure commonly cited on the Europe PMC developer forum, so this job uses 5 req/s to stay well under it. Full-text XML is only fetched for records marked `isOpenAccess=Y` by Europe PMC itself — publisher paywalls are never bypassed.

## Data quality observations

- `abstractText` from the `resultType=core` search response is used directly as the abstract; no re-processing.
- A full-text fetch that fails (e.g. Europe PMC's own metadata says open access but the fullTextXML endpoint 404s) is retried on every subsequent run — full text is content-hash-checkpointed exactly like metadata, so it is never a permanent per-record failure.
- No deduplication against the PubMed manifest is performed; `pmid`/`doi` are preserved so a downstream join is possible, but a paper appearing in both sources intentionally keeps two independent evidence rows (Prompt.md section 6).

## Known coverage gaps

- Query family mirrors PubMed's four query forms translated into Europe PMC syntax; same terminology-coverage caveat applies.
- Preprints (`source=PPR`) and patents (`source=PAT`) that Europe PMC indexes are captured like any other record if they match a query — no special handling or filtering is applied to them in this job.

## Reproduction command

```bash
python -m adc_acquisition europe_pmc --limit 835 --output DATA
```
