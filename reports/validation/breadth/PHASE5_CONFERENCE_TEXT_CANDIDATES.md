# Phase 5a — Candidate Discovery From Conference Abstract Text

## Round-1 fixes (2 issues from review)

1. **Candidate identity was source-dependent -- would have broken Phase
   6's delta system before it existed.** The first version picked
   `candidate_id`'s PREFIX (`CTGOV_SUFFIX_`/`CONFERENCE_SUFFIX_`) based on
   whether clinicaltrials evidence was present. A real early-seed
   candidate first seen only in a conference abstract, then later also
   confirmed on CT.gov, would get a DIFFERENT id on the second run --
   looking to any future delta/diff logic like "old candidate disappeared,
   new candidate appeared" instead of "same candidate, new evidence
   source, status upgraded". Fixed with `candidate_id_for_name()`: identity
   now depends ONLY on the canonical normalized name, never on source
   composition. This is an intentional, one-time migration of the 16
   existing `CTGOV_SUFFIX_*` ids (and the new `CONFERENCE_SUFFIX_*` ids
   from this same PR) to a single `ADC_SUFFIX_*` scheme -- the hash portion
   is unchanged (`sha256(normalize_name(name))[:12]`), only the prefix text
   changes. Doing this now, before Phase 6's delta system exists, is the
   last reasonable window to fix the identity contract without a real
   migration against live delta history. Paired with a new
   `status_and_confidence_for_sources()` helper so status upgrades
   (`NEEDS_REVIEW` -> `AUTO_HIGH_CONFIDENCE`) happen in place for the same
   id. Regression test:
   `test_candidate_id_for_name_is_source_independent_and_stable_across_upgrade`
   -- a candidate seen only in conference text, then also seen on CT.gov,
   asserted to keep the same id and upgrade status in place.
2. **`first_seen` could be the literal string `"nan"`.** An undated
   conference record's `publication_or_release_date` is a pandas float
   `NaN`, not `None` -- `if date:` treats `NaN` as truthy
   (`bool(float("nan"))` is `True`), so `str(date)` produced the literal
   string `"nan"` instead of leaving `first_seen` blank. Confirmed live: 3
   real rows (`Trastuzumab vedotin`, `datopotumab deruxtecan`, `M100B
   vedotin`) had `first_seen="nan"` before this fix. Fixed with a shared
   `_clean_date_string()` helper (`pd.isna()`-aware), applied to BOTH the
   conference-text path (where the reviewer found it) and the CT.gov path
   (`study_first_post_date`, the same latent bug in a sibling function
   this PR was already touching). Regression test:
   `test_clean_date_string_never_produces_literal_nan`.

Live-reverified after both fixes: same 39/53/30 counts as before (identity
and first_seen are provenance fields, not counted quantities), 0 literal
`"nan"` values, all 39 suffix-matched candidates now share the single
`ADC_SUFFIX_*` id scheme. 445 tests passing (3 new this round).


Per `reports/validation/BREADTH_PLAN.md` Phase 5 (Parts 4/9 continuation).
BREADTH_PLAN.md's Phase 5 bundles several distinct pieces of work (ADC_PLATFORM
taxonomy, company scientific-presentation source, patent-derived breadth
mining, full component tables, target x indication feasibility table) --
too much for one PR-sized change per this project's own discipline. This is
the first increment ("Phase 5a"): extending Phase 3's candidate-discovery
mechanism to the second text source Phase 4 just added
(`conference_abstract_corpus.parquet`), which the reviewer identified as
the concrete next step after Phase 4's APPROVE ("从这些 abstract text 中抽取
ADC candidate...feasibility entities"). The remaining Phase 5 parts
(platform taxonomy, company presentations, patent mining, full component
tables, target x indication table) are separate, later increments -- not
attempted here.

## 1. What this phase does

`tools/breadth/candidate_queue.py`'s two-stage design (Part 9) already knew
how to turn CT.gov's structured `intervention_names` field into candidates
via a documented USAN/INN suffix match. This phase adds a second source:
`conference_abstract_corpus.parquet`'s `title`+`abstract` free text (2,456
AACR/ASCO records from Phase 4), scanned with the same suffix set.

**A new extraction function, not a reuse of `extract_adc_generic_name()`.**
CT.gov's `intervention_names` is a short, single-purpose field; a
conference abstract's title+abstract is full prose that can genuinely
discuss MULTIPLE distinct ADCs in one record. `extract_adc_generic_name()`
(Phase 3) only returns the LAST matching name-suffix pair in a string --
correct for a short intervention label, wrong for prose. The new
`extract_all_adc_generic_names_from_text()` returns every distinct match.

**Free text is categorically noisier than a structured field -- verified
empirically, not assumed.** A first pass scanning the real corpus with no
additional filtering surfaced real signal (e.g. `datopotamab deruxtecan`,
`becotatug vedotin`, `mecbotamab vedotin` -- genuine ADC generic names) but
also produced a long tail of false positives that never occur against
CT.gov's `intervention_names`: common English words immediately before the
suffix word ("novel vedotin", "the deruxtecan arm", "payload tesirine"),
one of the suffix words itself acting as a false "prefix" to another
("emtansine deruxtecan", "exatecan deruxtecan" -- prose listing two payload
classes side by side), purely numeric prefixes ("38 govitecan"), and
single/double-letter abbreviation fragments ("E vedotin", "M Deruxtecan").
`extract_all_adc_generic_names_from_text()` filters all four classes:

1. `TEXT_SCAN_STOPWORD_PREFIXES` -- an empirically-derived (not
   hypothetical) blocklist of the common-English/generic-description words
   actually observed in a real scan of the corpus.
2. The prefix may not itself be one of the 8 documented ADC_SUFFIX_PAYLOAD_
   CLASS suffix words.
3. The prefix may not be purely numeric.
4. The prefix must be at least 5 characters (every real USAN/INN
   antibody-stem word in this corpus is well over that).

None of this filtering is fuzzy/probabilistic -- every rule is a concrete,
checkable condition, consistent with Part 9's "avoid fuzzy-only promotion."

## 2. Confidence: two sources, two confidence tiers, never silently merged

A name found via CT.gov's structured field is `AUTO_HIGH_CONFIDENCE`
(unchanged from Phase 3) regardless of whether conference text also
mentions it. A name found **only** via conference free text is
`NEEDS_REVIEW` -- **never** auto-promoted, precisely because Part 9's
two-stage design exists for exactly this case: a noisier signal earns a
human check, not a confidence label it hasn't earned. `merge_suffix_
candidates()` unions evidence for a name found by both sources into ONE
candidate (not two), and a name already in `configs/known_adc_assets.yaml`
is suppressed by the same `mentions_known_asset()` containment check
already used for CT.gov (e.g. `Datopotamab deruxtecan`, already a known
asset, is correctly suppressed here too, not surfaced as "new").

`tools/breadth/feasibility_entities.py` required **no code change**: it
already only promotes `PROMOTED`/`AUTO_HIGH_CONFIDENCE` rows into
`adc_candidates.tsv`, so `NEEDS_REVIEW` conference-only candidates are
correctly excluded from becoming entities this phase, and a merged
candidate's `evidence_sources` column now honestly shows
`"clinicaltrials; conference_abstract_corpus"` when both sources
contributed, instead of just `"clinicaltrials"`.

## 3. Real numbers (live run against the real corpus, not fixtures)

```
$ python3 tools/breadth/candidate_queue.py --known-assets-file configs/known_adc_assets.yaml --data-dir DATA --output DATA/feasibility
Found 39 distinct new candidate names via ADC USAN/INN suffix match
(16 from clinicaltrials, 37 from conference_abstract_corpus, 14 found by both)
candidate_queue.tsv: 53 total (14 PROMOTED, 16 AUTO_HIGH_CONFIDENCE, 23 NEEDS_REVIEW)

$ python3 tools/breadth/feasibility_entities.py ...
30/53 candidate_queue.tsv rows are validated; adc_candidates.tsv: 30 entities (unchanged from Phase 3 --
NEEDS_REVIEW correctly excluded)
```

`candidate_queue.tsv` grew from 30 rows (Phase 3) to 53: the 14 known-asset
`KNOWN_*` rows are unaffected; the 16 CT.gov-derived candidates now carry a
migrated `ADC_SUFFIX_*` id (round-1 fix -- see above; the id no longer
depends on which source(s) discovered a name), plus 23 new `ADC_SUFFIX_*`
rows for conference-only names, all `NEEDS_REVIEW`, visible for human
review but not promoted to any `DATA/feasibility/*.tsv` entity table.

## 4. What the 23 NEEDS_REVIEW rows actually look like (disclosed, not hidden)

Manually inspecting the 23 rows after the filtering above: most fall into
two honest, disclosed classes, not resolved this phase:

- **Genuinely new, plausible ADC candidate names** not yet in
  `configs/known_adc_assets.yaml` or the CT.gov-derived set: e.g.
  `mecbotamab vedotin`, `becotatug vedotin`, `naratuximab emtansine`,
  `lifastuzumab vedotin`, `camidanlumab tesirine`, `sonesitatug vedotin`,
  `indusatumab vedotin`, `tecotabart vedotin`, `zelenectide pevedotin` --
  exactly the kind of early-seed, conference-only breadth signal this
  phase exists to surface.
- **Likely OCR/authoring typo variants of an already-known name's
  spelling** (e.g. `trastuzuamb`/`tratuzumab`/`trastruzumab deruxtecan` for
  `Trastuzumab deruxtecan`; `datopotomab`/`datopotumab deruxtecan` for
  `Datopotamab deruxtecan`; `sacitizumab`/`sacituzmab govitecan` for
  `Sacituzumab govitecan`; `distamab vedotin` for `Disitamab vedotin`;
  `paritumab deruxtecan` for `Patritumab deruxtecan`) -- **not
  auto-corrected or fuzzy-matched away this phase** (Part 16 / Part 9
  discipline: no fuzzy-only promotion, and no fuzzy-only suppression
  either, since a one-letter-different string could in principle be a
  genuinely different asset). A human reviewer looking at
  `candidate_queue.tsv` can recognize and mark these `REJECTED`; this
  phase does not attempt that classification.
- A few ambiguous target/dev-code-adjacent mentions (`CADM1 Tesirine`,
  `M100B vedotin`, `PODO447 Vedotin`) that could be a real early-stage
  candidate description or could be generic "target-directed conjugate"
  prose -- correctly landing in `NEEDS_REVIEW`, not resolved either way by
  this mechanism.

## 5. What Phase 5a does and does not establish

- Confirms the reviewer's stated priority was correct: conference abstract
  text, once acquired (Phase 4), surfaces genuine new-candidate signal
  through the exact same low-risk mechanism already proven in Phase 3 --
  no new acquisition, no fuzzy promotion, evidence-gated throughout.
- Does **not** resolve any `NEEDS_REVIEW` row to `PROMOTED`/`REJECTED` --
  that requires either a human pass or a future, more capable
  disambiguation mechanism, explicitly out of this phase's scope.
- Does **not** attempt target/payload/linker extraction from conference
  text beyond the existing USAN/INN suffix-based payload/linker class
  inference already applied uniformly to every candidate regardless of
  source (unchanged from Phase 3).
- Does **not** implement the rest of BREADTH_PLAN.md's Phase 5 (ADC_PLATFORM
  taxonomy, company scientific-presentation source, patent-derived breadth
  mining, full component tables, target x indication feasibility table) --
  those remain later increments.

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
