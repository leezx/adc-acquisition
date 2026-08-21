# Phase 3 — Feasibility Entity Model + High-Recall Candidate Queue

Per `reports/validation/BREADTH_PLAN.md` Phase 3 (Parts 4, 9). Turns
existing raw evidence already in this repo into counted,
provenance-preserving entities for the first time — **no new acquisition
source in this phase**, and no dependency on the NAR ADCdb benchmark used
in Phases 1-2 (Part 15: NAR is a reference for measuring gaps, not a
source to build this layer from).

## 1. Two-stage design (Part 9): DISCOVERY CANDIDATE -> VALIDATED FEASIBILITY ENTITY

`tools/breadth/candidate_queue.py` builds `DATA/feasibility/
candidate_queue.tsv` from two sources, explicitly avoiding fuzzy-only
promotion:

1. **`configs/known_adc_assets.yaml`'s 14 active assets** — already
   independently curated and verified in the prior audit (PR #17) →
   `validation_status = PROMOTED`.
2. **`DATA/manifests/clinicaltrials.parquet`'s `intervention_names`**,
   matched against a documented USAN/INN naming-convention stem specific
   to ADC payload/linker chemistry (`vedotin`, `mafodotin`, `emtansine`,
   `soravtansine`, `ozogamicin`, `govitecan`, `tesirine`, `deruxtecan` —
   general public pharmaceutical-nomenclature knowledge, empirically
   confirmed to cover all 8 distinct suffixes already present among our
   own 14 known assets' names, **not** derived from or copied out of the
   NAR vault) → `validation_status = AUTO_HIGH_CONFIDENCE`.

**A real dedup gap was found and fixed during this phase**: CT.gov's
`intervention_names` frequently records a combination-regimen or
trial-arm label (e.g. `"Pembrolizumab + Enfortumab Vedotin"`, `"Arm A:
Belantamab Mafodotin"`) rather than a clean single-drug name. An exact
normalized-string match against the known registry missed these entirely,
surfacing 10 of an initial 25 suffix matches as spurious "new" candidates
that were actually already-known assets in disguise. Fixed with a
substring-containment check (`mentions_known_asset`, tested in
`tests/tools/breadth/test_candidate_queue.py`) — every one of the messy/
combo-looking strings in the initial run turned out to be exactly this,
not a genuinely new candidate with a messy label.

Result: **29 candidates** in the queue — 14 `PROMOTED` + **15
`AUTO_HIGH_CONFIDENCE`, genuinely new** ADC candidates absent from
`configs/known_adc_assets.yaml`: Pinatuzumab vedotin, Ladiratuzumab
vedotin, Telisotuzumab vedotin, Glembatumumab vedotin, Depatuxizumab
mafodotin, Denintuzumab mafodotin, Rovalpituzumab tesirine, Patritumab
deruxtecan (+ its 89Zr-labeled imaging-tracer variant, kept as a separate,
explicitly-labeled entity), Ozuriftamab vedotin, Sigvotatug vedotin,
Ifinatamab deruxtecan, Zilovertamab vedotin, Raludotatug deruxtecan,
Bulumtatug fuvedotin. `NEEDS_REVIEW`/`REJECTED`/`UNREVIEWED` candidates are
not produced by this phase's two sources (both are inherently high-
confidence patterns) — a future phase adding lower-confidence sources
(e.g. free-text literature/patent mining) would populate those statuses.

## 2. Feasibility entities (`DATA/feasibility/*.tsv`)

`tools/breadth/feasibility_entities.py` promotes only the queue's
`PROMOTED`/`AUTO_HIGH_CONFIDENCE` rows into entities:

| File | Rows | Basis |
|---|---|---|
| `adc_candidates.tsv` | 29 | All validated queue rows. `target`/`company`/`stage` populated from the known registry for the 14 known assets (`stage = "Approved"`, established in PR #17); honestly left blank/`"unknown"` for the 15 new candidates (Part 4's explicit tolerance for partial entities) — `stage` for those instead derived from CT.gov's own `phases` field where available. |
| `adc_targets.tsv` (`ADC_TARGET`) | 11 | Known-registry only this phase — new candidates have no established target yet, left absent rather than guessed. Correctly merges shared targets (e.g. HER2 across 3 known assets) into one entity. |
| `adc_antibodies.tsv` (`ADC_ANTIBODY`) | 14 | Known-registry only this phase, same reasoning. |
| `adc_payloads.tsv` (`ADC_PAYLOAD`) | 8 | USAN/INN suffix inference, `confidence = medium` (a naming-convention inference, not a directly-extracted structured field) — spans both known and new candidates. |
| `adc_linkers.tsv` (`ADC_LINKER`) | 8 | Same basis as payloads. |
| `adc_indications.tsv` | 789 distinct strings | Raw, **undeduplicated** free-text `conditions` field from `clinicaltrials.parquet`, aggregated per validated candidate. Deliberately not normalized in this phase (e.g. "Breast Cancer" / "Breast Neoplasms" / "Metastatic Breast Cancer" all appear separately) — a lightweight breadth index per Part 16's scope discipline, not a cleaned ontology. |

**Not written in this phase**: `adc_platforms.tsv` (Part 5 — ADC_PLATFORM
taxonomy doesn't exist yet) and `target_indication_feasibility.tsv` (Part
10, also Phase 5 per the plan's sequencing) are explicitly deferred, not
created as empty placeholders.

## 3. What Phase 3 does and does not establish

- Demonstrates the two-stage candidate-queue mechanism works and, even
  restricted to a single existing source (`clinicaltrials.parquet`) with
  zero new acquisition, already surfaces 15 genuine ADC candidates beyond
  the 14-asset curated registry — direct evidence that breadth extraction
  from evidence we already hold is viable, before Phases 4-5 add new
  sources.
- The USAN/INN suffix match is high-precision by construction (a real,
  documented naming convention) but is **not exhaustive** — newer or
  unconventional payload/linker stems, and any candidate that only exists
  in literature/patent/conference text rather than a CT.gov intervention
  name, will not be found by this phase's two sources. That is explicit
  Phase 4/5 scope, not a defect here.
- `ADC_PAYLOAD`/`ADC_LINKER` entities are `confidence = medium` by design
  — they are inferred from a name pattern, not read from a structured
  chemistry field, and are labeled as such rather than asserted as
  verified facts.
- Does not attempt any deep extraction (IC50/DAR/PK-PD/mechanism) — Part
  16 scope discipline maintained.

## Reproduction

```
python3 tools/breadth/candidate_queue.py \
    --known-assets-file configs/known_adc_assets.yaml \
    --data-dir DATA \
    --output DATA/feasibility

python3 tools/breadth/feasibility_entities.py \
    --candidate-queue DATA/feasibility/candidate_queue.tsv \
    --known-assets-file configs/known_adc_assets.yaml \
    --data-dir DATA \
    --output DATA/feasibility
```
