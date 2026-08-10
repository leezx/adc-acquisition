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

778 query-hits across 4 active queries; 523 unique PMIDs.

## Records downloaded

0 downloaded, 20 skipped as unchanged (matched checkpoint content hash).

## Duplicates

201 PMIDs were discovered by more than one query. The content manifest (`pubmed.parquet`) attributes each record to a single "primary" query per Prompt.md section 3's single-valued contract, but every discovering query is preserved as a separate row in `pubmed_discovery.parquet` (append-only, one row per (PMID, query, run)) — that ledger, not this report, is the authoritative answer to "why is this document in our corpus."

### Records per query

- PUBMED_ADC_001: 200
- PUBMED_ADC_002: 200
- PUBMED_ADC_003: 200
- PUBMED_ADC_004: 178

## Missing fields

- doi missing in 8/20 records

- records with abstract: 20
- records without abstract: 0
- records with DOI: 12

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

1988: 1, 1989: 3, 1990: 6, 1991: 7, 1992: 3

## Reproduction command

```bash
python -m adc_acquisition pubmed --since 1900-01-01 --until 3000-01-01 --limit 523 --output DATA
```
