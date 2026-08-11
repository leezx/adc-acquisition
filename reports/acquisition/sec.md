# SEC EDGAR (Job 05)

## Acquisition mechanism

SEC EDGAR submissions API (`GET /submissions/CIK{cik}.json`) + Archives document retrieval, official REST interfaces. No scraping, no API key required — but every request requires an identifying `User-Agent` header (SEC's fair access policy) or it is rejected with HTTP 403.

## Official endpoint / API / dataset

https://data.sec.gov/submissions/ — https://www.sec.gov/Archives/edgar/data/ — https://www.sec.gov/search-filings/edgar-application-programming-interfaces

## Companies in this run

- Seagen Inc. (CIK 0001060736)
- ImmunoGen, Inc. (CIK 0000855654)
- Mersana Therapeutics, Inc. (CIK 0001442836)
- Zymeworks Inc. (CIK 0001937653)
- Sutro Biopharma, Inc. (CIK 0001382101)
- ADC Therapeutics SA (CIK 0001771910)
- AbbVie Inc. (CIK 0001551152)
- Pfizer Inc. (CIK 0000078003)

## Records discovered

2116 relevant-form filings across 8 companies; 2116 unique accession numbers.

## Records downloaded

0 new/changed filing snapshots, 12 skipped as unchanged (matched checkpoint content hash).

## Duplicates

0 accession numbers were attributed to more than one company entry (should be rare — normally indicates an alias/CIK overlap worth double-checking in configs/company_registry.yaml).

### Filings per company query

- SEC_FILINGS_ABBVIE: 256
- SEC_FILINGS_ADC_THERAPEUTICS: 173
- SEC_FILINGS_IMMUNOGEN: 482
- SEC_FILINGS_MERSANA: 149
- SEC_FILINGS_PFIZER: 489
- SEC_FILINGS_SEAGEN: 349
- SEC_FILINGS_SUTRO_BIOPHARMA: 125
- SEC_FILINGS_ZYMEWORKS: 93

## Missing fields

- none observed in this run

- filing type distribution: 10-Q: 5, 10-Q/A: 1, 8-K: 6
- company distribution: Pfizer Inc.: 12

## Exhibits (independent artifact, see `sec_exhibits.parquet`)

6 exhibit fetches attempted this run (0 new/changed, 6 unchanged, 0 failed). Exhibits are tracked as their own content-version manifest, keyed by `{accession_number}:{filename}` with `parent_record_id` pointing back to the filing — never as a field on the filing row itself, so an exhibit fetch failure or a later successful retry never touches the filing's own content-version snapshot.

## Failed downloads

8 (see DATA/logs/sec_failures.log and sec_attempts.parquet (status=failed)). Failed attempts never occupy a content-manifest version slot.

## Rate/access limitations

Officially documented: max 10 req/s, mandatory identifying `User-Agent` header (name/tool + contact email) or requests are rejected with HTTP 403 and the source IP may be briefly blocked. This job uses 8 req/s to stay under the limit.

## Data quality observations

- `item_codes` (8-K only) are the numbered disclosure items SEC assigns (e.g. "2.01,5.02") — useful downstream for filtering to acquisition/licensing/executive-change items without parsing filing text.
- An amendment (e.g. `10-K/A`) is its own filing with its own accession number, not a patch applied to the original — both remain independent evidence rows by design.
- Only the current 1000 most recent filings plus any additional pages (`filings.files[]`) from the submissions API are covered — a company's full historical filing set is retrieved, not just the most recent page.

## Known coverage gaps

- Only companies in `configs/company_registry.yaml`'s currently-active entries are covered; expanding coverage means adding more curated entries, not open-ended crawling (Prompt.md section 13/11's shared guidance).
- Relevance filtering here is by SEC form type only (`RELEVANT_FORMS` in `jobs/sec/parser.py`) — no attempt is made to judge whether a given filing actually discusses an ADC program; that is a downstream decision (Prompt.md section 30).
- Observed live: some pre-2002 filings have an empty or incorrect `primaryDocument` in the submissions API itself (before EDGAR required a structured primary-document designation), which surfaces as an expected, logged `failed` attempt (missing document / 404) rather than a crash — this is a genuine SEC-side historical data-quality gap, not an acquisition bug.

## Reproduction command

```bash
python -m adc_acquisition sec --limit 2116 --output DATA
```
