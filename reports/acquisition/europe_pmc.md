# Europe PMC (Job 02)

## Acquisition mechanism

Europe PMC RESTful Web Service (`search` + `fullTextXML`), official REST API. No scraping, no API key required.

## Official endpoint / API / dataset

https://www.ebi.ac.uk/europepmc/webservices/rest/ — https://europepmc.org/RestfulWebService

## Queries used

- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_TRASTUZUMAB_DERUXTECAN` (v1): `(TITLE:"Trastuzumab deruxtecan" OR ABSTRACT:"Trastuzumab deruxtecan")` — Known-ADC asset expansion: bare identifier 'Trastuzumab deruxtecan' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_ENHERTU` (v1): `(TITLE:"Enhertu" OR ABSTRACT:"Enhertu")` — Known-ADC asset expansion: bare identifier 'Enhertu' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_DS_8201` (v1): `(TITLE:"DS-8201" OR ABSTRACT:"DS-8201")` — Known-ADC asset expansion: bare identifier 'DS-8201' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_T_DXD` (v1): `(TITLE:"T-DXd" OR ABSTRACT:"T-DXd")` — Known-ADC asset expansion: bare identifier 'T-DXd' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_PATENT` (v1): `(TITLE:"Trastuzumab deruxtecan" OR ABSTRACT:"Trastuzumab deruxtecan") AND patent` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'patent' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_TRIAL` (v1): `(TITLE:"Trastuzumab deruxtecan" OR ABSTRACT:"Trastuzumab deruxtecan") AND trial` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'trial' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_ACTIVITY` (v1): `(TITLE:"Trastuzumab deruxtecan" OR ABSTRACT:"Trastuzumab deruxtecan") AND activity` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'activity' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_CYTOTOXICITY` (v1): `(TITLE:"Trastuzumab deruxtecan" OR ABSTRACT:"Trastuzumab deruxtecan") AND cytotoxicity` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'cytotoxicity' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_XENOGRAFT` (v1): `(TITLE:"Trastuzumab deruxtecan" OR ABSTRACT:"Trastuzumab deruxtecan") AND xenograft` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'xenograft' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_IC50` (v1): `(TITLE:"Trastuzumab deruxtecan" OR ABSTRACT:"Trastuzumab deruxtecan") AND ic50` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'ic50' for asset trastuzumab_deruxtecan.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_BRENTUXIMAB_VEDOTIN` (v1): `(TITLE:"Brentuximab vedotin" OR ABSTRACT:"Brentuximab vedotin")` — Known-ADC asset expansion: bare identifier 'Brentuximab vedotin' for asset brentuximab_vedotin.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_ADCETRIS` (v1): `(TITLE:"Adcetris" OR ABSTRACT:"Adcetris")` — Known-ADC asset expansion: bare identifier 'Adcetris' for asset brentuximab_vedotin.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_SGN_35` (v1): `(TITLE:"SGN-35" OR ABSTRACT:"SGN-35")` — Known-ADC asset expansion: bare identifier 'SGN-35' for asset brentuximab_vedotin.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_PATENT` (v1): `(TITLE:"Brentuximab vedotin" OR ABSTRACT:"Brentuximab vedotin") AND patent` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'patent' for asset brentuximab_vedotin.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_TRIAL` (v1): `(TITLE:"Brentuximab vedotin" OR ABSTRACT:"Brentuximab vedotin") AND trial` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'trial' for asset brentuximab_vedotin.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_ACTIVITY` (v1): `(TITLE:"Brentuximab vedotin" OR ABSTRACT:"Brentuximab vedotin") AND activity` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'activity' for asset brentuximab_vedotin.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_CYTOTOXICITY` (v1): `(TITLE:"Brentuximab vedotin" OR ABSTRACT:"Brentuximab vedotin") AND cytotoxicity` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'cytotoxicity' for asset brentuximab_vedotin.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_XENOGRAFT` (v1): `(TITLE:"Brentuximab vedotin" OR ABSTRACT:"Brentuximab vedotin") AND xenograft` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'xenograft' for asset brentuximab_vedotin.
- `EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_IC50` (v1): `(TITLE:"Brentuximab vedotin" OR ABSTRACT:"Brentuximab vedotin") AND ic50` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'ic50' for asset brentuximab_vedotin.

## Date coverage

since=(no lower bound), until=(no upper bound) (filtered via `FIRST_PDATE:[...]` when set)

## Records discovered

2423 query-hits across 19 active queries; 1376 unique records.

## Records downloaded

3 new/changed metadata snapshots, 0 skipped as unchanged (matched checkpoint content hash).

## Duplicates

611 records were discovered by more than one query. As with PubMed, the content manifest attributes one primary query_id per record; the full multi-query history lives in `europe_pmc_discovery.parquet` (append-only, one row per (record, query, run)).

### Records per query

- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_ADCETRIS: 98
- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_BRENTUXIMAB_VEDOTIN: 200
- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_ACTIVITY: 200
- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_CYTOTOXICITY: 150
- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_IC50: 39
- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_PATENT: 36
- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_TRIAL: 200
- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_XENOGRAFT: 69
- EPMC_ASSETEXP_BRENTUXIMAB_VEDOTIN_SGN_35: 41
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_DS_8201: 47
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_ENHERTU: 76
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_ACTIVITY: 200
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_CYTOTOXICITY: 200
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_IC50: 64
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_PATENT: 30
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_TRIAL: 200
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_XENOGRAFT: 173
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_TRASTUZUMAB_DERUXTECAN: 200
- EPMC_ASSETEXP_TRASTUZUMAB_DERUXTECAN_T_DXD: 200

## Missing fields

- doi missing in 1/3 records

- records with abstract: 3
- records with DOI: 2
- open access: 1

## Full text (independent artifact, see `europe_pmc_fulltext.parquet`)

1 full-text fetches attempted this run (1 new/changed, 0 unchanged, 0 failed). Full text is tracked as its own content-version manifest, keyed by pmcid with `parent_record_id` pointing back to the metadata record — never as a field on the metadata row itself, so a full-text fetch failure or a later successful retry can never touch the metadata snapshot.

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
python -m adc_acquisition europe_pmc --limit 1376 --output DATA
```
