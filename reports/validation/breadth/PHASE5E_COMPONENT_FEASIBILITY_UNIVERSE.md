# Phase 5e — ADC_PLATFORM + Component Feasibility Universe

Per `reports/validation/BREADTH_PLAN.md` Phase 5 Parts 5/11. Explicitly
scoped per the reviewer's own instruction: **no new acquisition source,
no patent-derived breadth mining** (BREADTH_PLAN Part 8 remains deferred)
-- every entity in this phase is mined from evidence ALREADY sitting in
`DATA/manifests/*` from prior phases (conference abstracts, PubMed,
Europe PMC, Crossref, company scientific presentations).

## 1. Compliance with this round's explicit constraints

- **No new acquisition source added.** `git diff --stat` for this PR
  touches only `tools/breadth/*.py`, `tests/`, `DATA/feasibility/*.tsv`,
  and this report -- no `jobs/`, no `configs/*_queries.yaml`, no new
  manifest source.
- **No patent-derived mining attempted.** `epo`/`uspto`/`wipo`/
  `patent_bioactivity_corpus` manifests were not read by any script in
  this phase (confirmed: `tools/breadth/component_evidence.py` and
  `tools/breadth/feasibility_entities.py` only import from
  `conference_abstract_corpus`, `pubmed`, `europe_pmc`, `crossref`, and
  `company_scientific_presentations`).
- **ADC_TARGET vs PAYLOAD_MOA_TARGET split preserved.** `adc_targets.tsv`
  is untouched by this phase (still known-registry-only, unchanged
  schema/content). The new `payload_moa_targets.tsv` is a genuinely
  separate file/entity_type, never merged into or cross-referenced from
  `adc_targets.tsv`'s own rows.
- **Evidence-backed extraction only.** Every ADC_PLATFORM entity requires
  a literal, quoted keyword match in already-acquired text (see Section
  2). Every payload/linker tier upgrade requires either (a) independent
  public pharmacology for an asset already audited as a real antibody
  ADC in PR #17, or (b) a literal chemistry-name match in the SAME
  candidate's own local evidence context. Nothing is inferred from a
  name's shape or guessed.

## 2. ADC_PLATFORM mining (`tools/breadth/component_evidence.py`)

**Why a curated dictionary, not a generic rule.** A first attempt scanned
all already-acquired free text for `<capitalized token> platform|
technology` co-occurrences: 80 distinct pre-tokens, only ~35% genuine
platform brand names -- the rest generic English/abbreviations (`ADC`,
`DAR`, `IgG`, `CRISPR`, `ISAC`, `ATAC`, `This`, `The`, `Our`, `Novel`,
`Dual-payload TME-activated ADC`...). An automatic rule this noisy would
misclassify far too often for an evidence-gated project -- exactly the
same "naming-pattern-based rule considered and rejected as unsafe"
conclusion Phase 5b already reached for modality classification. So
every one of the 29 entries in `ADC_PLATFORM_KEYWORDS` was individually
verified by reading its real surrounding sentence:

| Platform | Real quoted evidence (abbreviated) |
|---|---|
| TMALIN | "This ADC was prepared using MediLink's TMALIN platform, a proprietary tumor microenvironment activable linker-payload platform" |
| GlycoConnect / HydraSpace | "the improved therapeutic index of ADCs obtained by GlycoConnect™ and HydraSpace™ Technologies" |
| SYNtecan E | "GlycoConnect™ ADCs based on topoisomerase 1 inhibitor exatecan (SYNtecan E™)" |
| ConjuAll | "LCB84 was prepared using ConjuAll, a proprietary site-directed conjugation technology of LegoChem Biosciences" |
| Dolaflexin / Dolasynthen / Immunosynthen / Synthemer / Fleximer | Mersana's 5 distinct named platforms, each independently found ("via the Dolaflexin ADC platform"; "The Dolasynthen platform..."; "leveraging our Immunosynthen platform"; "leveraged our Synthemer platform"; linker technology "Fleximer®") |
| SeriMab | "site-specific SeriMab antibody-drug conjugate (ADC) using an indolino-benzodiazepine DNA-alkylating agent" |
| EuCODE / C-LOCK | Ambrx's two named platforms ("Ambrx's site-specific EuCODE technology"; "our site-specific conjugation proprietary C-LOCK technology") |
| AxcynCYS, BrickADC, Mtoxin, PermaLink, MuSC, TMEAlinker, StarLinker, SMAC(TM), CROSSCONJU, ThioBridge, Azymetric, CAPAC, Nanolattix Biolattix, Ligase-Dependent Conjugation (iLDC), Tub-Tag, Conditionally Active Biologics (CAB) | Each individually verified the same way -- see `component_evidence.py`'s module docstring and the real scan output in this PR's description for the full quote per entry. |

**Explicitly excluded** even though found by the same scan, because they
are not conjugation/delivery technology (BREADTH_PLAN's own ADC_PLATFORM
definition is "a named proprietary conjugation/technology platform"):
`COMET` (Lunaphore's spatial-biology imaging platform), `GNOCLE`/`MIntTM`
(target-discovery engines), `OncoPanel`/`MiniPDX` (genomic-biomarker and
PDX-model platforms), `iScreener` (a screening platform, despite
incidentally mentioning "conjugation capability"), `Cancer DataMiner`
(a data-mining tool). Also excluded: bare `Araris` (a company name, not
a distinct branded term in the one abstract found), and bare `SYN`/
`SMAC`/`CAB` (collision-prone short forms -- only the disambiguating
fuller surface form, e.g. `SMACTM`, is matched, same
`ambiguous_identifiers` discipline `configs/known_adc_assets.yaml`
already established for "Polivy").

**Real numbers** (live scan of `conference_abstract_corpus`, `pubmed`,
`europe_pmc`, `crossref`, `company_scientific_presentations`):

```
adc_platforms.tsv: 29 entities
  3 VALIDATED (corroborated across >=2 independent evidence corpora):
    GlycoConnect (conference_abstract_corpus + europe_pmc, 23 records)
    SYNtecan E   (conference_abstract_corpus + europe_pmc, 11 records)
    ThioBridge   (conference_abstract_corpus + europe_pmc, 3 records)
  26 OBSERVED (single-source), e.g. TMALIN (14 records, conference only)
  297 total evidence mentions across all 29 entities
```

**`associated_adc_candidates` is deliberately always blank.** A
local-window co-occurrence attempt was tried during development and
caught a real false positive: abstract `aacr:2026:1689` ("Next generation
ConjuAll BCMA antibody-drug conjugates... LCB14-2524 and LCB14-2516")
also mentions "belantamab mafodotin" nearby purely as an unrelated
comparator drug in the background section -- proximity alone would have
wrongly linked ConjuAll (LegoChem's own platform) to a completely
different company's ADC. Reliable candidate-to-platform attribution needs
an explicit usage-verb pattern ("prepared using X", "leveraging its
proprietary X") tied to that SAME candidate's own name, not mere
co-occurrence -- out of scope for this narrowly-scoped phase; the
alternative (guessing the link) would violate this project's
evidence-gated discipline. Disclosed, not silently narrowed.

## 3. Payload/linker evidence-tier upgrade

Two independent upgrade paths from the existing `INFERRED`
(USAN/INN-suffix naming-convention) tier, both requiring positive
evidence, neither guessing a NEW payload/linker identity beyond the
existing 8-suffix map:

- **`VALIDATED`** -- a known-registry candidate's (14 active assets,
  `configs/known_adc_assets.yaml`) suffix-derived payload/linker. This is
  not a naming-convention guess: it is independently established public
  pharmacology for an FDA-approved/late-stage asset already audited as a
  real antibody ADC in PR #17.
- **`OBSERVED`/`TEXT_OBSERVED`** -- a NEW (Phase 3/5a-discovered)
  candidate's own evidence record explicitly names its payload/linker
  chemistry in the LOCAL context around that ONE candidate's own mention
  (`candidate_queue.local_context_for_span()`) -- never the whole record,
  same cross-contamination discipline as Phase 5b's round-1 fix (a
  regression test, `test_text_observed_payload_linker_false_when_
  chemistry_belongs_to_different_candidate`, confirms a different
  candidate's chemistry mentioned elsewhere in the same abstract does
  NOT leak into this one).

**Real numbers:**

```
14/14 known-registry candidates: payload VALIDATED, linker VALIDATED (all 14)
16/16 new candidates: payload/linker resolved via suffix (unchanged from Phase 3)
  11/16 upgraded to TEXT_OBSERVED payload (their own conference-abstract
        evidence explicitly names MMAE/MMAF/SN-38/exatecan/DXd/PBD dimer)
   5/16 remain INFERRED payload (no corroborating text found this phase)
  16/16 linker remains INFERRED (no linker-chemistry keyword found in any
        new candidate's local context this phase -- abstracts far more
        often state the payload than the specific linker chemistry;
        honest, not a bug)
```

Each `adc_payloads.tsv`/`adc_linkers.tsv` row's `evidence_sources` column
lists every distinct tier actually contributing (e.g. `TEXT_OBSERVED;
USAN_INN_NAMING_INFERENCE; VALIDATED_KNOWN_ASSET` for MMAE), so the tier
mix behind an entity's rolled-up `status` is never hidden.

## 4. `payload_moa_targets.tsv` (Phase 1's ontology split, preserved)

Only 6 of 8 USAN suffix classes get a MoA target -- auristatins/
maytansinoids (`-vedotin`/`-mafodotin`/`-emtansine`/`-soravtansine`) →
**Tubulin**; SN-38/exatecan-class (`-govitecan`/`-deruxtecan`) → **DNA
topoisomerase 1 (TOP1)**. `-ozogamicin` (calicheamicin, a DNA-damaging
enediyne antibiotic) and `-tesirine` (a PBD dimer, a DNA-crosslinking
agent) are honestly left unmapped -- neither has a single discrete
protein MoA target the same way the other six do; asserting one would be
a guess. 2 entities, both `VALIDATED` (uncontroversial public
pharmacology), 19 + 7 = 26 candidate associations (`Tubulin` used by 4 of
the 8 -vedotin/-mafodotin/-emtansine/-soravtansine classes' candidates,
`TOP1` by the -govitecan/-deruxtecan classes' candidates).

## 5. Coverage audit (`tools/breadth/component_coverage_audit.py`)

Full output: `reports/validation/breadth/component_coverage_audit.tsv`
(28 rows). Headline findings:

**Resolved coverage:**

| Candidate group | n | target resolved | payload resolved | linker resolved |
|---|---|---|---|---|
| Known-registry | 14 | 14/14 | 14/14 | 14/14 |
| New (Phase 3/5a) | 16 | **0/16** | 16/16 | 16/16 |

The 0/16 target gap for new candidates is unchanged from Phase 5c and
still honest -- Phase 5a/3's discovery mechanism has no target-resolution
signal of its own; closing it would require a real target-identification
source, not attempted this phase.

**NAR / ours-only classification** (a COMPARISON only, never a copy --
see `component_coverage_audit.py`'s own module docstring):

| Component | in both | ours-only | not compared |
|---|---|---|---|
| ADC_PAYLOAD (8 USAN classes) | 8/8 | 0 | -- |
| ADC_LINKER (8 USAN classes) | 7/8 | 0 | 1 (`-tesirine`'s linker -- no reliable keyword to search NAR by) |
| ADC_TARGET (known-registry, 11) | 11/11 | 0 | -- |
| PAYLOAD_MOA_TARGET (2) | 2/2 | 0 | -- |
| **ADC_PLATFORM (29)** | **N/A -- NAR has no platform category at all** | **29/29 categorically beyond NAR's own extraction schema** | -- |

The payload/linker/target 100% overlap with NAR is expected, not a null
result: our vocabulary here operates at the coarse USAN-suffix-**class**
level (8 classes), the same public nomenclature NAR itself draws from --
no novelty is claimed or expected at that granularity. One documented
synonym was needed for an honest (non-overclaiming) MoA-target
comparison: NAR's own `payload_moa_targets.tsv` labels the auristatin/
maytansinoid MoA target `"Microtubule (MT)"`, never `"Tubulin"` (the more
textbook-precise term for the same binding target) -- without this
synonym, `Tubulin` would have been misreported as a genuinely novel MoA
target beyond NAR's universe, when it is really a terminology-convention
difference (confirmed by inspecting NAR's own backlink entries for that
row, which do include MMAE/DM1-class conjugates).

**The one qualitatively significant finding**: NAR's own reference schema
(Antigen/Antibody/Payload/Linker/Target component pages) has **no
platform-entity category at all**. This is not "not found in NAR" -- it
is "not a concept NAR's own extraction schema captures." Every one of
our 29 ADC_PLATFORM entities, and the 297 real evidence mentions behind
them, is categorically beyond what NAR's own reference universe
structurally represents, independent of any name-level match. This is
the single largest, most defensible "breadth beyond NAR" signal produced
by this repo to date.

## 6. What this phase does not attempt

- No new acquisition source, no patent-derived mining (both explicitly
  out of scope this round -- see Section 1).
- No candidate-to-platform attribution (Section 2's disclosed limitation).
- No target resolution for the 16 new candidates (unchanged gap, Section 5).
- No new payload/linker chemical identities beyond the existing 8-suffix
  map -- this phase only raises CONFIDENCE in an already-suffix-inferred
  identity, never discovers a 9th class.
- Zymeworks (Phase 5d's disclosed deferral) remains unattempted.

## 7. On readiness for a breadth-freeze audit

This phase adds a real, substantive, independently-verified new component
category (29 platform entities, 297 evidence mentions, a genuine
architectural gap in NAR's own schema) and meaningfully deepens payload
evidence confidence (11/16 new candidates upgraded to TEXT_OBSERVED) --
without any new acquisition source or patent mining, exactly as scoped.
Whether this breadth is now "adequate" to trigger a freeze-audit is a
Phase 7 verdict, evaluated against BREADTH_PLAN's six explicit acceptance
gates with the FULL accumulated numbers (Phases 1-5e) -- not asserted
unilaterally here. This report's role is only to make the real numbers
available for that decision.

## Reproduction

```bash
python3 tools/breadth/feasibility_entities.py \
    --candidate-queue DATA/feasibility/candidate_queue.tsv \
    --known-assets-file configs/known_adc_assets.yaml \
    --data-dir DATA --output DATA/feasibility

python3 tools/breadth/component_coverage_audit.py \
    --feasibility-dir DATA/feasibility \
    --nar-dir DATA/reference/nar_adcdb \
    --output reports/validation/breadth/component_coverage_audit.tsv
```
