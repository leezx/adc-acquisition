# Phase 5b — ADC Modality Taxonomy

Per `reports/validation/BREADTH_PLAN.md` Phase 5 Part 5. Second increment
after Phase 5a (candidate discovery from conference abstract text). Full
taxonomy definitions and design rationale are in
`reports/validation/breadth/ADC_MODALITY_TAXONOMY.md`; this report covers
the pipeline change and real results.

## Why this phase exists

Phase 5a's own writeup flagged `zelenectide pevedotin` as `NEEDS_REVIEW`
without resolving what it actually is. It is a real, disclosed case: its
own conference abstracts (verified by reading the real text) describe it
as a **"Bicycle Toxin Conjugate (BTC)"** -- a bicyclic peptide, not an
antibody, conjugated to MMAE via the same `-vedotin` payload/linker
chemistry a real antibody-drug conjugate would use. The USAN/INN suffix
mechanism (Phase 3/5a) matches payload/linker chemistry, not the delivery
vehicle, so it cannot by itself tell "this is a strict ADC" from "this
uses ADC-class payload chemistry on a non-antibody vehicle."

## What was rejected before landing on the final design

A naming-pattern rule ("the vehicle word ends in `-mab`") was considered
and rejected as unsafe: checking the real queue found 3 already-CT.gov-
confirmed candidates (`sigvotatug vedotin`, `raludotatug deruxtecan`,
`bulumtatug fuvedotin`) whose vehicle word does NOT end in `-mab`, and this
project cannot verify live whether `-tug`/`-tabart` are a legitimate,
newer USAN antibody-format stem. Asserting a rule that might misclassify
real antibody ADCs as non-antibody would be exactly the kind of
unverifiable guess this project avoids. The final design is
**positive-keyword-evidence only**: a candidate is only classified as a
non-strict-ADC modality when its OWN evidence text explicitly names one
(`ADJACENT_MODALITY_KEYWORDS` in `tools/breadth/candidate_queue.py`) --
never inferred from the candidate name's shape.

## What changed

- `build_ctgov_suffix_candidates()`/`build_conference_suffix_candidates()`
  now scan each mention's own text (CT.gov `brief_title`; conference
  **full** `title`+`abstract`, not the 150-char truncated `context`
  snippet) for `ADJACENT_MODALITY_KEYWORDS`, accumulating hits per
  candidate through the merge step.
- `candidate_queue.tsv` gained `modality_classification`
  (`STRICT_ADC`/`PRESUMED_STRICT_ADC`/`ADJACENT_CONJUGATE_MODALITY`) and
  `modality_detail` (the specific matched modality, e.g.
  `BICYCLE_TOXIN_CONJUGATE`).
- `feasibility_entities.py`'s new `filter_promotable()` excludes
  `ADJACENT_CONJUGATE_MODALITY` rows from `adc_candidates.tsv` regardless
  of `validation_status` -- not load-bearing against today's data
  (`zelenectide pevedotin` is already `NEEDS_REVIEW`, excluded by the
  status filter alone) but closes a real gap for any future case where an
  adjacent-modality candidate is ALSO confirmed via CT.gov.
- `adc_candidates.tsv` carries `modality_classification` through
  (`STRICT_ADC` for all 14 known-registry entities; `PRESUMED_STRICT_ADC`
  for the 16 CT.gov-derived ones -- none of the 30 currently-promoted
  entities are `ADJACENT_CONJUGATE_MODALITY`, so `adc_candidates.tsv`'s
  count is unchanged this phase).

## Real numbers (live run, not fixtures)

```
$ python3 tools/breadth/candidate_queue.py ...
candidate_queue.tsv: 53 total (14 PROMOTED, 16 AUTO_HIGH_CONFIDENCE, 23 NEEDS_REVIEW)
modality_classification: 1 ADJACENT_CONJUGATE_MODALITY, 14 STRICT_ADC, 38 PRESUMED_STRICT_ADC

  zelenectide pevedotin | BICYCLE_TOXIN_CONJUGATE | NEEDS_REVIEW

$ python3 tools/breadth/feasibility_entities.py ...
30/53 candidate_queue.tsv rows are validated (excluding 1 ADJACENT_CONJUGATE_MODALITY);
adc_candidates.tsv: 30 entities (unchanged from Phase 5a -- the 1 adjacent-modality
row was already NEEDS_REVIEW, so this phase found zero cases that needed the new
promotion-gate exclusion to actually block, but the gate now exists)
```

## What Phase 5b does and does not establish

- Correctly, evidence-gatedly resolves the one open case Phase 5a flagged
  without an answer.
- Does **not** re-classify any of the 3 `-tug`/`-tabart` CT.gov-confirmed
  candidates -- left `PRESUMED_STRICT_ADC`, genuinely unresolved.
- Does **not** mine `ADC_PLATFORM` entities (named conjugation
  technologies like Dolaflexin/THIOMAB/SMARTag) -- defined in the taxonomy
  for completeness, deferred to a later Phase 5 increment.
- Does **not** retroactively re-scan `configs/known_adc_assets.yaml`'s 14
  assets by keyword -- they are `STRICT_ADC` by the prior independent
  audit (PR #17), not by this phase's mechanism.

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
