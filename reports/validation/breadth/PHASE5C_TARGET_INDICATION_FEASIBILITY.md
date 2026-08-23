# Phase 5c — Target x Indication Feasibility Table

Per `reports/validation/BREADTH_PLAN.md` Phase 5 Part 10. Third increment
after Phase 5a (conference-text candidate discovery) and Phase 5b (ADC
modality taxonomy).

## What this phase does

`tools/breadth/feasibility_entities.py`'s new `build_target_indication_rows()`
builds `DATA/feasibility/target_indication_feasibility.tsv`: one row per
distinct (ADC_TARGET, indication) pair, derived entirely from
`adc_candidates.tsv` x `adc_targets.tsv` (both already produced by this
same script) -- no new acquisition, no new extraction source.

**`target` is ALWAYS `ADC_TARGET`** (the antibody-binding delivery
antigen, e.g. HER2), **never `PAYLOAD_MOA_TARGET`** (the payload's
mechanism-of-action target, e.g. TOP1) -- the permanent ontology split
locked in Phase 1. `target_entity_id` cross-references `adc_targets.tsv`
directly (e.g. `ADC_TARGET_HER2`).

## Scope: known-registry-only, same reason as adc_targets.tsv

This table can only pair a target with an indication for candidates whose
target is already resolved -- today, the 14 `configs/known_adc_assets.yaml`
assets only. This is not a new restriction introduced by this phase: it
directly follows `adc_targets.tsv`'s own pre-existing scope (Phase 3:
"known-registry only this phase"). The 16 CT.gov/conference-derived
candidates (Phase 3/5a) have `target=""`, honestly left blank rather than
guessed, so `build_target_indication_rows()` correctly finds them absent
from every target's `associated_adc_candidates` list and they contribute
no row -- verified with a dedicated test
(`test_build_target_indication_rows_excludes_candidates_with_no_resolved_target`).

## Inherited limitation (not new, disclosed again here)

`indication` values come directly from `adc_candidates.tsv`'s own
`indications` field, which is itself CT.gov's raw, **undeduplicated**
`conditions` strings (Phase 3's own documented scope: "a lightweight
breadth index... not a cleaned ontology"). So `target_indication_feasibility.tsv`
inherits the same non-normalization: "Breast Cancer" / "Breast Neoplasms" /
"Metastatic Breast Cancer" appear as separate rows for the same target,
rather than one normalized indication. Not fixed this phase -- normalizing
indication strings is a distinct, larger effort (would need an indication
ontology/mapping, out of Part 16's scope discipline) than this phase's own
job (pairing what's already extracted, not cleaning it).

## Real numbers (live run, not fixtures)

```
$ python3 tools/breadth/feasibility_entities.py ...
target_indication_feasibility.tsv: 1012 (target, indication) pairs (known-registry-only this phase)
```

Top rows by evidence_count (3 of the 14 known HER2-targeted assets --
`Disitamab vedotin`, `Trastuzumab deruxtecan`, `Trastuzumab emtansine` --
share several indication strings, e.g. "Breast Cancer", "Gastric Cancer"),
descending from there. Rows sorted by `evidence_count` (desc), then
`target`, then `indication`, so the most cross-validated (target,
indication) pairs sort first.

## What Phase 5c does and does not establish

- Directly satisfies Part 10's file (`target_indication_feasibility.tsv`)
  and its explicit `target`-column-is-always-`ADC_TARGET` requirement.
- Does **not** attempt indication normalization/deduplication -- disclosed
  above, inherited from Phase 3's own scope.
- Does **not** extend target×indication pairing to the 16 CT.gov/
  conference-derived candidates -- would require resolving their target
  first (deferred; no safe mechanism exists yet to infer a target from a
  bare generic name).
- Does **not** attempt `ADC_PLATFORM` entity mining, company
  scientific-presentation ingestion, or patent-derived breadth mining --
  remaining Phase 5 increments per `BREADTH_PLAN.md`'s own sequencing.

## Reproduction

```bash
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
