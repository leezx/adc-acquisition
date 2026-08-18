# Known-ADC Asset Expansion (Job 15)

## Acquisition mechanism

ASSET-CENTRIC EXPANSION PASS -- Prompt.md: "another acquisition loop should operate from known asset names," distinct from the broad DISCOVERY PASS Jobs 01-14 already perform ("do not conflate the two passes"). This job generates source-specific searches (bare name/alias, plus "patent"/"trial"/"activity"/"cytotoxicity"/"xenograft"/"IC50" suffixes for literature sources) from a curated known-ADC asset registry, then EXECUTES them by calling Jobs 01 (PubMed), 02 (Europe PMC), 03 (ClinicalTrials.gov), 08 (WIPO), and 10 (EPO) in-process with those queries. This job has NO content manifest of its own -- every discovered/materialized record lands in those jobs' own manifests, tagged with an asset-expansion query_id for provenance. Crossref (Job 04) is not a target (its own free-text search is unusable for precise discovery, already established live).

## Known-ADC asset registry

2 active assets:

- **Trastuzumab deruxtecan** (trastuzumab_deruxtecan) — aliases: Enhertu; dev codes: DS-8201, T-DXd; target: HER2; company: Daiichi Sankyo
- **Brentuximab vedotin** (brentuximab_vedotin) — aliases: Adcetris; dev codes: SGN-35; target: CD30; company: Seagen

## Per-source execution this run

- **pubmed**: 19 queries generated — 1308 discovered, 3 downloaded, 0 skipped_unchanged, 0 failed
- **europe_pmc**: 19 queries generated — 1376 discovered, 3 downloaded, 0 skipped_unchanged, 0 failed
- **wipo**: 7 queries generated — 9 discovered, 3 downloaded, 0 skipped_unchanged, 0 failed
- **epo**: 7 queries generated — 1 discovered, 1 downloaded, 0 skipped_unchanged, 0 failed
- **clinicaltrials**: 7 queries generated — 657 discovered, 13 downloaded, 8 skipped_unchanged, 0 failed

**Aggregate:** 3351 records discovered across all sources this run, 23 newly downloaded (see each source's OWN report — reports/acquisition/{pubmed,europe_pmc,clinicaltrials,wipo,epo}.md — for full per-record detail; this report only summarizes the asset-expansion pass's contribution).

## Reproduction command

```bash
python -m adc_acquisition known_adc_asset_expansion --output DATA
```
