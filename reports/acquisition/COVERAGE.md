# Acquisition Coverage

Status matrix across all planned sources (Prompt.md sections 5–19, execution order in section 29).
Update this table whenever a source's `implementation_status` changes in `configs/sources.yaml`.

| Source | Type | Implemented | API/Bulk | Raw Download | Incremental | Records | Status |
|---|---|---|---|---|---|---:|---|
| PubMed | Literature | Yes | Yes (E-utilities) | Yes (per-PMID XML) | Yes (`--resume` + date range) | 20 (test run) | Implemented, phase-1 reviewed |
| Europe PMC | Literature | Yes | Yes (REST + fullTextXML) | Yes (per-record JSON + OA full text) | Yes (`--resume` + date range) | 20 (test run) | Implemented, phase-2 |
| ClinicalTrials.gov | Clinical | Yes | Yes (API v2) | Yes (per-NCT-ID JSON) | Yes (`--resume` + date range) | 20 (test run) | Implemented, phase-3 |
| Crossref | Literature | No | — | — | — | 0 | Not started |
| SEC | Regulatory | No | — | — | — | 0 | Not started |
| FDA | Regulatory | No | — | — | — | 0 | Not started |
| EMA | Regulatory | No | — | — | — | 0 | Not started |
| WIPO | Patent | No | Unknown | — | — | 0 | Not started — access mechanism not yet investigated |
| USPTO | Patent | No | Unknown | — | — | 0 | Not started — access mechanism not yet investigated |
| EPO | Patent | No | Unknown | — | — | 0 | Not started — access mechanism not yet investigated |
| Company pipelines | Corporate | No | — | — | — | 0 | Not started — needs `configs/company_registry.yaml` first |
| Company PR | Corporate | No | — | — | — | 0 | Not started |
| Patent bioactivity corpus | Derived | No | — | — | — | 0 | Not started — depends on WIPO/USPTO/EPO |
| Publication bioactivity corpus | Derived | No | — | — | — | 0 | Not started — depends on PubMed/Europe PMC |
| Known-ADC asset expansion | Derived | No | — | — | — | 0 | Not started |

Per-source reports live at `reports/acquisition/<source>.md`.
