# PR #32 — Asset-Extraction Recall Closure

Per the reviewer's explicit scope for PR #32: no new acquisition source,
only complementary high-precision extraction on top of the corpus already
acquired, plus formalizing `nar702_broad_recall.tsv` as a standing
extractor benchmark, plus a deterministic identity-duplication fix, plus
a lightweight clinical-development-oriented derived view. Stop criterion:
>=90% of NAR Phase1+ `BROAD_DISCOVERED` assets independently identified by
our own extractor; every remaining miss classified into an explicit
extraction-limitation category, never a vague "source gap."

## 1. Complementary extraction improvements

All four items requested, plus two real bugs found and fixed along the way:

1. **Appositive pattern** (`_DEV_CODE_ADC_APPOSITIVE_RE`) — catches
   `"<code>, a ... antibody-drug conjugate"` with no is/was verb (e.g.
   *"ZL-6201, a novel LRRC15-targeting antibody drug conjugate (ADC)"*),
   a real, common conference-abstract-title construction PR #31's two
   patterns did not cover.
2. **Dev-code fragment broadened** in two directions, both confirmed
   against real corpus text: (a) hyphen-optional (`BAT8008`, the real
   acquired spelling of `BAT-8008`), requiring >=3 digits in the
   hyphenless case as the false-positive guard a hyphen boundary
   otherwise provides; (b) a single optional letter directly after the
   hyphen (`SHR-A2102`, `BG-C0902`) and a single-uppercase-letter-only
   hyphenless prefix (`M7437`) — both real shapes the original fragment
   missed entirely.
3. **CT.gov structured provenance** (`build_ctgov_dev_code_candidates()`)
   — a THIRD path using CT.gov's clean, controlled `intervention_names`
   field: an entry that is itself, in its entirety, development-code-
   shaped only needs the SAME trial's own brief_title/official_title/
   conditions to independently establish ADC context (verified against
   the real corpus: 669 dev-code-shaped intervention_names entries, 55
   with real trial-level ADC context, spot-checked as genuine — e.g.
   STRO-002, SKB264).
4. **Deterministic alias/dev-code crosswalk** (`parenthetical_alias_crosswalk()`)
   — TEXT-EVIDENCE-derived (never hardcoded external pharma knowledge):
   scientific text overwhelmingly cross-references an ADC and its
   development code via direct parenthetical co-reference (*"glembatumumab
   vedotin (CDX-011)"*, *"CDX-011 (glembatumumab vedotin)"*, *"Bulumtatug
   Fuvedotin (BFv, 9MW2821)"*). Merges the dev-code candidate's own
   evidence into the existing suffix candidate instead of emitting a
   duplicate row — closes exactly the two identity-duplication examples
   the reviewer cited (`CDX-011`/glembatumumab vedotin, `9MW-2821`/
   bulumtatug fuvedotin), plus 16 more found the same way (e.g.
   `ADCT-301`/camidanlumab tesirine, `DS-7300a`/ifinatamab deruxtecan,
   `MK-2140`/zilovertamab vedotin) — 18 total merges in the real run.
   (`IMMU-130`/labetuzumab govitecan, the reviewer's third cited example,
   turned out to already resolve correctly via PR #30's own exact-match
   logic, since NAR's own record for that asset already lists `IMMU-130`
   as a synonym — verified before assuming this crosswalk was needed for it.)

**Two real bugs found and fixed during this work, not part of the
original 4-item scope but directly blocking it:**

- **Case-sensitivity bug**: the tight-grammar ADC-context patterns
  (`is/was a(n) ADC`, `ADC <code>`, the new appositive pattern) matched
  `"antibody-drug conjugate"`/`"ADC"` case-SENSITIVELY, missing the common
  Title-Case form (`"Antibody Drug Conjugate"`) that dominates CT.gov
  trial titles and many paper titles. Fixed with a scoped `(?i:...)` group
  around the phrase only, keeping the bare `ADC` abbreviation
  case-sensitive (uppercase-only) to avoid matching a stray lowercase
  "adc" substring. This alone nearly quadrupled the CT.gov signal's yield
  (27 -> 96 candidates in the real run).
- **Performance bug** (self-caught before this PR was ever run for real):
  the first working version of `parenthetical_alias_crosswalk()` compiled
  one regex PER candidate label and ran all of them against every row;
  the reverse-direction branch (`([^)]{1,80})\s+\(label\)`) has no
  literal anchor before its bounded quantifier, so the engine retried it
  at every character position — ~1.5ms per (label, row) pair regardless
  of match, which across 44 labels x ~28k rows meant 10+ minutes just for
  this one function. Rewritten to make exactly ONE pass per row: a single
  combined-alternation regex anchored on the (fast) literal label text
  for one direction, and a single regex anchored on the (fast, bounded)
  dev-code fragment for the other, checking parenthetical content against
  the label set via an O(1) dict lookup instead of a second per-label
  regex. Full-corpus crosswalk time: 8.8s (down from 10+ minutes);
  full `candidate_queue.py` run: ~18s end to end.

## 2. Suffix vocabulary expansion (data-driven finding, not in the original 4-item list)

Classifying the ~200 original misses found ~90 that were suffix-named
(not development-code-named) but ending in a USAN/INN stem NOT in
`ADC_SUFFIX_PAYLOAD_CLASS` — this was actually the SECOND-largest miss
category after development codes. Added 4 stems, each confirmed
empirically against MULTIPLE distinct NAR canonical names (same
discipline as the original 8, never a single one-off): `ravtansine` (6
NAR assets), `mertansine` (3), `talirine` (3), `duocarmazine` (2).
Payload/linker chemistry descriptions are conservative where genuinely
uncertain (e.g. `mertansine`'s linker is documented as "typical for
earlier -mertansine-class conjugates," distinct from `emtansine`'s later
SMCC chemistry, rather than asserting an exact unverified structure).
Explicitly did NOT add `sarotalocan` (Cetuximab sarotalocan) — its
photoimmunotherapy-conjugate classification is an already-disclosed open
ontology-scope question from earlier phases, and `amanitin` — payload
class is public knowledge but linker chemistry could not be confidently
documented, so it is left as a genuinely uncovered stem rather than
guessed.

## 3. Formal asset-extraction recall benchmark (new, committed tool)

`tools/breadth/asset_extraction_recall_benchmark.py` formalizes exactly
the comparison this PR's review round required manually:
`nar702_broad_recall.tsv`'s `BROAD_DISCOVERED` rows (proof the corpus
already contains this asset) joined against
`DATA/catalog/adc_asset_universe.tsv`'s `catalog_status` (proof our
extractor turned it into a catalog entry). Every miss is classified into
`DEV_CODE_SHAPED` / `UNCOVERED_SUFFIX` / `SUFFIX_COVERED_BUT_STILL_MISSED`
/ `OTHER_UNCLASSIFIED` — never left as an undifferentiated "gap." This is
now a standing, reproducible check, not an ad-hoc one-off analysis.

## 4. Real result

```
                                Before PR #32   After PR #32 (round 2)
Extractor recall (Phase1+ BROAD_DISCOVERED)   27.6% (76/275)  68.4% (188/275)
NAR-matched (independent evidence)                     95            260
ours-only                                              22            323
Catalog rows                                          725           1026
STRICT/PRESUMED ADCs                                   57            565
REFERENCE_UNCLASSIFIED                                667            460
candidate_queue.tsv rows                              170            584
```

("STRICT/PRESUMED ADCs" is `adc_scope`-axis terminology for the row count,
not a claim that all 565 are independently confirmed classical ADCs —
`catalog_status` is the separate, orthogonal evidence-strength axis, and
most of these rows are still `NEEDS_REVIEW` pending human promotion.)

**Stop criterion (>=90%) NOT reached — 68.4%, up from 27.6% (2.5x).**
Per the reviewer's own explicit instruction ("达到这个水平后就不要继续无限
优化 regex"), this PR stops here rather than continuing indefinite regex
iteration. Remaining misses, from `asset_extraction_recall_benchmark.tsv`:

| Miss cause | Count | What it means |
|---|---|---|
| `DEV_CODE_SHAPED` | 76 | development-code asset our signal still doesn't catch in its current corpus text (a further format/grammar variant, or a genuinely looser co-occurrence than this signal's tight-grammar requirement supports) |
| `UNCOVERED_SUFFIX` | 7 | a USAN/INN stem seen only once in NAR, below the multi-asset confirmation bar |
| `SUFFIX_COVERED_BUT_STILL_MISSED` | 3 | suffix is documented, but the acquired text only contains an alias/dev-code form, not the canonical generic name |
| `OTHER_UNCLASSIFIED` | 2 | needs individual inspection |

None of these are attributed to "the corpus doesn't have this asset" —
the target set is restricted to assets `nar702_broad_recall.tsv` already
proves are `BROAD_DISCOVERED`. The dominant remaining category
(`DEV_CODE_SHAPED`, 76) is a further iteration on the same signal, not a
new problem class — left for a future increment if/when the user wants
to resume this specific optimization, per their own explicit
"don't optimize regex forever" instruction.

**Round-2 fix (reviewer-identified identity-correctness blocker, not a
recall-optimization item)**: round 1 disclosed but did not fix a
compound-identifier bug — some real ADC identifiers follow a two-segment
`"<COMPANY_CODE>-<MOLECULE_CODE>"` convention (e.g. `"REGN5093-M114"`,
`"HRA00129-C004"`), and the dev-code fragment only ever matched ONE
segment at a time (confirmed: `_DEV_CODE_FRAGMENT.finditer("REGN5093-M114")`
returned two separate matches, `"REGN5093"` and `"M114"`). This was not a
recall gap but an identity-correctness bug: it fabricated two incomplete
candidate entities for one real asset, and left the correct NAR row
(`REGN5093-M114`) as `REFERENCE_UNCLASSIFIED` instead of enriching it —
and it collapsed four genuinely DISTINCT real ADCs (`HRA00129-C004`,
`HRA00184-C004`, `HRA00242-C004`, `HRA00130-C004`) into one shared
`"C004"` row, since the truncated trailing fragment alone carries no
company-code half to disambiguate them.

Fixed with a new `_DEV_CODE_COMPOUND_FRAGMENT` alternative
(`SEGMENT-SEGMENT`, where each segment independently requires its own
digit run), placed FIRST in `_DEV_CODE_FRAGMENT`'s alternation so the
regex engine prefers the full compound at a given start position over
either half alone. Verified this does not affect any existing
single-hyphen code (`"SHR-A2102"`, `"BAT-8008"`): those prefixes carry no
digit run of their own, so the compound alternative correctly fails to
match and falls through to the pre-existing single-segment alternatives,
unchanged (regression test added). Verified directly against the real
corpus that every occurrence of `REGN5093`/`M114`/`HRA00129..HRA00130`/
`C004` is the full compound form — the fix does not invent structure the
text doesn't already show.

Real result of this one fix, confirmed against the regenerated real
catalog: `REGN5093-M114` is now a single `NAR_DRG0MRJEG` row with
`catalog_status=MULTISOURCE_CONFIRMED` (was two incomplete ours-only
rows, `REGN5093` and `M114`, with the NAR row untouched); the four
`HRA*-C004` candidates are now four distinct `NEEDS_REVIEW` rows (was one
merged `C004` row). No bare `M114`/`C004`/`REGN5093` row remains in
either `candidate_queue.tsv` or `adc_asset_universe.tsv`.

Deliberately NOT extended to three-or-more-segment names (out of the
reviewer's explicitly stated scope for this fix) — that remains a
disclosed, deferred limitation.

## 5. `DATA/catalog/adc_clinical_development.tsv` (new, lightweight derived view)

Per the reviewer's request — not a new phase, purely a projection of
`adc_asset_universe.tsv`'s already-computed columns
(`canonical_name`/`aliases`/`development_codes`/`target`/`company`/
`highest_stage`/`development_status`/`nct_ids`/`adc_scope`/
`catalog_status`/`sources`), nothing recomputed. Generated automatically
alongside the master catalog by `build_adc_asset_universe.py`'s existing
`main()`. `adc_asset_universe.tsv` remains the maximal-recall superset
(1026 rows, including 460 `REFERENCE_UNCLASSIFIED` reference-only rows);
`adc_clinical_development.tsv` is the same data, reshaped for daily
industry-research use.

Non-blocking note the reviewer raised: `adc_clinical_development.tsv` is
currently a straight column projection of every master-catalog row
(including `REFERENCE_UNCLASSIFIED` reference-only rows), not filtered to
rows with an actual clinical-development stage — the name could read as
narrower than what the file contains. Left as-is this round per the
reviewer's own instruction not to block on it; a real `highest_stage`
filter (or a rename) is deferred to PR #33 or later.

## Test plan

- 28 new/updated tests: appositive pattern, hyphenless code, letter-after-
  hyphen code, single-letter-prefix code, short-target-symbol exclusion
  regression, CT.gov trial-level context requirement, CT.gov full-match-
  only requirement, parenthetical crosswalk (both directions + multi-
  alias group + empty-labels edge case), alias-crosswalk merge (both
  merge and no-op paths), new-suffix collision-safety regression
  (`soravtansine` vs `ravtansine`), new-suffix recognition, benchmark
  script (`classify_miss_cause` all branches, `compute_benchmark`
  filtering, `build_report` percentage/stop-criterion text), clinical-
  development view projection, round-2 compound-identifier fix (keeps
  `"REGN5093-M114"` whole, keeps the four distinct `HRA*-C004` codes
  distinct, leaves an ordinary single-hyphen code like `"SHR-A2102"`
  unaffected)
- 584 tests passing project-wide, 0 regressions
- Real end-to-end run: `candidate_queue.py` -> `feasibility_entities.py`
  -> `component_coverage_audit.py` -> `build_adc_asset_universe.py` ->
  `asset_extraction_recall_benchmark.py`, against the real repository
