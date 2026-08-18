# Known-ADC Asset Expansion (Job 15)

## Acquisition mechanism

ASSET-CENTRIC EXPANSION PASS -- Prompt.md: "another acquisition loop should operate from known asset names," distinct from the broad DISCOVERY PASS Jobs 01-14 already perform ("do not conflate the two passes"). This job generates source-specific searches (bare name/alias, plus "patent"/"trial"/"activity"/"cytotoxicity"/"xenograft"/"IC50" suffixes for PubMed/Europe PMC/USPTO) from a curated known-ADC asset registry, then EXECUTES them by calling Jobs 01 (PubMed), 02 (Europe PMC), 03 (ClinicalTrials.gov), 08 (WIPO), 09 (USPTO), and 10 (EPO) in-process with those queries. This job has NO content manifest of its own -- every discovered/materialized record lands in those jobs' own manifests, tagged with an asset-expansion query_id for provenance. Crossref (Job 04) is not a target (its own free-text search is unusable for precise discovery, already established live).

## Known-ADC asset registry

2 active assets:

- **Trastuzumab deruxtecan** (trastuzumab_deruxtecan) — aliases: Enhertu; dev codes: DS-8201, T-DXd; target: HER2; company: Daiichi Sankyo
- **Brentuximab vedotin** (brentuximab_vedotin) — aliases: Adcetris; dev codes: SGN-35; target: CD30; company: Seagen

## Per-source execution this run

- **pubmed**: 19 queries generated — 1308 discovered, 0 downloaded, 3 skipped_unchanged, 0 failed
- **europe_pmc**: 19 queries generated — 1376 discovered, 0 downloaded, 3 skipped_unchanged, 0 failed
- **wipo**: 7 queries generated — 9 discovered, 3 downloaded, 3 skipped_unchanged, 0 failed
- **epo**: 7 queries generated — 1 discovered, 0 downloaded, 1 skipped_unchanged, 0 failed
- **uspto**: 19 queries generated — 2 discovered, 2 downloaded, 0 skipped_unchanged, 0 failed
- **clinicaltrials**: 7 queries generated — 657 discovered, 0 downloaded, 21 skipped_unchanged, 0 failed

**Aggregate:** 3353 records discovered across all sources this run, 5 newly downloaded.

Each source's OWN `reports/acquisition/<source>.md` continues to describe ONLY that job's broad-discovery pass, unchanged by this run -- this job explicitly restores it after every sub-invocation (Prompt.md: "do not conflate the two passes" applies to reporting, not just acquisition). Full per-record provenance for what THIS asset-expansion pass discovered lives in each source's OWN `*_discovery.parquet`/`*_attempts.parquet` instead -- every row there is tagged with its own asset-expansion `query_id` (e.g. `PUBMED_ASSETEXP_...`), which is the actual audit trail for "why is this record in our corpus."

## Reproduction command

```bash
python -m adc_acquisition known_adc_asset_expansion --output DATA
```
