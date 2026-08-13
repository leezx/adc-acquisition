# Acquisition Coverage

Status matrix across all planned sources (Prompt.md sections 5–19, execution order in section 29).
Update this table whenever a source's `implementation_status` changes in `configs/sources.yaml`.

| Source | Type | Implemented | API/Bulk | Raw Download | Incremental | Records | Status |
|---|---|---|---|---|---|---:|---|
| PubMed | Literature | Yes | Yes (E-utilities) | Yes (per-PMID XML) | Yes (`--resume` + date range) | 20 (test run) | Implemented, phase-1 reviewed |
| Europe PMC | Literature | Yes | Yes (REST + fullTextXML) | Yes (per-record JSON + OA full text) | Yes (`--resume` + date range) | 20 (test run) | Implemented, phase-2 |
| ClinicalTrials.gov | Clinical | Yes | Yes (API v2) | Yes (per-NCT-ID JSON) | Yes (`--resume` + date range) | 20 (test run) | Implemented, phase-3 |
| Crossref | Literature | Yes | Yes (`/works/{doi}`) | Yes (per-DOI JSON) | N/A — DOI-centric reconciliation, not date range | 24 (test run) | Implemented, phase-4 |
| SEC | Regulatory | Yes | Yes (submissions API) | Yes (per-filing + exhibits) | Yes (`--resume` + `filing_date` range, client-side) | 12 (test run) | Implemented, phase-5 |
| FDA | Regulatory | Yes | Yes (label full-text search + drugsfda API) | Yes (per-application raw record + per-submission JSON + documents) | Yes (`--resume` + `submission_status_date` range, client-side) | 20 (test run) | Implemented (approved products only), phase-6 |
| EMA | Regulatory | Yes | Yes (bulk medicines + EPAR-documents JSON feeds) | Yes (per-medicine raw record + documents + raw bulk snapshots) | Yes (`--resume` + `last_updated_date` range, client-side) | 16 (test run) | Implemented (PSUSA/DHPC safety feeds not covered), phase-7 |
| WIPO | Patent | Yes | Yes (EPO OPS, not WIPO PATENTSCOPE — see notes) | Yes (per-publication biblio XML) | Full undated discovery sweep every run; `--since`/`--until` server-side CQL; already-successful publications skipped (biblio treated as immutable) | 12 (test run) | Implemented, phase-8. WIPO PATENTSCOPE itself has no public API and its Terms of Use forbid automated access — acquired via EPO OPS instead, filtered to WO-prefixed publications |
| USPTO | Patent | No | Unknown | — | — | 0 | Not started — access mechanism not yet investigated |
| EPO | Patent | No | Unknown | — | — | 0 | Not started — access mechanism not yet investigated |
| Company pipelines | Corporate | No | — | — | — | 0 | Not started — needs `configs/company_registry.yaml` first |
| Company PR | Corporate | No | — | — | — | 0 | Not started |
| Patent bioactivity corpus | Derived | No | — | — | — | 0 | Not started — depends on WIPO/USPTO/EPO |
| Publication bioactivity corpus | Derived | No | — | — | — | 0 | Not started — depends on PubMed/Europe PMC |
| Known-ADC asset expansion | Derived | No | — | — | — | 0 | Not started |

Per-source reports live at `reports/acquisition/<source>.md`.
