# ADC Breadth Layer — Plan

This plan responds to the finding of `reports/validation/nar_adcdb_comparison.md`
(PR #17, pending review): known-asset acquisition *depth* is proven, but the
project has never measured or built for *breadth* — the size of the ADC
feasibility universe it can discover independent of a curated seed list. This
document is the required Phase 0 deliverable before any breadth-layer code is
written (per workflow discipline: inspect first, plan, then implement in
small reviewed phases). It is descriptive of current state and intended
sequencing — not itself a code change.

## 1. Current measurable baseline

Confirmed by direct inspection of this repository and the external NAR vault
on 2026-08-20 (branch `breadth-plan`, off `main` @ `b998e26`):

- **15 acquisition jobs implemented** (`jobs/`): pubmed, europe_pmc,
  clinicaltrials, crossref, sec, fda, ema, wipo, uspto, epo, company_pipeline,
  company_press_release, patent_bioactivity_corpus,
  publication_bioactivity_corpus, known_adc_asset_expansion. All literature/
  clinical-trial/patent/regulatory/company sources. **Zero conference sources**
  (no AACR/ASCO/ESMO job or adapter exists anywhere in `jobs/` or `tools/`).
- **`configs/known_adc_assets.yaml`**: 15 curated assets, 14 `active: true`.
  This is the entire targeted-lookup seed list — confirmed by the prior audit
  to already have deep multi-source evidence for all 14, so per-asset depth
  is not the open problem.
- **No breadth/discovery-candidate infrastructure exists**: no
  `DATA/reference/`, no `DATA/feasibility/`, no `tools/breadth/` or
  `adc_acquisition/breadth/`, no candidate-queue concept, no target/linker/
  payload/platform entity model anywhere in the codebase. Every existing job
  is asset- or query-driven, not entity-discovery-driven.
- **`tools/validation/compare_nar_adcdb.py`** (from PR #17) already contains
  reusable primitives: NAR markdown table parsing (`_parse_general_info_table`,
  regex-based, tolerant of Obsidian wikilink cell values), discovery-ledger
  loading across all `*_discovery.parquet` files, DOI/NCT normalization, and
  full-text raw-file search. This is the parsing foundation for Part 1/2, not
  a rewrite.
- **External NAR vault inventory** (`ADCdb_Obsidian/`, read-only, confirmed
  untouched): `ADCs/` 6,235 files (702 phase-tagged, established previously),
  `Antibodies/` 1,380 files, `Payloads/` 521 files, `Linkers/` 587 files,
  `Antigens/` 316 files (antibody binding targets — what NAR calls "Antigen
  Name" on an ADC page), `Targets/` 52 files (**a distinct, separate concept**:
  the payload's mechanism-of-action target, e.g. BCL2L1 — confirmed by
  direct read, matches the "Antigen Name vs Therapeutic Target" distinction
  already documented from the prior audit). Antigen/Payload/Linker/Antibody/
  Target pages carry their own `entity_id` (e.g. `TAR0YVQUD`, `PAY0RDAOD`,
  `LIN0DBDYG`, `ANTI0ECLLM`, `PATR0EDEOC`) and backlink to the ADC page(s)
  that reference them — this makes them usable as NAR's own component
  reference tables (Part 1), not something we have to re-derive from free
  text.
- **406 tests passing** as of `main` @ `b998e26`.

## 2. Exact missing capabilities (mapped to the prompt's 19 parts)

| # | Capability | Status |
|---|---|---|
| 1 | NAR reference universe extraction (assets + 5 component tables) | Missing — parser exists in `compare_nar_adcdb.py` for assets only; component pages (Antigen/Antibody/Payload/Linker/Target) never parsed |
| 2 | Broad-discovery vs targeted-recovery recall split | Missing — prior audit only measured targeted recovery for the 14 curated assets |
| 3 | Miss-pattern taxonomy for NOT_DISCOVERED assets | Missing |
| 4 | Feasibility entity model (candidate/target/antibody/linker/payload/platform/indication) | Missing entirely — no schema, no storage format |
| 5 | ADC_PLATFORM taxonomy + STRICT_ADC/ADC_PLATFORM/ADJACENT_CONJUGATE_MODALITY distinction | Missing |
| 6 | Conference ingestion (AACR/ASCO/ESMO) | Missing — highest-priority new source per the prompt |
| 7 | Company scientific-presentation source (R&D day / IR science pages) | Missing — `company_pipeline`/`company_press_release` cover pipeline pages and press releases only, not presentation/poster archives |
| 8 | Patent-derived breadth entity mining (new candidate/target/linker/payload/platform mentions) | Missing — existing patent jobs acquire raw documents only, no entity-mention extraction |
| 9 | Candidate queue with validation_status lifecycle | Missing |
| 10 | target × indication feasibility table | Missing |
| 11 | Component feasibility tables + NAR/ours-only classification | Missing |
| 12 | Twice-monthly delta/update command | Missing — no `update_breadth` orchestration, no delta-snapshot mechanism |
| 13 | Tier A/B/C prioritization of delta output | Missing |
| 14 | Six freeze gates, re-run against real numbers | Not yet evaluable — depends on 1–3 |

## 3. Implementation phases

Per the prompt's own required priority order (Part "WORKFLOW DISCIPLINE"),
each phase below is one PR, gated on explicit APPROVE before the next phase
starts — same discipline as every prior job in this project.

**Phase 1 — NAR reference universe + broad-discovery recall (Parts 1–2)**
Build `DATA/reference/nar_adcdb/{assets,targets,antibodies,payloads,linkers,
indications}.tsv` from the vault (read-only, reproducible script, not
committing raw vault content). Extend the 702-asset extraction already proven
in `compare_nar_adcdb.py`. Then measure **broad discovery recall**: for each
of the 702 NAR assets, check whether *generic* ADC-discovery evidence
(queries that do not name the asset) already surfaced it in our discovery
ledgers, using aliases/dev-codes only for post-hoc matching — never injected
into the query being evaluated. Produce `reports/validation/breadth/
nar702_broad_recall.tsv` and `nar702_targeted_recovery.tsv`, with recall
broken out by phase bucket (Approved/Phase3/Phase2/Phase1/Investigative).
This phase produces the load-bearing number the rest of the plan depends on
and must land before anything else.

**Phase 2 — Close systematic broad-discovery misses (Part 3)**
Root-cause every meaningful NOT_DISCOVERED asset from Phase 1 into the
prompt's taxonomy (MISSING_QUERY_TERM, PATENT_ONLY, CONFERENCE_ONLY, etc.),
aggregate into `broad_miss_taxonomy.tsv`, and only patch production queries
where a *repeated* pattern proves a systematic gap — same evidence-gated rule
already used for the Polivy fix. One-off misses get documented, not patched.

**Phase 3 — Feasibility entity + candidate-queue schema (Parts 4, 9)**
Define the entity model (`ADC_CANDIDATE`/`ADC_TARGET`/`ADC_ANTIBODY`/
`ADC_LINKER`/`ADC_PAYLOAD`/`ADC_PLATFORM`/`ADC_INDICATION`) and the
two-stage `DISCOVERY CANDIDATE → VALIDATED FEASIBILITY ENTITY` promotion
pipeline, backed by evidence already in `DATA/manifests/*` and discovery
ledgers — no new sources needed yet. This turns existing raw evidence into
counted, provenance-preserving entities for the first time.

**Phase 4 — Conference ingestion (Part 6)**
Before any new download: search this project and local data for reusable
historical AACR/ASCO/ESMO corpora. Then build the incremental adapter/job.
Highest new-source priority per the prompt (AACR >> ASCO/ESMO), since
preclinical/early-seed ADCs most often first appear here and nowhere else.

**Phase 5 — Component/platform discovery (Parts 5, 7, 8, 10, 11)**
ADC_PLATFORM taxonomy; company scientific-presentation source (official
domains only, reusing the company registry); patent-derived breadth mining
for new candidate/target/linker/payload/platform mentions; full component
tables (`DATA/feasibility/adc_{assets,targets,linkers,payloads,platforms,
antibodies,indications}.tsv`) and `target_indication_feasibility.tsv`.

**Phase 6 — Twice-monthly delta system (Parts 12–13)**
`update_breadth` orchestration command, snapshot-diffed delta tables under
`reports/delta/YYYY-MM-DD/`, Tier A/B/C prioritized `ADC_BREADTH_DELTA.md`.
Never silently overwrites historical evidence — same immutability discipline
as the existing three-table acquisition architecture.

**Phase 7 — Final breadth benchmark + freeze decision (Parts 14–19)**
Re-run the NAR comparison against the completed breadth layer, evaluate all
six gates explicitly with real numbers, answer all 15 required questions in
`reports/validation/breadth_closure.md`, and issue one verdict:
`READY_TO_FREEZE_ACQUISITION_V1` or `NOT_READY_TO_FREEZE_ACQUISITION_V1`.

## 4. Acceptance gates (restated from the prompt, evaluated only in Phase 7)

1. **NAR reference coverage** — ≥95% of the 702 phase-tagged assets are
   BROAD_DISCOVERED or TARGETED_RECOVERABLE, reported separately.
2. **Approved assets** — 100% recognized/recoverable unless a documented
   ontology exclusion applies (e.g. the existing moxetumomab_pasudotox
   immunotoxin exclusion).
3. **Component breadth** — feasibility universe contains at least all
   reliably extractable NAR targets/payloads/linkers, mapped explicitly where
   NAR's own Antigen-vs-Target distinction requires it.
4. **Ours-only value** — a non-trivial, provenance-preserving set of entities
   absent from NAR (post-cutoff assets, new targets/payload/linker/platform
   entities, conference-only/preclinical entities).
5. **Incremental update** — two controlled delta runs demonstrate stability,
   correct append-only behavior, no duplication, visible/retryable failures.
6. **Precision** — stratified audit of candidate promotions, reported
   separately per entity type (asset/target/linker/payload/platform).

## 5. Explicit non-goals for this phase (Part 16)

Deep IC50/DAR/toxicity/PK-PD/clinical-endpoint extraction, mechanism-of-action
reasoning, final claim arbitration, and therapeutic-window scoring are all
out of scope until breadth is closed. Depth work does not begin before Phase
7's freeze decision.

---

Next step: Phase 1 implementation, as its own PR, per this plan.
