# ADC Modality Taxonomy (Phase 5b)

Per `reports/validation/BREADTH_PLAN.md` Phase 5 Part 5: "ADC_PLATFORM
taxonomy + STRICT_ADC/ADC_PLATFORM/ADJACENT_CONJUGATE_MODALITY distinction."

## Why this exists

Phase 3/5a's USAN/INN suffix mechanism (`-vedotin`, `-mafodotin`,
`-emtansine`, `-soravtansine`, `-ozogamicin`, `-govitecan`, `-tesirine`,
`-deruxtecan`) matches on the PAYLOAD/LINKER naming convention, not the
delivery vehicle. This is deliberate (Phase 3: "not derived from or copied
out of the NAR vault") but has a real, concrete consequence: a payload/
linker suffix can legitimately be used by a delivery vehicle that is
**not a classical antibody** -- e.g. `zelenectide pevedotin` (`BT8009`),
surfaced by Phase 5a as `NEEDS_REVIEW`, is explicitly described in its own
conference abstracts (verified by reading the real abstract text, not
assumed) as a **"Bicycle Toxin Conjugate (BTC)"** / **"Bicycle® Drug
Conjugate (BDC™)"** -- a bicyclic peptide, not an antibody, conjugated to
MMAE via the same `-vedotin` linker-payload chemistry a real antibody-drug
conjugate would use.

**A naming-pattern-based rule (e.g. "the vehicle word ends in `-mab`") was
considered and rejected as unsafe.** Checking the real queue found 3
already-`AUTO_HIGH_CONFIDENCE` (CT.gov-confirmed) candidates whose vehicle
word does NOT end in `-mab` -- `sigvotatug vedotin`, `raludotatug
deruxtecan`, `bulumtatug fuvedotin` -- and this project cannot verify
live, from inside this sandbox, whether `-tug`/`-tabart` are a legitimate,
newer USAN antibody-format stem or something else. Asserting a rule here
that might be wrong would misclassify genuine antibody ADCs as non-antibody
-- exactly the kind of unverifiable guess this project's evidence-gated
discipline exists to avoid. So classification here is **positive-evidence
only**: a candidate is only classified as a non-strict-ADC modality when
its own evidence TEXT explicitly says so (a documented keyword), never
inferred from the shape of its name alone.

## The three categories

- **`STRICT_ADC`** -- an antibody conjugated to a small-molecule cytotoxic
  payload via a chemical linker; the classical ADC. Applied to
  `configs/known_adc_assets.yaml`'s 14 active assets (already
  independently verified as real antibody ADCs in the prior NAR-benchmark
  audit, PR #17) -- and ONLY there. This phase does not assert `STRICT_ADC`
  for any suffix-matched candidate, for the exact reason above: absence of
  adjacent-modality evidence is not proof of being a strict ADC, it is only
  absence of evidence against it.
- **`PRESUMED_STRICT_ADC`** -- a suffix-matched candidate (Phase 3/5a) with
  NO explicit adjacent-modality keyword found in its own evidence text.
  Named `PRESUMED`, not `STRICT_ADC`, per the same censored-negative
  discipline already established for `NOT_CONFIRMED_BROAD` in
  `tools/breadth/broad_recall.py` (Phase 1) -- a "no adjacent-modality
  signal found" result is not the same as "confirmed to be a strict ADC."
- **`ADJACENT_CONJUGATE_MODALITY`** -- a candidate whose OWN evidence text
  explicitly names a related-but-distinct conjugate drug class (see
  `ADJACENT_MODALITY_KEYWORDS` in `tools/breadth/candidate_queue.py`):
  Bicycle toxin/drug conjugate, peptide-drug conjugate, small-molecule
  drug conjugate, radioconjugate/radioligand therapy, degrader-antibody
  conjugate. `zelenectide pevedotin` is the one confirmed real case in the
  current corpus.
- **`ADC_PLATFORM`** -- a named proprietary conjugation/technology
  platform (e.g. Dolaflexin, THIOMAB, SMARTag) rather than a specific
  asset. **Defined here for the taxonomy's completeness, but NOT mined or
  applied to any entity this phase** -- platform-name mining is a
  separate, later Phase 5 increment (a new `adc_platforms.tsv` entity
  table, per `BREADTH_PLAN.md`'s own file list), not attempted here.

## What changed in the pipeline

`tools/breadth/candidate_queue.py`'s `build_ctgov_suffix_candidates()` and
`build_conference_suffix_candidates()` now also scan each mention's own
text (CT.gov's `brief_title`; conference abstracts' FULL `title`+`abstract`
text, not the 150-char truncated snippet stored in `candidate_queue.tsv`'s
`context` column) for `ADJACENT_MODALITY_KEYWORDS`, accumulating any hits
per candidate. `candidate_queue.tsv` gained two columns:
`modality_classification` (`STRICT_ADC` / `PRESUMED_STRICT_ADC` /
`ADJACENT_CONJUGATE_MODALITY`) and `modality_detail` (which specific
keyword-matched modality, when applicable).

**Promotion gate hardened**: `tools/breadth/feasibility_entities.py` now
excludes `ADJACENT_CONJUGATE_MODALITY` candidates from
`adc_candidates.tsv` regardless of `validation_status` -- a real ADC
candidate table must never silently include a confirmed non-antibody
conjugate, even a high-confidence one. Not load-bearing against the
CURRENT data (`zelenectide pevedotin` is `NEEDS_REVIEW`, already excluded
by the existing promotion gate), but closes a real gap for any future
case where an adjacent-modality candidate is ALSO confirmed via CT.gov's
structured field.

## Not done this phase

- `ADC_PLATFORM` entity mining (named technology/platform mentions) --
  deferred, a separate Phase 5 increment.
- Re-litigating whether `-tug`/`-tabart`-vehicle candidates are real
  antibody ADCs -- left `PRESUMED_STRICT_ADC`, not resolved either way.
- Retroactive re-classification of `configs/known_adc_assets.yaml`'s own
  14 assets by keyword scan -- they are `STRICT_ADC` by virtue of the
  prior independent audit (PR #17), not by this phase's keyword mechanism.
