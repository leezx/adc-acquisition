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

**Round-1 fix — canonicalize BEFORE matching, not after.** The first pass
matched a USAN/INN suffix against, and deduplicated on, the WHOLE raw
intervention string. Two distinct problems followed from this, both fixed
by `extract_adc_generic_name()` (tested in
`tests/tools/breadth/test_candidate_queue.py`): it tokenizes on any
non-alphanumeric character and extracts the two-word generic name
(antibody-stem word + payload/linker-suffix word) around the LAST matching
suffix token, discarding everything else:

1. **Combination-regimen/trial-arm labels falsely flagged as new.** CT.gov's
   `intervention_names` frequently records `"Pembrolizumab + Enfortumab
   Vedotin"` or `"Arm A: Belantamab Mafodotin"` rather than a clean
   single-drug name. Matching/deduping on the raw string missed these
   entirely — 10 of an initial 25 suffix matches were already-known assets
   in disguise. `extract_adc_generic_name("Pembrolizumab + Enfortumab
   Vedotin")` → `"Enfortumab Vedotin"`, which the known-registry
   containment check (`mentions_known_asset`) then correctly suppresses.
2. **A radiolabeled tracer variant counted as a separate, new ADC.**
   `"89Zr-Patritumab deruxtecan"` (a PET-imaging tracer of an existing
   candidate, not a new development asset) was initially kept as its own
   entity alongside `"Patritumab Deruxtecan"`.
   `extract_adc_generic_name("89Zr-Patritumab deruxtecan")` →
   `"Patritumab deruxtecan"`, which now correctly merges into the same
   candidate (the isotope-label token is simply never adjacent to the
   suffix token, so it's dropped without any isotope-specific stripping
   logic).

**A side benefit, not just a fix**: extracting the generic name before
matching also RECOVERED two real candidates the naive whole-string
`endswith()` check had silently missed, because CT.gov recorded them with
a trailing parenthetical abbreviation — `"Labetuzumab Govitecan (LG)"` and
`"Enapotamab vedotin (HuMax-AXL-ADC)"` do not literally *end* in the
suffix, but do contain the correct two-word pair, so the corrected version
finds these where the original missed them.

Result: **30 candidates** in the queue — 14 `PROMOTED` + **16
`AUTO_HIGH_CONFIDENCE`, genuinely new** ADC candidates absent from
`configs/known_adc_assets.yaml`: Labetuzumab govitecan, Pinatuzumab
vedotin, Ladiratuzumab vedotin, Telisotuzumab vedotin, Glembatumumab
vedotin, Depatuxizumab mafodotin, Denintuzumab mafodotin, Rovalpituzumab
tesirine, Patritumab deruxtecan (its 89Zr-labeled imaging-tracer mentions
now correctly merged into this same candidate, not a separate one),
Enapotamab vedotin, Ifinatamab deruxtecan, Ozuriftamab vedotin,
Sigvotatug vedotin, Zilovertamab vedotin, Raludotatug deruxtecan,
Bulumtatug fuvedotin. `NEEDS_REVIEW`/`REJECTED`/`UNREVIEWED` candidates are
not produced by this phase's two sources (both are inherently high-
confidence patterns) — a future phase adding lower-confidence sources
(e.g. free-text literature/patent mining) would populate those statuses.

## 2. Feasibility entities (`DATA/feasibility/*.tsv`)

`tools/breadth/feasibility_entities.py` promotes only the queue's
`PROMOTED`/`AUTO_HIGH_CONFIDENCE` rows into entities:

| File | Rows | Basis |
|---|---|---|
| `adc_candidates.tsv` | 30 | All validated queue rows. `target`/`company`/`stage` populated from the known registry for the 14 known assets (`stage = "Approved"`, established in PR #17); honestly left blank/`"unknown"` for the 16 new candidates (Part 4's explicit tolerance for partial entities) — `stage` for those instead derived from CT.gov's own `phases` field where available. `payload_if_known`/`linker_if_known` are accompanied by explicit `payload_evidence_type`/`linker_evidence_type = USAN_INN_NAMING_INFERENCE` columns (round-1 fix, see below) — never asserted as a directly-confirmed structured fact. |
| `adc_targets.tsv` (`ADC_TARGET`) | 11 | Known-registry only this phase — new candidates have no established target yet, left absent rather than guessed. Correctly merges shared targets (e.g. HER2 across 3 known assets) into one entity. |
| `adc_payloads.tsv` (`ADC_PAYLOAD`) | 8 | USAN/INN suffix inference, `status = INFERRED` (round-1 fix, was `VALIDATED`), `confidence = medium` — spans both known and new candidates. |
| `adc_linkers.tsv` (`ADC_LINKER`) | 8 | Same basis and status as payloads. |
| `adc_indications.tsv` | 871 distinct strings | Raw, **undeduplicated** free-text `conditions` field from `clinicaltrials.parquet`, aggregated per validated candidate. Deliberately not normalized in this phase (e.g. "Breast Cancer" / "Breast Neoplasms" / "Metastatic Breast Cancer" all appear separately) — a lightweight breadth index per Part 16's scope discipline, not a cleaned ontology. |

**`adc_antibodies.tsv` is NOT written this phase (round-1 fix).** The
first pass wrote the FULL ADC name (e.g. "Trastuzumab deruxtecan") as an
`ADC_ANTIBODY` entity, but the antibody moiety is "Trastuzumab" —
"Trastuzumab deruxtecan" is the complete conjugate, a different entity
type entirely. Neither the known registry nor `clinicaltrials.parquet`
carries a reliable structured antibody-moiety field, and inferring one by
stripping the payload-suffix word is not safe in general (naming structure
varies and isn't guaranteed splittable that way). Antibody-entity
extraction is deferred until a source explicitly supports antibody
identity — not attempted by guessing here.

**Not written in this phase**: `adc_platforms.tsv` (Part 5 — ADC_PLATFORM
taxonomy doesn't exist yet) and `target_indication_feasibility.tsv` (Part
10, also Phase 5 per the plan's sequencing) are explicitly deferred, not
created as empty placeholders.

**Non-blocking cleanup applied alongside the above**: known-asset trial
matching in `feasibility_entities.py` previously used exact normalized-
string equality against `intervention_names`, which — same root cause as
the candidate-queue dedup gap — undercounted `evidence_count`/`indications`
whenever a known asset appeared only inside a combination-regimen string.
Now reuses the same `mentions_known_asset` containment matcher (restricted
to just that one asset's own identifiers), so known-asset evidence counts
reflect the actual trial set rather than only exact-label matches.

## 3. What Phase 3 does and does not establish

- Demonstrates the two-stage candidate-queue mechanism works and, even
  restricted to a single existing source (`clinicaltrials.parquet`) with
  zero new acquisition, already surfaces 16 genuine ADC candidates beyond
  the 14-asset curated registry — direct evidence that breadth extraction
  from evidence we already hold is viable, before Phases 4-5 add new
  sources.
- The USAN/INN suffix match is high-precision by construction (a real,
  documented naming convention) but is **not exhaustive** — newer or
  unconventional payload/linker stems, and any candidate that only exists
  in literature/patent/conference text rather than a CT.gov intervention
  name, will not be found by this phase's two sources. That is explicit
  Phase 4/5 scope, not a defect here.
- **`ADC_CANDIDATE` identity confidence and `ADC_PAYLOAD`/`ADC_LINKER`
  chemistry confidence are two different claims, and are now labeled as
  such.** A candidate's own identity (this is a real, distinct ADC generic
  name) can legitimately be `AUTO_HIGH_CONFIDENCE`/`high` from the suffix
  match alone. Its inferred payload/linker CLASS is a separate, weaker
  claim (`status = INFERRED`, `confidence = medium`,
  `evidence_sources = USAN_INN_NAMING_INFERENCE`) — a naming-convention
  inference about the general class the stem denotes, not a
  per-asset-confirmed structural fact.
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
