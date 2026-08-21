# PubMed (Job 01)

## Acquisition mechanism

NCBI E-utilities (`esearch` + `efetch`), official REST API. No scraping.

## Official endpoint / API / dataset

https://eutils.ncbi.nlm.nih.gov/entrez/eutils/ — https://www.ncbi.nlm.nih.gov/books/NBK25501/

## Queries used

- `PUBMED_ADC_001` (v1): `"antibody-drug conjugate"[tiab] OR "antibody-drug conjugates"[tiab]` — Primary hyphenated phrase form, singular and plural.
- `PUBMED_ADC_002` (v1): `"antibody drug conjugate"[tiab] OR "antibody drug conjugates"[tiab]` — Unhyphenated phrase form, singular and plural.
- `PUBMED_ADC_003` (v1): `ADC[tiab] AND antibody[tiab] AND conjugate[tiab]` — Abbreviation form, constrained by co-occurring antibody/conjugate terms to avoid unrelated "ADC" hits (e.g. AIDS dementia complex, analog-to-digital converter).
- `PUBMED_ADC_004` (v1): `immunoconjugate[tiab] AND cytotoxic[tiab]` — Older/alternative terminology for the same asset class.

## Date coverage

since=(no lower bound), until=(no upper bound)

## Records discovered

1179 query-hits across 4 active queries; 839 unique PMIDs.

## Records downloaded

576 downloaded, 23 skipped as unchanged (matched checkpoint content hash).

## Duplicates

293 PMIDs were discovered by more than one query. The content manifest (`pubmed.parquet`) attributes each record to a single "primary" query per Prompt.md section 3's single-valued contract, but every discovering query is preserved as a separate row in `pubmed_discovery.parquet` (append-only, one row per (PMID, query, run)) — that ledger, not this report, is the authoritative answer to "why is this document in our corpus."

### Records per query

- PUBMED_ADC_001: 600
- PUBMED_ADC_002: 200
- PUBMED_ADC_003: 200
- PUBMED_ADC_004: 179

## Missing fields

- abstract missing in 13/599 records
- doi missing in 38/599 records

- records with abstract: 586
- records without abstract: 13
- records with DOI: 561

## Failed downloads

1 (see DATA/logs/pubmed_failures.log and pubmed_attempts.parquet (status=failed)). Failed attempts never occupy a content-manifest version slot — they live only in the attempts ledger, so they can never overwrite or be overwritten by a real evidence snapshot.

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

1983: 1, 1984: 1, 1987: 2, 1988: 4, 1989: 4, 1990: 6, 1991: 7, 1992: 3, 1993: 7, 1994: 6, 1995: 2, 1996: 4, 1997: 8, 1998: 4, 1999: 6, 2000: 4, 2001: 5, 2002: 7, 2003: 3, 2004: 12, 2005: 8, 2006: 3, 2007: 6, 2008: 5, 2009: 4, 2010: 2, 2011: 7, 2012: 4, 2013: 1, 2014: 3, 2015: 5, 2016: 4, 2017: 1, 2018: 4, 2019: 2, 2020: 3, 2021: 2, 2022: 2, 2023: 5, 2024: 3, 2025: 4, 2026: 425

## Reproduction command

```bash
python -m adc_acquisition pubmed --since 1900-01-01 --until 3000-01-01 --limit 839 --output DATA
```
