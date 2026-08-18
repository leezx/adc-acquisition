# PubMed (Job 01)

## Acquisition mechanism

NCBI E-utilities (`esearch` + `efetch`), official REST API. No scraping.

## Official endpoint / API / dataset

https://eutils.ncbi.nlm.nih.gov/entrez/eutils/ — https://www.ncbi.nlm.nih.gov/books/NBK25501/

## Queries used

- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_TRASTUZUMAB_DERUXTECAN` (v1): `"Trastuzumab deruxtecan"[tiab]` — Known-ADC asset expansion: bare identifier 'Trastuzumab deruxtecan' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_ENHERTU` (v1): `"Enhertu"[tiab]` — Known-ADC asset expansion: bare identifier 'Enhertu' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_DS_8201` (v1): `"DS-8201"[tiab]` — Known-ADC asset expansion: bare identifier 'DS-8201' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_T_DXD` (v1): `"T-DXd"[tiab]` — Known-ADC asset expansion: bare identifier 'T-DXd' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_PATENT` (v1): `"Trastuzumab deruxtecan"[tiab] AND patent[tiab]` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'patent' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_TRIAL` (v1): `"Trastuzumab deruxtecan"[tiab] AND trial[tiab]` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'trial' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_ACTIVITY` (v1): `"Trastuzumab deruxtecan"[tiab] AND activity[tiab]` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'activity' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_CYTOTOXICITY` (v1): `"Trastuzumab deruxtecan"[tiab] AND cytotoxicity[tiab]` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'cytotoxicity' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_XENOGRAFT` (v1): `"Trastuzumab deruxtecan"[tiab] AND xenograft[tiab]` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'xenograft' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_IC50` (v1): `"Trastuzumab deruxtecan"[tiab] AND ic50[tiab]` — Known-ADC asset expansion: 'Trastuzumab deruxtecan' + 'ic50' for asset trastuzumab_deruxtecan.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_BRENTUXIMAB_VEDOTIN` (v1): `"Brentuximab vedotin"[tiab]` — Known-ADC asset expansion: bare identifier 'Brentuximab vedotin' for asset brentuximab_vedotin.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_ADCETRIS` (v1): `"Adcetris"[tiab]` — Known-ADC asset expansion: bare identifier 'Adcetris' for asset brentuximab_vedotin.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_SGN_35` (v1): `"SGN-35"[tiab]` — Known-ADC asset expansion: bare identifier 'SGN-35' for asset brentuximab_vedotin.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_PATENT` (v1): `"Brentuximab vedotin"[tiab] AND patent[tiab]` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'patent' for asset brentuximab_vedotin.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_TRIAL` (v1): `"Brentuximab vedotin"[tiab] AND trial[tiab]` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'trial' for asset brentuximab_vedotin.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_ACTIVITY` (v1): `"Brentuximab vedotin"[tiab] AND activity[tiab]` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'activity' for asset brentuximab_vedotin.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_CYTOTOXICITY` (v1): `"Brentuximab vedotin"[tiab] AND cytotoxicity[tiab]` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'cytotoxicity' for asset brentuximab_vedotin.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_XENOGRAFT` (v1): `"Brentuximab vedotin"[tiab] AND xenograft[tiab]` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'xenograft' for asset brentuximab_vedotin.
- `PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_IC50` (v1): `"Brentuximab vedotin"[tiab] AND ic50[tiab]` — Known-ADC asset expansion: 'Brentuximab vedotin' + 'ic50' for asset brentuximab_vedotin.

## Date coverage

since=(no lower bound), until=(no upper bound)

## Records discovered

1803 query-hits across 19 active queries; 1308 unique PMIDs.

## Records downloaded

3 downloaded, 0 skipped as unchanged (matched checkpoint content hash).

## Duplicates

383 PMIDs were discovered by more than one query. The content manifest (`pubmed.parquet`) attributes each record to a single "primary" query per Prompt.md section 3's single-valued contract, but every discovering query is preserved as a separate row in `pubmed_discovery.parquet` (append-only, one row per (PMID, query, run)) — that ledger, not this report, is the authoritative answer to "why is this document in our corpus."

### Records per query

- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_ADCETRIS: 105
- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_BRENTUXIMAB_VEDOTIN: 200
- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_ACTIVITY: 200
- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_CYTOTOXICITY: 27
- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_IC50: 1
- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_PATENT: 1
- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_TRIAL: 200
- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_NAME_XENOGRAFT: 16
- PUBMED_ASSETEXP_BRENTUXIMAB_VEDOTIN_SGN_35: 46
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_DS_8201: 48
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_ENHERTU: 79
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_ACTIVITY: 200
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_CYTOTOXICITY: 34
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_IC50: 6
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_PATENT: 0
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_TRIAL: 200
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_NAME_XENOGRAFT: 40
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_TRASTUZUMAB_DERUXTECAN: 200
- PUBMED_ASSETEXP_TRASTUZUMAB_DERUXTECAN_T_DXD: 200

## Missing fields

- none observed in this run

- records with abstract: 3
- records without abstract: 0
- records with DOI: 3

## Failed downloads

0 (none). Failed attempts never occupy a content-manifest version slot — they live only in the attempts ledger, so they can never overwrite or be overwritten by a real evidence snapshot.

## Rate/access limitations

3 req/s without an NCBI API key, 10 req/s with one (Job used a key). No authentication required for metadata access.

## Data quality observations

- Abstracts are metadata-level (title/abstract/MeSH), not full text.
- Structured abstracts (with Label attributes) are flattened to `Label: text` blocks joined by blank lines.
- `publication_or_release_date` preserves whatever precision PubMed provides (year, year-month, or year-month-day); some records only carry a `MedlineDate` free-text range.

## Known coverage gaps

- Query family covers phrase/abbreviation/immunoconjugate forms only (configs/pubmed_queries.yaml); it will miss papers that describe an ADC without using any of those terms.
- No full text is retrieved here — see Job 02 (Europe PMC / PMC) for legally accessible full text.

## Date distribution

2008: 3

## Reproduction command

```bash
python -m adc_acquisition pubmed --since 1900-01-01 --until 3000-01-01 --limit 1308 --output DATA
```
