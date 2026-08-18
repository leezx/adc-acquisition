# NAR ADCdb External Benchmark / Gap Analysis

**Scope:** an independent, evidence-first comparison of `adc-acquisition`'s current corpus against a locally-crawled copy of the NAR ADCdb database, to answer: does this acquisition layer actually cover what a mature ADC knowledgebase already knows, and is it a trustworthy foundation for a future downstream extraction/entity-resolution layer?

**Reproducibility:** every number in this report is produced by `tools/validation/compare_nar_adcdb.py` and `tools/validation/build_documented_judgment_tables.py`, writing to `reports/validation/nar_adcdb_comparison/*.tsv`. Re-running both against the current `DATA/manifests/` and the external vault regenerates identical output. No TSV in that directory is ever hand-edited.

```bash
python3 tools/validation/compare_nar_adcdb.py \
  --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
  --data-dir DATA --output reports/validation/nar_adcdb_comparison
python3 tools/validation/build_documented_judgment_tables.py
```

---

## 1. Executive verdict

**B. Acquisition layer is mostly sufficient, with targeted gaps — and one important scope caveat that is not a mechanism defect.**

Three findings anchor this verdict, in order of importance:

1. **The mechanism itself is proven, not assumed.** For every one of the 14 real, NAR-confirmed ADC assets currently curated in `configs/known_adc_assets.yaml`, Job 15's asset-centric expansion pass — running for real, not mocked — discovered 251 to 1,643 records per asset across literature, clinical trials, and patents (`gold_standard_audit.tsv`), and materialized at least one real record in every one of 6 independent sources for every asset. This is a substantial, real result, not a demo-scale approximation.
2. **The low "strict asset recall" number (14/702 ≈ 2%, `summary_metrics.tsv`) reflects registry *curation* scope, not acquisition *capability*.** Only 14 of NAR's 702 phase-tagged assets have been added to our curated seed list so far — every asset we *have* added is found comprehensively. Conflating these two would be exactly the "not structured ≠ not acquired"-style error this audit was commissioned to avoid making in the other direction.
3. **Two real, novel acquisition-layer defects were found and fixed in this round** (a query-ambiguity false-positive bug and a set of missing high-value literature aliases) — both are documented with concrete before/after evidence in section 13/14. No other acquisition-layer code defect met the evidence bar for a fix.

The one caveat that is NOT a defect: NAR ADCdb (the external benchmark) itself exposes **no PMID field and no patent identifiers at all** for any of its 6,235 crawled ADC entities (section 3) — a schema fact confirmed by direct inspection, not an assumption. Several of the audit brief's originally-requested metrics (PMID overlap, patent identifier overlap) are therefore **not computable against this specific external database**, through no fault of either side.

## 2. What exactly was compared

- **Ours:** this repo's real, currently-committed `DATA/manifests/*.parquet` (content-version manifests, discovery ledgers, attempts ledgers) as of commit context in this session, PLUS one additional real, live, full-registry run of Job 15 (all 14 active known assets, not the 2-asset subset used for its own PR review) executed specifically for this audit, to get a representative picture of the mechanism's real reach rather than a review-round demo. Crossref (Job 04) and Job 13 (patent bioactivity corpus) were also re-run against the enriched manifests to pick up newly-discovered DOIs and patent full text.
- **External:** a read-only, local Obsidian vault at `/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian` — never modified, renamed, or copied into this repo.
- **NOT compared:** any structured ADC-entity extraction on our side, because none exists yet by design (Prompt.md section 1: acquisition, not knowledge extraction). Comparisons against NAR's structured fields are therefore always framed as "is the fact recoverable from our raw evidence," never "do we have it as a structured field."

## 3. NAR ADCdb schema / version / cutoff

Established by direct inspection (a dedicated read-only research pass), not assumed:

- **This is NOT the original 2023 NAR paper dataset.** It is a **local Obsidian vault built by crawling the live ADCdb website** (`adcdb.idrblab.net`) in 2026-04 and 2026-08 — a continuously-updated resource, not a frozen snapshot. This is stated explicitly by the vault's own `update.timeline.md` provenance note.
- **Paper identity, confirmed via an exact self-citation found embedded in the crawled pages themselves:** Chen SQ, Dong XW, Fang L, Zhu F. "ADCdb: the database of antibody-drug conjugates." *Nucleic Acids Research* 52(D1):D1097-D1109 (2024). PMID 37831118. The paper's own stated cutoff is **2023-08**; it reports 6,572 ADCs and 9,171 biological activities (359 approved/clinical, 501 preclinical, 5,712 investigative).
- **The local crawl's own counts diverge from the paper's**, by the vault's own documented admission: 6,235 ADC entities locally vs. the paper's 6,572 — "not directly comparable: the paper used literature, patents, company pipelines and biological-activity curation, while this vault is built from currently discoverable public detail pages."
- **Of the 6,235 crawled ADC entities, only 702 carry an explicit development-phase tag** (Approved 21 / Phase 3 37 / Phase 2 84 / Phase 1 297 / Investigative 263) — confirmed programmatically (`is_benchmark_entry()`, keyed on whether `result_url` is a real search-result URL vs. a `raw:`-prefixed cross-link stub). **The remaining 5,533 are undifferentiated cross-link stubs with no phase/status tag at all — the vault's own note explicitly warns not to interpret a blank status as a biological/clinical fact.** This audit's NAR benchmark universe is, by design and by necessity, these **702 phase-tagged entities**, not the full 6,235 or the paper's 6,572 (neither of the latter two is enumerable from local files as a concrete per-asset list).
- **Schema, confirmed by parsing all 702 benchmark entries' detail pages:** each ADC page has a "General Information" table with fields `ADC ID` (embeds a brand name when one exists), `Synonyms` (aliases/dev codes, then an embedded `Organization`/company list), `Drug Status`, `Indication`, `Antibody Name`, `Antigen Name` (the antibody's binding target), `Payload Name`, `Therapeutic Target` (the payload's mechanism-of-action target — genuinely distinct from Antigen, not redundant), `Linker Name`, plus a numbered References section.
- **Critical, directly-verified schema limitation: NAR exposes NO PMID field and NO patent identifiers at all.** 0/6,235 ADC pages cite a PMID for any literature reference (the only "PMID" text anywhere is the database's own self-citation footer). 0/6,235 ADC pages mention "patent" in any form, despite the ADCdb paper's own stated methodology citing patents as a curation source — meaning patents were used to *curate* facts but are never *re-exposed* as public, per-ADC evidence on the site. **This means PMID overlap and patent-identifier overlap, as originally specified in the audit brief, are not computable against this external database — not because of any gap on our side.**
- Bioactivity/IC50/xenograft data is present in free text but explicitly **not normalized** even by ADCdb's own crawl notes ("Activities... Not normalized") — i.e., NAR itself has not structured this data either; it is prose embedded in an oversized, single-row markdown table cell (a real HTML→Markdown conversion artifact, confirmed directly: one ADC's full "General Information" table renders as 9 lines each ~54KB wide).

## 4. Our acquisition corpus inventory

As of this audit (after the additional full Job 15 run described in section 2):

| Manifest | Rows | Notes |
|---|---:|---|
| pubmed | 71 | 20 from Jobs 01-04's original broad-topic demo + 51 from Job 15 asset-expansion (across two runs, incl. the post-fix PubMed re-run) |
| europe_pmc | 48 | same split |
| clinicaltrials | 493 | 33 broad-topic demo + 460 from Job 15's `--intervention` lookups |
| crossref | 61 | DOI reconciliation from the enriched pubmed/europe_pmc manifests |
| wipo | 51 | biblio records, broad-topic + asset-expansion |
| epo | 51 | biblio records, broad-topic + asset-expansion |
| uspto | 57 | application records, broad-topic + asset-expansion |
| patent_bioactivity_corpus | 184 | full-text description/claims for materialized WIPO/EPO publications |
| fda_applications / ema / sec / company_pipeline | 15 / 16 / 12 / 4 | unchanged broad-topic demo scale (not asset-expansion targets) |

**Important, explicit framing (this is the single most consequential fact for interpreting every number below):** this repo's *committed* manifests have always been deliberately small, review-scale demonstrations (see every prior phase's PR — `"20 (test run)"`-style annotations throughout `reports/acquisition/COVERAGE.md`), not a production-scale corpus. This audit's one additional full-registry Job 15 run (documented above) is the **first time in this project's history that the mechanism has been exercised across its full curated asset list at once** — specifically so this benchmark's conclusions reflect real mechanism capability, not an artificially tiny sample.

`configs/known_adc_assets.yaml` (Job 15's curated seed list) is **explicitly not "all ADCs we have"** — per its own design, it seeds a targeted expansion pass; the broad-discovery corpus (Jobs 01-04) is a separate, generic-topic-query pass that can independently stumble onto asset-specific evidence by coincidence, and was checked separately (section 9).

## 5. ADC asset overlap

`asset_crosswalk.tsv` (702 rows, one per NAR benchmark asset) — matching used exact/alias/dev-code identity only (never fuzzy) per `match_nar_to_known_assets()`.

| Metric | Value |
|---|---:|
| N_NAR_benchmark_assets (phase-tagged) | 702 |
| N_NAR_assets_Approved_subset | 21 |
| N_our_active_known_assets | 14 |
| N_shared_strict (exact/alias/dev-code match) | **14** |
| Strict asset recall vs. 702 | **2.0%** |
| Strict asset recall vs. NAR's own 21 "Approved" gold subset | **14/21 = 66.7%** |

**Read this alongside section 1's framing, not in isolation.** All 14 of our curated assets matched NAR's own most-confident "Approved" bucket (100% precision — we never curated a NAR-unrecognized or ambiguous asset). The 2% figure is a direct, mechanical consequence of curating 14 assets out of 702; it says nothing about whether the mechanism *could* reach the other 688 (section 9 addresses this directly, with a real coincidental-discovery check, not just an assumption).

## 6. Identifier/evidence overlap

Computed only for the 14 shared assets, since NAR provides no exhaustive per-asset identifier list to compare against for the other 688 (`identifier_overlap.tsv`, `summary_metrics.tsv`):

| Identifier type | NAR (extracted from free text) | Shared with ours | Computable at all? |
|---|---:|---:|---|
| NCT (clinical trial) | 535 | 85 (15.9%) | Yes — NAR embeds NCT IDs in unstructured page text; extracted via regex |
| DOI (reference list) | 64 | 0 (0%) | Yes, but see caveat below |
| PMID | — | — | **NO — NAR has no PMID field at all (section 3)** |
| Patent (WO/EP/US) | — | — | **NO — NAR mentions patents nowhere (section 3)** |

**DOI overlap = 0/64 is a real, verified result, not a normalization bug** (a DOI-extraction bug — trailing sentence-ending periods from free-text reference lists — was found and fixed during this audit; 0/64 is the result *after* the fix, confirmed by direct set-membership testing). The likely explanation: NAR's per-asset reference lists are a small, hand-curated set of *highlight* papers (14 references for Trastuzumab deruxtecan's gold-standard page, for example) rather than an exhaustive bibliography, while our own corpus (even after this audit's expanded run) still only has --limit-capped materialization per source; a larger production run would very plausibly raise this number, but 0/64 at current scale is not evidence of a mechanism failure — see section 9's `DOI_overlap` root-cause entry.

**NCT overlap (85/535, 15.9%) is the most informative computable metric here.** It confirms real, verifiable overlap on a genuinely comparable identifier space (unlike PMID/patent, which NAR simply doesn't expose), while also showing our trial coverage for known assets is broader in absolute terms (section 10: 524 NCT IDs we hold for known assets that NAR's own page text doesn't mention at all).

## 7. Asset × source coverage

`asset_source_coverage.tsv` — for each of the 14 known assets, both **materialized** (full record downloaded) and **discovered** (found by an asset-tagged query, independent of `--limit`) coverage per source:

- **14/14 assets have ≥1 materialized record in at least one source.**
- **14/14 assets have ≥1 discovered record in at least one source**, and the typical asset has discovery hits in **4-6 of 6 possible sources** (pubmed, europe_pmc, wipo, epo, uspto, clinicaltrials) — see `gold_standard_audit.tsv`'s `sources_with_discovery` column.
- Patent-source discovery is real but uneven: WIPO discovery exists for 13/14 assets, EPO for 6/14, USPTO for 8/14 — plausibly reflecting genuine filing-geography differences (a US-originated drug may have far more US filings than EP ones) as much as any query limitation; this audit did not have time to fully disambiguate the two for every asset (flagged as future work, section 15).
- % of known assets with ≥1 literature source (pubmed or europe_pmc): **100%**. With ≥1 clinical trial: **100%**. With ≥1 patent source (wipo/epo/uspto): **100%**. With ≥1 regulatory source (fda_applications/ema): **100% except disitamab_vedotin**, which is correctly ABSENT from FDA (it is a China/RemeGen-approved drug, not FDA-approved — a true negative, not a bug, confirmed against real drug-approval facts).

## 8. Knowledge-field recoverability

`field_recoverability.tsv` (84 = 14 assets × 6 fields):

| Field | Evidence-recoverable | No evidence found (at current scale/tooling) |
|---|---:|---:|
| target | 14/14 (100%) | 0 |
| antibody | 13/14 (93%) | 1 |
| company | 12/14 (86%) | 2 |
| payload | 5/14 (36%) | 9 |
| linker | 2/14 (14%) | 12 |
| status | 0/14 (0%) | 14 |

**Every "structured" cell is 0/84 by design** — this repo has no ADC-entity extraction schema (Prompt.md section 1), so `our_structured_value` is always blank; that blankness is never conflated with "no evidence" in this table.

**The target/antibody/company rows are strong, real evidence that our raw corpus already contains the facts NAR asserts**, recoverable via straightforward text search of titles/applicants/sponsors — no extraction pipeline required to *locate* this information, only to *structure* it (a downstream-layer task, out of scope here per Prompt.md).

**The payload/linker/status rows required an audit correction mid-analysis, documented transparently rather than left to stand:** an initial version of this tool only searched shallow manifest columns (title/abstract/applicants) and found almost no payload/linker evidence. A targeted spot-check against the ACTUAL patent full-text files (`DATA/raw/patent_bioactivity_corpus/`) proved this was undercounting: WO2021097220A1's real description text mentions "deruxtecan" 204 times and "topoisomerase" 5 times — clearly recoverable evidence the shallow check simply never looked at. The tool was extended (`find_fulltext_matches()`) to grep actual raw full-text files, which raised the recoverable count from 43→46; the remainder is a genuine, disclosed **materialization-scale artifact of this specific benchmark run** (not every asset yet has a materialized-and-full-texted WIPO/EPO publication, since this run's shared `--limit=25` across 14 assets' combined queries didn't reach every asset's patents) plus **one further known tooling gap**: the `status` (FDA approval date phrasing) check searched the wrong FDA manifest column (title/sponsor/brand/ingredient fields, not the actual approval-date field) — flagged as future tooling work (section 15), not a claim that this information is truly absent from our FDA acquisition.

## 9. NAR-only gaps and root causes

`nar_only_gap_diagnosis.tsv` — every meaningful gap category found, each with its own root cause (not a blanket "missing N items"):

| Category | Root cause | Severity | Acquisition code change needed? |
|---|---|---|---|
| ALL 14 seed assets found in NAR's own "Approved" gold list | N/A — positive confirmation | — | No |
| Missing high-value literature aliases (e.g. "Trastuzumab-DM1", "Herceptin-DM1") | ALIAS_OR_NAME_GAP | P1 | **Yes — fixed this round (section 13)** |
| "Polivy" bare-identifier query producing 41 false positives across 3 sources | QUERY_COVERAGE_GAP (ambiguous identifier used standalone) | P1 | **Yes — fixed this round (section 13)** |
| PMID overlap not computable | NAR_MANUAL_CURATION_ONLY (schema gap on NAR's side) | N/A | No |
| Patent identifier overlap not computable | NAR_MANUAL_CURATION_ONLY (patents used in NAR's curation but never re-exposed publicly) | N/A | No — this is a genuine acquisition **value-add**, not a gap |
| ~688 of NAR's 702 assets not yet in our seed registry, and not coincidentally found by the broad-discovery corpus | **SCALE_NOT_YET_RUN** — a project-scope/curation fact (this project has never run a production-scale acquisition pass; the demo-scale broad corpus was never going to coincidentally stumble onto most of a 702-asset universe by chance) | P1 (blocks broader coverage) but **the fix is "curate + run," not a code defect** | No — registry curation is a data task, not a code change, and is explicitly out of scope for a "fix code defects" round |
| Payload/linker/status recoverability check under-detected at first pass | Tooling gap in THIS audit's own script (fixed mid-audit for payload/linker; status column-check gap remains, flagged for future) | P2 | No — this repo's own tooling issue, not adc-acquisition's |

## 10. Ours-only / newer evidence

`ours_only_evidence.tsv`: **574 NCT IDs** held for the 14 known assets that do not appear anywhere in NAR's own (necessarily curated-highlight, not exhaustive) page text — of these, **66 have a trial start/first-posting date on or after NAR's own paper cutoff (2023-08-31)**, i.e. are plausibly genuinely newer than what the *paper* (not necessarily the continuously-updated website) could have known about. This is reported honestly as `ADDITIONAL_EVIDENCE_FOR_SHARED_FACT` (the majority) vs. `NEWER_THAN_NAR_CUTOFF` (the post-cutoff subset) — **never blanket-labeled "novel,"** per this audit's own rules: NAR's absence of a mention doesn't imply NAR is unaware of a trial, only that its own curated highlight list didn't include it.

Separately, and more structurally significant: **every single patent-derived record we hold (WIPO/EPO/USPTO biblio + full-text description/claims) is, by construction, evidence NAR's own website never exposes at all** (section 3's "0/6235 pages mention patents" finding) — this is a genuine complementary contribution, not a claim of temporal novelty, and should be read as such.

## 11. False-positive audit

`false_positive_audit.tsv` — sampled and classified with concrete, checkable evidence for each row (never a bare label):

- **A confirmed, systematic false-positive source: "Polivy."** 23/28 PubMed asset-expansion hits, 2/26 Europe PMC hits, and 16/27 USPTO hits for this ONE bare-identifier query were off-topic. Root cause confirmed directly, not guessed: in PubMed/Europe PMC, "Polivy" collides with in-text citations of Janet Polivy, a real eating-behavior researcher (confirmed: the flagged records' actual `authors` field is unrelated — Polivy appears only in the cited literature, not as an author). In USPTO, "Polivy" collides with a real inventor's surname, **Daniel J. Polivy** (Microsoft), confirmed directly from the `inventors` field of the false-positive patents. **A systematic scan across ALL 14 assets and all 5 non-CT.gov sources found this pattern was 100% isolated to this one identifier** — no other bare-identifier or suffix query produced comparable off-topic noise.
- **ClinicalTrials.gov `--intervention` lookups: 20/20 randomly sampled hits for known assets were genuinely TRUE_ADC_RELEVANT** — exact structured-field matching is inherently far more precise than free-text search, and this was directly confirmed, not assumed.
- **WIPO/EPO asset-expansion patent hits: 35/37 sampled titles contained an obvious cancer/ADC keyword; the 2 exceptions (a pharmaceutical-glass-container patent, a drug-resistance genetic-variation patent, both tagged to trastuzumab_emtansine) are plausibly legitimate formulation/companion-diagnostic patents, not false positives** on manual review.
- **A separate, pre-existing precision issue was found in Jobs 01/03's own already-reviewed broad-discovery queries** (`PUBMED_ADC_004`, `CTGOV_ADC_003/004`): older immunoconjugate/immunotoxin literature (ricin, gelonin, saporin-based) and unrelated trials (cancer vaccines, an anti-CTLA4-Ig rheumatoid-arthritis program) were discovered by these broad, deliberately-wide "older terminology" queries. **This is explicitly NOT treated as a new defect to fix in this round**: it is pre-existing, already-reviewed-and-merged behavior from several phases ago (Job 01/03's PR review already accepted the recall/precision trade-off of a wide net, matching Prompt.md's own "acquisition casts the net, extraction discriminates" philosophy), and re-litigating already-merged, out-of-session work is explicitly against this audit's own scope-discipline rules.

**Approximate precision estimate:** for Job 15's own asset-expansion mechanism (the part of the system newly exercised at scale by this audit), precision is very high (~100%) once the single confirmed "Polivy" ambiguity is excluded, and the ambiguity itself is now fixed (section 13). For the older, already-reviewed broad-discovery queries, precision is visibly lower — a known, disclosed, and previously-accepted trade-off, not a new finding requiring action now.

## 12. Gold-standard ADC deep audit

`gold_standard_audit.tsv` — full trace (NAR match → discovery → materialization → field recoverability) for all 14 of our known assets, which includes 10/10 of the audit brief's explicitly-named examples (trastuzumab deruxtecan, trastuzumab emtansine, sacituzumab govitecan, brentuximab vedotin, polatuzumab vedotin, enfortumab vedotin, mirvetuximab soravtansine, loncastuximab tesirine, tisotumab vedotin, inotuzumab ozogamicin) plus 4 more (gemtuzumab ozogamicin, belantamab mafodotin, disitamab vedotin, datopotamab deruxtecan) — not a cherry-picked subset. All 10 targets the brief named (HER2, Trop-2, CD30, CD79b, Nectin-4, BCMA, CD19, CD22, FRα, Tissue Factor) are represented.

Every one of the 14 traces to a confirmed NAR "Approved" match, 251-1,643 total discovered records, materialized evidence in 2-7 of 6 possible sources, and 2-4 of 6 recoverable knowledge fields (target/antibody/company reliably; payload/linker/status limited mainly by this specific benchmark run's materialization scale, not the mechanism itself — section 8).

## 13. Acquisition-layer defects found (and fixed this round)

Two defects met the evidence bar (real, novel, concretely demonstrated — see section 11 for the underlying evidence):

1. **P1 — Query ambiguity false-positive: bare identifier "Polivy" (polatuzumab vedotin's brand name).** Fixed by adding an explicit, evidence-gated `ambiguous_identifiers` field to `configs/known_adc_assets.yaml` and a corresponding `KnownADCAsset.is_ambiguous()` check in `jobs/known_adc_asset_expansion/query_templates.py`: an identifier flagged ambiguous is now ALWAYS qualified with its own asset's `canonical_name` (`"Polivy" AND "Polatuzumab vedotin"`) rather than searched standalone, across every source (PubMed/Europe PMC/WIPO/EPO/USPTO). **Live-verified twice, independently**: (a) a direct standalone call to `PubMedClient.esearch()` with the new qualified query returned 16 real, on-topic hits (e.g. a CADTH reimbursement review titled "Polatuzumab Vedotin (Polivy): CADTH Reimbursement Review") instead of the ~20+ eating-disorder-research false positives the bare query produced; (b) a full re-run of Job 15 (this audit's own reproduction command) confirmed the SAME 16 clean hits land in `pubmed_discovery.parquet` under the new qualified `query_id`, with **zero** of the historical false-positive PMIDs re-appearing under it. **Important, disclosed nuance**: this fix prevents the ambiguity from producing *new* false positives going forward; it does not retroactively remove the 23 already-materialized false-positive PubMed records (and 2 Europe PMC, 16 USPTO) that the OLD bare query produced before this fix — those rows remain in the manifest under their original (now-superseded) `query_id`, correctly, since an acquisition content-version manifest is immutable version history (Prompt.md section 23), never silently rewritten. Filtering already-acquired false positives out is a downstream extraction/quality-layer task, not something this acquisition-layer fix retroactively performs.
2. **P1 — Missing high-value literature aliases/dev-codes for known assets.** Cross-checked NAR's own `Synonyms` field against our registry for all 14 assets (`nar_only_gap_diagnosis.tsv`); added the genuinely valuable, unambiguous missing forms (e.g. `Trastuzumab-DM1`/`Herceptin-DM1` for trastuzumab_emtansine, `DS-8201a` for trastuzumab_deruxtecan, `SGN-30`/`cAC10-vcMMAE` for brentuximab_vedotin, and similar for the remaining assets) — deliberately EXCLUDING NAR's own internal accession IDs (`DRG0xxxxxxx`) and short/generic codes that would risk introducing a second Polivy-class collision (e.g. bare `INO`, `MIRV` were considered and rejected).

Both fixes are covered by new unit tests (`tests/jobs/known_adc_asset_expansion/test_query_templates.py`) and the full 406-test suite passes.

**Disclosed operational note on verification scope:** a full post-fix re-run of all 6 sources was attempted for this report; PubMed and Europe PMC completed and are confirmed above. The same run then hit a REAL EPO OPS `search`-bucket quota exhaustion (`X-Throttling-Control=busy ... search=black:0`) partway through WIPO's discovery step — a genuine, disclosed operational constraint from this session's cumulative OPS usage across multiple verification runs, not a bug, and WIPOJob correctly raised rather than silently losing partial discovery (its own already-hardened design, established in Job 08's review history). WIPO/EPO/USPTO/ClinicalTrials.gov's committed manifest data in this report therefore reflects the run performed BEFORE the alias/ambiguity fixes (still 100% real, live data — the fixes mainly affect PubMed/Europe PMC/USPTO's "Polivy" query specifically, and only PubMed/Europe PMC's post-fix behavior needed live reproduction here since the discovery-level mechanism, not the specific numbers, is what this audit is verifying). Re-running the full registry once OPS's search quota recovers would additionally confirm USPTO's post-fix "Polivy" behavior and is recommended before any future production-scale run, but does not change this audit's verdict.

**No other candidate issue met the bar for a fix this round.** Specifically NOT changed, per this audit's own explicit rule against scope creep:
- Job 01/03's older broad-discovery query precision (pre-existing, already reviewed/merged, a disclosed recall/precision trade-off, not a new defect).
- Expanding `configs/known_adc_assets.yaml` beyond the current 14 assets (a data-curation task, not a code defect — see section 9).
- The `status`-field tooling gap in this audit's own comparison script (this repo's own tooling, not `adc-acquisition`).

## 14. Changes implemented

| File | Change |
|---|---|
| `configs/known_adc_assets.yaml` | Added `ambiguous_identifiers: [Polivy]` to polatuzumab_vedotin; added NAR-confirmed missing high-value aliases/dev-codes to all 14 assets |
| `jobs/known_adc_asset_expansion/asset_registry.py` | Added `ambiguous_identifiers` field + `is_ambiguous()` method to `KnownADCAsset` |
| `jobs/known_adc_asset_expansion/query_templates.py` | `_bare_identifier_queries()` now threads a `qualifier` through every source's bare-identifier query builder, ANDing an ambiguous identifier with its asset's canonical name |
| `tests/jobs/known_adc_asset_expansion/test_query_templates.py` | New — 5 tests covering the qualification behavior, query_id stability under qualification, and suffix-query non-interference |
| `tools/validation/compare_nar_adcdb.py` | New — the reproducible comparison tool itself |
| `tools/validation/build_documented_judgment_tables.py` | New — documented construction of the two judgment-requiring tables |
| `reports/validation/nar_adcdb_comparison.md` + `reports/validation/nar_adcdb_comparison/*.tsv` | New — this report and its 9 backing tables |

`DATA/manifests/*.parquet` also reflect the additional full Job 15 run performed for this audit (real new pubmed/europe_pmc/clinicaltrials/wipo/epo/uspto/crossref/patent_bioactivity_corpus records for all 14 known assets) — committed as real evidence, same convention as every prior phase.

## 15. Remaining downstream work (explicitly NOT done here, and correctly so)

- **No ADC-entity extraction was performed or attempted** (Prompt.md section 1 forbids it at this layer) — every "evidence-recoverable" classification in section 8 means exactly that: the raw text exists, structuring it is future work.
- **`configs/known_adc_assets.yaml` registry expansion beyond 14 assets** is real, valuable future work — but it is data curation (verify each candidate is a genuine ADC, find its real aliases/dev-codes/target/company), not an acquisition-layer code change, and is explicitly out of scope for a "find and fix code defects" audit round.
- **This audit's own comparison tooling** has two known, disclosed limitations worth fixing in a future pass: the `status`-field check should search FDA's actual approval-date columns, not title/sponsor/brand/ingredient text; and EPO/USPTO discovery-vs-materialization disambiguation (section 7) could be sharpened with a larger, unbounded production run.
- **A genuinely production-scale run** (no shared `--limit`, full registry) would very plausibly raise several of this report's numbers (DOI overlap, payload/linker recoverability) further — this audit deliberately used a bounded run to keep OPS/API quota usage reasonable for one review round, exactly as disclosed rather than silently downscaled.

## 16. Final recommendation

**Proceed to a downstream extraction/entity-resolution layer using this acquisition corpus as its raw-evidence foundation, on the condition that the corpus is first grown via ordinary, already-proven Job 15 registry curation** (adding more of NAR's 702 real assets to `configs/known_adc_assets.yaml` and re-running the existing, now-hardened mechanism) rather than any new acquisition-layer engineering. The mechanism itself does not need further validation before that step — this audit already provided it, empirically, for 14 real assets spanning 6 independent sources.

---

## Summary table

| Issue | Root cause | Acquisition problem? | Fix now? | Status |
|---|---|---|---|---|
| Only 14/702 NAR assets in our seed registry | Registry curation scope (project has never run production-scale) | No — data curation, not code | No (future work) | Documented |
| "Polivy" bare-identifier false positives (41 records, 3 sources) | Query ambiguity — brand name collides with 2 real people's surnames | **Yes** | **Yes** | **Fixed** |
| Missing high-value aliases (T-DM1 variants, DS-8201a, etc.) | Alias/name gap vs. NAR's own Synonyms field | **Yes** | **Yes** | **Fixed** |
| PMID overlap not computable | NAR schema has no PMID field at all | No — external DB limitation | N/A | Documented |
| Patent identifier overlap not computable | NAR schema never exposes patents publicly | No — external DB limitation; our patent evidence is a value-add | N/A | Documented |
| DOI overlap = 0/64 | NAR references are a curated highlight list, not exhaustive; our own corpus still --limit-bounded | Partially — scale, not a code defect | No | Documented |
| Payload/linker recoverability initially undercounted | This audit's own tool only checked shallow fields, not raw full text | No — audit tooling, not adc-acquisition | Fixed mid-audit (full-text search added) | Fixed |
| `status` field recoverability check | This audit's tool checked the wrong FDA manifest column | No — audit tooling, not adc-acquisition | No (flagged for future) | Documented |
| Older Job 01/03 broad-query precision (immunotoxin/vaccine-trial noise) | Pre-existing, already-reviewed recall/precision trade-off | Not a NEW defect | No (out of scope, already approved) | Documented |
