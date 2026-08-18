# Known-ADC Asset Expansion (Job 15)

## Acquisition mechanism

ASSET-CENTRIC EXPANSION PASS -- Prompt.md: "another acquisition loop should operate from known asset names," distinct from the broad DISCOVERY PASS Jobs 01-14 already perform ("do not conflate the two passes"). This job generates source-specific searches (bare name/alias, plus "patent"/"trial"/"activity"/"cytotoxicity"/"xenograft"/"IC50" suffixes for PubMed/Europe PMC/USPTO) from a curated known-ADC asset registry, then EXECUTES them by calling Jobs 01 (PubMed), 02 (Europe PMC), 03 (ClinicalTrials.gov), 08 (WIPO), 09 (USPTO), and 10 (EPO) in-process with those queries. This job has NO content manifest of its own -- every discovered/materialized record lands in those jobs' own manifests, tagged with an asset-expansion query_id for provenance. Crossref (Job 04) is not a target (its own free-text search is unusable for precise discovery, already established live).

## Known-ADC asset registry

14 active assets:

- **Gemtuzumab ozogamicin** (gemtuzumab_ozogamicin) — aliases: Mylotarg; dev codes: CMA-676; target: CD33; company: Pfizer
- **Brentuximab vedotin** (brentuximab_vedotin) — aliases: Adcetris; dev codes: SGN-35; target: CD30; company: Seagen
- **Trastuzumab emtansine** (trastuzumab_emtansine) — aliases: Kadcyla; dev codes: T-DM1; target: HER2; company: Genentech
- **Inotuzumab ozogamicin** (inotuzumab_ozogamicin) — aliases: Besponsa; dev codes: CMC-544; target: CD22; company: Pfizer
- **Polatuzumab vedotin** (polatuzumab_vedotin) — aliases: Polivy; dev codes: DCDS4501A, RG7596; target: CD79b; company: Genentech
- **Enfortumab vedotin** (enfortumab_vedotin) — aliases: Padcev; dev codes: ASG-22ME; target: Nectin-4; company: Seagen
- **Trastuzumab deruxtecan** (trastuzumab_deruxtecan) — aliases: Enhertu; dev codes: DS-8201, T-DXd; target: HER2; company: Daiichi Sankyo
- **Sacituzumab govitecan** (sacituzumab_govitecan) — aliases: Trodelvy; dev codes: IMMU-132; target: Trop-2; company: Gilead Sciences
- **Belantamab mafodotin** (belantamab_mafodotin) — aliases: Blenrep; dev codes: GSK2857916; target: BCMA; company: GSK
- **Loncastuximab tesirine** (loncastuximab_tesirine) — aliases: Zynlonta; dev codes: ADCT-402; target: CD19; company: ADC Therapeutics
- **Tisotumab vedotin** (tisotumab_vedotin) — aliases: Tivdak; dev codes: HuMax-TF-ADC; target: Tissue Factor; company: Genmab
- **Mirvetuximab soravtansine** (mirvetuximab_soravtansine) — aliases: Elahere; dev codes: IMGN853; target: Folate receptor alpha; company: ImmunoGen
- **Disitamab vedotin** (disitamab_vedotin) — aliases: Aidixi; dev codes: RC48; target: HER2; company: RemeGen
- **Datopotamab deruxtecan** (datopotamab_deruxtecan) — aliases: Datroway; dev codes: DS-1062, Dato-DXd; target: Trop-2; company: Daiichi Sankyo

## Per-source execution this run

- **pubmed**: 129 queries generated — 4531 discovered, 25 downloaded, 0 skipped_unchanged, 0 failed
- **europe_pmc**: 129 queries generated — 4897 discovered, 23 downloaded, 2 skipped_unchanged, 0 failed
- **wipo**: 45 queries generated — 66 discovered, 25 downloaded, 6 skipped_unchanged, 0 failed
- **epo**: 45 queries generated — 6 discovered, 5 downloaded, 1 skipped_unchanged, 0 failed
- **uspto**: 129 queries generated — 83 discovered, 25 downloaded, 0 skipped_unchanged, 0 failed
- **clinicaltrials**: 45 queries generated — 2688 discovered, 460 downloaded, 502 skipped_unchanged, 0 failed

**Aggregate:** 12271 records discovered across all sources this run, 563 newly downloaded.

Each source's OWN `reports/acquisition/<source>.md` continues to describe ONLY that job's broad-discovery pass, unchanged by this run -- this job explicitly restores it after every sub-invocation (Prompt.md: "do not conflate the two passes" applies to reporting, not just acquisition). Full per-record provenance for what THIS asset-expansion pass discovered lives in each source's OWN `*_discovery.parquet`/`*_attempts.parquet` instead -- every row there is tagged with its own asset-expansion `query_id` (e.g. `PUBMED_ASSETEXP_...`), which is the actual audit trail for "why is this record in our corpus."

## Reproduction command

```bash
python -m adc_acquisition known_adc_asset_expansion --output DATA
```
