# ADC-Acquisition — Project Completion Summary

**Repo:** https://github.com/leezx/adc-acquisition
**Status:** All 15 planned acquisition jobs implemented, reviewed, and merged to `main`
**HEAD:** `b998e26` · **Tests:** 401 passing (`pytest`, all HTTP mocked — no live network required for the suite)

This document is a project-level completion summary, written for external/final review of the acquisition layer as a whole. It is not a per-source report (see `reports/acquisition/COVERAGE.md` and `reports/acquisition/<source>.md` for those) — it summarizes architecture, delivery process, per-job outcomes, recurring lessons, and known disclosed limitations across the entire build.

## 1. What this project is

A source-separated **raw evidence acquisition pipeline** for an antibody-drug-conjugate (ADC) knowledgebase. Per the governing spec (`Prompt.md`, 32 sections), the system's job is strictly **acquisition, not knowledge extraction**: fetch, hash, version, and preserve raw evidence (with full query provenance) from 13 independent external sources plus 2 "second-pass" derived/expansion jobs — never interpret or structure the content itself.

## 2. Architecture

Every job shares a common contract (`Prompt.md` §3–4):

- **Three-table pattern** per source: a **content-version manifest** (immutable, hash-versioned snapshots), a **discovery ledger** (append-only, every query/record/run triple), and an **attempts ledger** (append-only, every fetch attempt incl. failures) — never conflated.
- **Common CLI surface**: `--dry-run --limit N --resume --since --until --output`.
- **Query provenance**: every discovered record traces back to an exact `query_id`/`query_version`/`query_text` (a dedicated `query_registry` module + per-source YAML files).
- **Checkpointing**: per-record content hashes + version numbers, with a `--refresh` escape hatch for sources whose skip-by-default assumption needs periodic re-verification.
- **Never**: CAPTCHA bypass, auth circumvention, aggressive crawling. Documented, disclosed failure when a source blocks (e.g., Cloudflare) rather than defeated.

## 3. Delivery process

Strictly phase-gated: **one job = one PR**, human review required (chat-based APPROVE/REQUEST_CHANGES — GitHub's review API 403s for this reviewer) before the next job started. Every job was live-verified against the *real* external API/source before merge, not just unit-tested against mocks.

## 4. Job-by-job status

| # | Job | Source(s) | Review rounds | Key mechanism / notable finding |
|---|-----|-----------|:---:|---|
| 01 | PubMed | E-utilities | 1 | Baseline 3-table pattern established |
| 02 | Europe PMC | REST + fullTextXML | 1 | OA full text is an independent versioned artifact, not a metadata field |
| 03 | ClinicalTrials.gov | API v2 | 1 | `--intervention` lookup added proactively for later Job 15 reuse |
| 04 | Crossref | `/works/{doi}` | 1 | DOI-exact reconciliation only — free-text search verified unusable for discovery |
| 05 | SEC EDGAR | submissions API | **3** | Multi-CIK companies, exhibit typing, resume-cursor failure-safety hardened over 3 rounds |
| 06 | FDA | label search + Drugs@FDA | 2 | 3-level model (application→submission→document); discovery-before-reconciliation |
| 07 | EMA | bulk medicines + EPAR JSON | 2 | Metadata-driven incremental fetch (avoid re-downloading PDFs just to hash-compare) |
| 08 | WIPO | EPO OPS (PATENTSCOPE has no API / ToS forbids automation) | **3** | Checkpoint/version durability ordering hardened across 3 rounds |
| 09 | USPTO | Open Data Portal | 1 | Full-spec free-text search; mutable content (always refetch+hash-compare) |
| 10 | EPO | EPO OPS (shared client w/ WIPO) | 1 | Disclosed gap: `pn=EP` title-phrase search 500s at 3+ terms — abstract-only fallback |
| 11 | Company pipelines | curated registry, scrape | 1 | AbbVie Cloudflare-blocked (documented, not bypassed) |
| 12 | Company press releases | curated registry, scrape | 1 | Backlog-resurrection independent of live pagination reach |
| 13 | Patent bioactivity corpus | EPO OPS description/claims | 1 | Round-1 corrected an "OPS full text is EP-only" overreach from n=1 — WIPO actually 95% available |
| 14 | Publication bioactivity corpus | Unpaywall + Europe PMC + NCBI ID Converter | 1 | Round-1 added PMID/PMCID-only coverage (was silently DOI-only, dropping ~35% of real records) |
| 15 | Known-ADC asset expansion | orchestrates Jobs 01/02/03/08/09/10 in-process | 1 | No content manifest of its own; exception-safe isolation of resume-cursor/report state from the broad-discovery pass |

**13/15 jobs approved in 1 review round; 2 needed 3 rounds (WIPO, SEC) to fully harden checkpoint/durability ordering.**

## 5. Cross-cutting hardening themes (recurring bug classes, fixed each time they resurfaced)

- **"Discovered ≠ resolved"** — a bounded/early-terminating discovery walk must not gate retry-eligibility (recurred 5×: SEC, FDA, EMA, WIPO/EPO, company press releases).
- **Checkpoint/manifest durability ordering** — a raw write must be checkpointed to disk *before* parsing/materialization, not after (WIPO rounds 1–3, USPTO round 1).
- **"Attempt broadly, don't generalize from n=1"** — Job 13 wrongly excluded all WIPO patents from an EPO OPS full-text query after testing one WO publication; Job 14 repeated the lesson at OA-location granularity (try every URL a location offers, not just "best").
- **Truthful status/provenance fields** — never fabricate an HTTP status or reuse a `query_id` for a materially different `query_text` (recurred: Job 12, Job 13, Job 14, Job 15).
- **Exception-safe isolation** — when one job's state must not leak into another's (Job 15 calling 6 other jobs' classes in-process), restoration must happen in `finally`, not sequential code.

## 6. Known, disclosed limitations (not silent gaps)

- WIPO/EPO: EP-prefixed title-phrase search unsupported at 3+ terms (OPS server bug) — abstract-only fallback, ~135 EP publications with title-only phrase matches not discovered.
- FDA: approved products only; safety communications / never-approved submissions not covered.
- EMA: PSUSA/DHPC safety-specific feeds not covered.
- Company pipelines: Seagen/ImmunoGen/Mersana absorbed (no standalone page); AbbVie blocked by Cloudflare.
- Company press releases: Zymeworks' IR subdomain entirely unreachable.
- Job 13: USPTO not duplicated (its SPEC documents already bundle full text).
- Job 14: some OA copies unreachable in practice (e.g., a Wiley landing page 403); many older (pre-DOI-era) records have no PMC/DOI mapping at all.
- Job 15: `moxetumomab_pasudotox` excluded from the strict-ADC registry (NCI classifies it as a recombinant immunotoxin, not a classic linker+payload conjugate); live verification used a 2-of-14-asset subset to bound API/OPS quota consumption per review round (full-registry runs are expected to take substantially longer).

## 7. Testing & verification

- 401 automated tests (fully HTTP-mocked, `responses` library) — reproducible offline.
- Every job additionally **live-verified against its real external API** at least once before merge (not just mocks) — several real bugs (OPS zero-hit-returns-404, NCBI ID Converter's int/string pmid mismatch, a missing `--refresh` attribute in a hand-built Namespace) were only findable this way, not via unit tests alone.
- Real evidence of live runs (small, demo-scale) is committed under `DATA/manifests/*.parquet` for inspection.

## 8. Questions for reviewer consideration

1. Does the three-table + query-provenance + checkpoint/versioning contract look sufficient for a system whose next stage (not built here) will be knowledge extraction over this raw evidence?
2. Are the disclosed limitations (§6) acceptable as documented gaps, or do any represent a blocking correctness risk for downstream use?
3. Any structural/architectural risk visible from this summary that per-job PR-level review might have missed by construction (i.e., a cross-job interaction, not a within-job bug)?
