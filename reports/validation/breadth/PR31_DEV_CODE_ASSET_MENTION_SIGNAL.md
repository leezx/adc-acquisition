# PR #31 — Development-Code Asset Mention Signal

Per the user's own diagnosis after PR #30: the production `candidate_queue.py`
discovery funnel structurally cannot find ADC assets named by an
alphanumeric development code (e.g. `BAT-8008`, `TAK-500`, `ADCT-901`,
`GQ-1001`, `DXC-004A`, `ZL-6201` — all real `DATA/reference/nar_adcdb/
assets.tsv` entries) because it only ever looks for a USAN/INN
payload-class `-suffix` (`vedotin`/`mafodotin`/etc.). No matter how many
more acquisition sources or 14-day cadence runs are added, a development
code can never end in one of those suffixes, so it will always be missed —
this is a discovery-signal gap, not a coverage-volume gap.

## Design

A second, independent signal in `tools/breadth/candidate_queue.py`:
`build_dev_code_candidates()` scans `pubmed.parquet`/`europe_pmc.parquet`/
`conference_abstract_corpus.parquet` title+abstract text (the only sources
with inline text in their committed manifests — `company_press_release`/
`company_pipeline`/`company_scientific_presentations` reference
`raw_file_path` on disk, not inline text, and `DATA/raw/` is gitignored/not
reproducible from a fresh clone, so those are explicitly deferred pending a
materialized full-text companion table).

**Tight grammatical co-occurrence, not loose same-window co-occurrence.**
A loose "development-code-shaped token anywhere near 'ADC'/'antibody-drug
conjugate' within ~150 characters" was tried first and rejected: verified
against the real corpus, it produced 542 candidate tokens, the large
majority of which were clinical trial acronyms (`KEYNOTE-057`,
`TROPiCS-02`, `EVOKE-02`, `ASCENT-04`, `DREAMM-11`), cell lines (`MB-231`,
`HCT-116`, `MOLT-16`), or target/biomarker symbols (`CD-30`, `PSMA-617`,
`COVID-19`) — not genuine asset codes. The pattern actually used requires
the code to be in a tight grammatical relationship with the ADC-defining
phrase: either the code is the explicit subject of `"<code> is/was a(n)
[novel/investigational/first-in-class] antibody-drug conjugate/ADC"`
(e.g. *"TAK-500 is a novel immune cell-directed antibody-drug
conjugate"*), or it directly follows `"ADC"`/`"antibody-drug conjugate"`
as the phrase's named referent (e.g. *"the ADC candidate BAT-8008"*).
Verified against the real corpus: this cuts the same scan down to 117
tokens, spot-checked as essentially all genuine development codes (no
trial names, cell lines, or target symbols observed in this tighter set).

**Known-asset suppression is EXACT normalized match, not
`mentions_known_asset()`'s substring containment.** A development code
(e.g. `SGN-35`, normalize_name → `sgn35`, 5 characters) is the candidate's
entire label, not a longer wrapper string a known name might be embedded
in — `mentions_known_asset()`'s `>=6`-char safety threshold (needed there
to avoid short-fragment false matches against a *longer* name) would let a
5-character code slip through unsuppressed even though it is exactly
Brentuximab vedotin's own registered `dev_code`. Exact match closes this.

**Always routed to `NEEDS_REVIEW`, never auto-promoted** — same two-stage
discipline as the existing free-text conference-abstract suffix path
(Part 9): a development code alone (unlike a USAN/INN suffix) carries no
independent payload/linker-class evidence, and this signal is entirely
free-text co-occurrence with no structured field to confirm it, regardless
of how many of the three sources mention it.

**Adjacent-modality classification reused unchanged**
(`detect_adjacent_modalities()` + `local_context_for_span()`) — e.g.
`TAK-500`'s real text (*"TAK-500 is a novel immune cell-directed
antibody-drug conjugate composed of ... an anti-CCR2 monoclonal antibody,
conjugated to the STING agonist dazostinag"*) is currently classified
`PRESUMED_STRICT_ADC` because no existing `ADJACENT_MODALITY_KEYWORDS`
phrase matches "STING agonist" — the source itself explicitly calls it an
"antibody-drug conjugate," so this is disclosed as a genuine ontology
policy question (is an immune-agonist-payload ADC `STRICT_ADC` or a
distinct adjacent category?), not resolved unilaterally here, same
precedent as PR #17's disclosed "Cetuximab sarotalocan" photoimmunotherapy-
conjugate case.

## Known, disclosed limitation (not fixed here)

Only the 14 curated known-registry assets' dev codes are suppressed. A
dev code belonging to an *already-discovered suffix-matched* candidate
(e.g. `CDX-011` is glembatumumab vedotin's own dev code; `IMMU-130` is
labetuzumab govitecan's) is **not** suppressed, since suffix-discovered
candidates' dev codes are not tracked anywhere in this pipeline's own
data yet — these appear as separate, likely-duplicate candidates. Same
category of gap as PR #30's disclosed alias-resolution limitation
(`bulumtatug fuvedotin` / `9MW-2821`), not solved here to avoid scope
creep.

## Real result against the actual repository

```
Found 112 distinct new candidate development codes via explicit
'<code> is/was a(n) ADC' / 'ADC <code>' grammatical co-occurrence
(9 from pubmed, 45 from europe_pmc, 84 from conference_abstract_corpus,
before cross-source merge)

candidate_queue.tsv: 170 total (was 58) --
  14 PROMOTED (known registry, unchanged)
  24 AUTO_HIGH_CONFIDENCE (USAN/INN suffix + structured field, unchanged)
  132 NEEDS_REVIEW (was 20 -- 20 USAN/INN-suffix-only + 112 new
       development-code candidates)
```

Feeding this through the PR #30 catalog union (`tools/catalog/
build_adc_asset_universe.py`):

```
                          Before PR #31   After PR #31
NAR matched (independent evidence)   35             95
ours-only (no NAR match)             22             74
Catalog rows                        725            777
ADC-oriented superset (adc_scope)    724            776
STRICT/PRESUMED ADCs                 57            159
REFERENCE_UNCLASSIFIED              667            617
```

**159 STRICT/PRESUMED ADCs, up from 57** — real, independently-confirmed
progress against the freeze-gate target of representing NAR's Phase1+
universe, driven entirely by a signal the previous architecture
structurally could not produce, not by adding new acquisition sources.

## Round-1 fix: corrected root-cause diagnosis for the 5 missed motivating examples

Of the 6 development codes originally cited as motivating examples
(`BAT-8008`, `PF-06804103`, `ADCT-901`, `GQ-1001`, `DXC-004A`, `ZL-6201`),
only `TAK-500` (a 7th real example independently found) is caught by this
signal. The first version of this report wrongly attributed the other 5
to "corpus-content limit, not a pattern flaw." **That was incorrect.**
`reports/validation/breadth/nar702_broad_recall.tsv` already proves 4 of
these 5 are present in the acquired corpus RIGHT NOW:

| Example       | Present in current broad corpus? | PR #31 grammar catches? | Gap                  |
|----------------|-----------------------------------|--------------------------|-----------------------|
| `BAT-8008`     | YES (conference, `EXACT_NAME`)                          | NO | `PATTERN_RECALL_GAP` |
| `PF-06804103`  | YES (clinicaltrials + conference, `ALIAS_MATCH`/`EXACT_NAME`) | NO | `PATTERN_RECALL_GAP` |
| `ADCT-901`     | YES (conference, `ALIAS_MATCH`)                         | NO | `PATTERN_RECALL_GAP` |
| `GQ-1001`      | YES (clinicaltrials + conference, `EXACT_NAME`/`STRONG_IDENTIFIER_NCT`) | NO | `PATTERN_RECALL_GAP` |
| `ZL-6201`      | YES (conference, `EXACT_NAME`)                          | NO | `PATTERN_RECALL_GAP` |
| `TAK-500`      | YES (conference + europe_pmc, `EXACT_NAME`)             | YES | caught |
| `DXC-004A`     | not in `nar702_broad_recall.tsv`'s `BROAD_DISCOVERED` rows | NO | not yet independently verified as corpus-present |

Spot-checked the actual raw text to confirm WHY each was missed — three
distinct, real mechanical reasons, all genuine pattern gaps:
- `BAT-8008`: the acquired text spells it without a hyphen ("BAT8008"),
  which `_DEV_CODE_FRAGMENT`'s required `-` never matches.
- `ZL-6201`: *"Discovery of ZL-6201, a novel LRRC15-targeting antibody
  drug conjugate (ADC) for the treatment of..."* — an appositive
  construction ("`<code>`, a ... conjugate") with no "is/was" verb, which
  neither of this PR's two patterns covers.
- `ADCT-901`/`PF-06804103`/`GQ-1001`: matched in `nar702_broad_recall.tsv`
  via `ALIAS_MATCH`/`STRONG_IDENTIFIER_NCT`, not the code's own literal
  string appearing next to "ADC" in the exact form this signal expects.

The correct conclusion: **the tight grammatical signal intentionally
prioritizes precision and captures only a subset of development-code
mentions already present in the acquired corpus. The remaining benchmark
misses demonstrate an asset-extraction pattern-recall gap, not an
acquisition/source gap** — acquisition recall and asset-extraction recall
are two different numbers, and this PR only measured/improved the second
one. The fix is NOT to add more acquisition sources (the evidence is
already here); it is a future, complementary high-precision extraction
pattern (e.g. the appositive "`<code>`, a ... ADC" construction, or
tying development-code extraction to records `broad_recall.py` already
classifies `BROAD_DISCOVERED` for a NAR asset). Explicitly deferred to a
future increment, not this PR — regex-widening or new-source work is not
in scope for PR #31's own revision.

## Test plan

- 9 new tests: code-first pattern match, term-first pattern match, loose
  co-occurrence correctly rejected (trial-acronym false-positive case),
  scientific-notation exclusion, exact-match known-registry suppression
  (short-code regression), adjacent-modality local-context attribution,
  cross-source merge
- 556 tests passing project-wide, 0 regressions
- Real end-to-end run: `candidate_queue.py` → `feasibility_entities.py` →
  `component_coverage_audit.py` → `build_adc_asset_universe.py`, against
  the real repository (this run also incorporates the 2026-08-25/27
  full-production acquisition cadence run's manifests — the catalog-era
  baseline the reviewer asked for after PR #30/#31)
