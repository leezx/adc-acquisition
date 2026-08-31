# PR #38: V1.1 integration + saturation closure

## Why

PR #34 (WHO ICTRP), #36 (China CDE), and #37 (conference Crossref search)
all closed acquisition-layer gaps, but `tools/breadth/candidate_queue.py`
-- the ONLY entry point into candidate discovery, and from there into
`DATA/catalog/adc_asset_universe.tsv` (the master catalog) -- never read
any of their manifests. Acquisition without integration is not a closed
loop: this PR wires the two sources that should feed candidate discovery,
keeps WHO ICTRP diagnostic-only per its licensing constraint, and measures
the real marginal yield rather than declaring victory on record counts.

## What changed

**`build_conference_suffix_candidates()` generalized.** Previously
hardcoded `sources={"conference_abstract_corpus"}`; now takes an optional
`source_name` parameter (default unchanged, so every existing caller/test
is untouched). This is the SAME already-hardened free-text scanning logic
(USAN/INN payload-suffix extraction, `_iter_adc_generic_name_matches()`,
local-context modality attribution) reused for two more sources, not a
new extractor.

**`conference_crossref_search.parquet` wired in directly** -- it's already
title+row-shaped exactly like `conference_abstract_corpus.parquet` (it has
no `abstract` column at all, which the existing `.get()`-based lookups
already tolerate). Both existing signals now scan it:
`build_conference_suffix_candidates(ccs_df, known_ids,
source_name="conference_crossref_search")` and
`build_dev_code_candidates(ccs_df, "conference_crossref_search",
known_ids)` (the latter was already source-parameterized, no change
needed). Also added to `parenthetical_alias_crosswalk`'s corpora list.

**`china_drug_trials.parquet` wired in via a concatenated text view.**
Unlike every other source, CDE has no single title+abstract field --
its potentially ADC-relevant text is split across `title` (public_title),
`drug_name`, and `indication`. `candidate_queue.py`'s `main()` builds a
synthetic `title` column (`title + " " + drug_name + " " + indication`)
so the SAME two generic signals can be reused unmodified, rather than
writing a bespoke CDE-only extractor.

**WHO ICTRP stays diagnostic-only -- confirmed, not just asserted.**
Verified independently (not just "we didn't touch it"): no code path in
`candidate_queue.py`, `feasibility_entities.py`, or
`build_adc_asset_universe.py` reads `who_ictrp.parquet` -- the only
mentions of `who_ictrp` in the codebase are its own job registration and
a prose comparison in `jobs/china_drug_trials/report.py`. Added an
explicit comment in `candidate_queue.py`'s `main()` recording WHY (WHO
ICTRP's non-commercial-research-use terms vs. this catalog's commercial
use), so a future contributor doesn't wire it in without re-checking that
constraint.

## Disclosed finding -- China CDE contributes ZERO candidates via current signals

Running the real pipeline: **0** suffix-matched and **0** dev-code-matched
candidates from `china_drug_trials.parquet`, despite this repo's own PR
#36 write-up confirming the acquired corpus DOES contain real ADC-relevant
trials (RC48-ADC/disitamab vedotin, F0002-ADC, ATG-022, STI-6129,
SSGJ-612). This is NOT a wiring bug -- it is a genuine, disclosed
STRUCTURAL LIMITATION: `drug_name`/`title`/`indication` in this source are
predominantly Chinese-language, while every candidate-discovery signal in
this repo is built for English USAN/INN nomenclature (`-vedotin`,
`-deruxtecan`, ...) and English ADC-context grammar (`"<code> is a novel
antibody-drug conjugate"`). Confirmed the specific gap: development codes
like "RC48" are 2-digit-suffixed and self-declare via a `-ADC` compound
suffix in the source text ("RC48-ADC") -- a pattern this repo's
`_DEV_CODE_FRAGMENT` regex correctly does NOT match (it requires >=3
digits in a hyphenless suffix specifically to exclude 2-digit
target/biomarker symbols like "HER2"/"CD30"; loosening that guard to catch
"RC48" risks reintroducing exactly the false-positive classes PR #31/#32
spent multiple rounds excluding). Not fixed this round -- deliberately
scoped out rather than hastily loosening a carefully-hardened shared
regex; see "Recommendation" below.

## Saturation audit (real run, `update_breadth.py --skip-acquisition`)

Baseline restored to the pre-#38 committed state, then
`tools/breadth/update_breadth.py --skip-acquisition --data-dir DATA
--delta-output reports/delta` run for real (derivation-only -- both
sources' acquisition already ran and is committed in #36/#37). Full delta
report: `reports/delta/2026-08-31/ADC_BREADTH_DELTA.md`.

| Source | Acquired records | Candidate contributions (suffix + dev-code) | New `candidate_queue.tsv` rows | New master-catalog rows (`adc_asset_universe.tsv`) | Existing master-catalog rows cross-confirmed | `catalog_status` upgrades |
|---|---:|---:|---:|---:|---:|---:|
| China CDE | 41 | 0 | 0 | 0 | 0 | 0 |
| Conference Crossref Search | 1,477 | 58 (7 suffix, 51 dev-code) | 8 | 3 (Enfotulumab vedotin, F0002, HDM2005) | 53 | 5 (`REFERENCE_CONFIRMED` -> `MULTISOURCE_CONFIRMED`) |

**Result summary** (from the real delta): 11 new Tier B entities total (8
in `candidate_queue.tsv`, 3 flowing through into
`adc_asset_universe.tsv`), 0 Tier A auto-promotions (correctly
conservative -- conference_crossref_search alone never auto-promotes, per
`status_and_confidence_for_sources()`, unchanged), 0 Tier C, 0 acquisition
failures, 0 unresolved removals. Catalog totals:
`TOTAL CATALOG ROWS` 1026 -> 1029, `REFERENCE_CONFIRMED` 460 -> 455,
`MULTISOURCE_CONFIRMED` 244 -> 249, `NEEDS_REVIEW` 316 -> 319 -- the 5
`catalog_status` upgrades are the most notable finding: five NAR-reference
rows that had ZERO acquired-source confirmation before now have real,
independent acquired evidence for the first time, specifically because of
conference_crossref_search.

The 8 new `candidate_queue.tsv` rows vs. only 3 new
`adc_asset_universe.tsv` rows is expected, not a discrepancy: the other 5
(HS-20089, RC118, Abbv-319, ABBV155, AZD0305) resolved by exact-identifier
match into EXISTING NAR-reference rows during catalog construction (see
`build_adc_asset_universe.py`'s identity-resolution step) rather than
becoming new master rows -- itself a form of cross-confirmation, already
counted in the "existing rows cross-confirmed" column above via their
`sources` field gaining `conference_crossref_search`.

## Recommendation: V1.1 source-universe freeze, with one disclosed follow-up

Per the stopping rule agreed before this PR (most results cross-confirm
the existing catalog; each source contributes a bounded number of
genuinely new assets, not proof of exhaustive coverage): **freeze new
ACQUISITION sources after this PR.** No PMDA, CNIPA, Google Scholar,
additional patent databases, or additional conferences unless the 14-day
maintenance cadence surfaces a systematic miss (a batch of real Phase 1+
ADCs concentrated in one uncovered source).

One item explicitly NOT covered by this freeze, because it is an
EXTRACTION-signal gap on already-acquired data, not a new source: China
CDE's real ADC content is currently invisible to this repo's
English-language-only candidate-discovery signals (see disclosed finding
above). A future increment could add a narrow, Chinese-language-aware (or
exact known-alias/dev-code crosswalk against `configs/known_adc_assets.yaml`,
using Chinese aliases if added there) extraction path for this one source
-- deliberately deferred, not silently dropped.

## Round-1 fix (reviewer-flagged): maintenance-cadence default Crossref window

The V1.1 freeze baseline this PR reports (1,477 records, 3 new master
assets, 53 cross-confirmations, 5 `catalog_status` upgrades) was acquired
with `conference_crossref_search --since 2022-01-01`. `update_breadth`'s
ordinary 14-day maintenance cadence calls every job with NO `--since` at
all -- without a fix, the first ordinary cadence run after this freeze
would silently become an undeclared full-history backfill (a materially
larger effective query, with its own brand-new `query_id`s under PR #37's
own provenance design) instead of an incremental maintenance run.

Fixed in the SOURCE's own config, not as a special case in
`update_breadth.py` (which must stay source-agnostic per its own
orchestrator design): `configs/conference_crossref_search.yaml` now
declares `default_since: "2022-01-01"`; `job.py`'s `run()` resolves
`effective_since = args.since or default_since` and uses it EVERYWHERE
(the Crossref `from-pub-date` filter, the effective query_text/query_id,
the acquisition report, and the reproduction command). Verified against
LIVE Crossref: running `python -m adc_acquisition conference_crossref_search
--output DATA` (no `--since`) reproduced the committed baseline exactly --
`records_discovered=1477`, `records_skipped_unchanged=1477`, and the
resulting manifest content is byte-for-byte identical (sorted) to the
committed one. 2 new regression tests: a no-`--since` run vs. an explicit
`--since 2022-01-01` run produce the identical query_id/query_text/date
filter, and an explicit `--since` still overrides the config default for
a deliberate future historical backfill.

**Two non-blocking nits also fixed in passing (as requested, not a
separate round):** (1) `update_breadth.py`'s committed
`ADC_BREADTH_DELTA.md` reproduction command now reflects the actual flags
used for that run (e.g. `--skip-acquisition`) instead of always printing
the bare acquisition-included default -- `DeltaResult` gained a
`reproduction_command` field computed from the real parsed args in
`main()`; 1 new regression test. (2) Test-count documentation below is the
current, re-verified number.

## Tests

8 new tests total: 5 in `tests/tools/breadth/test_candidate_queue.py`
(`source_name` parameterization, missing-`abstract`-column tolerance, the
china_drug_trials concatenated-text reuse pattern, and the
china_drug_trials-only-stays-`NEEDS_REVIEW` regression), 2 in
`tests/jobs/conference_crossref_search/test_job.py` (the
`default_since` round-1 fix above), 1 in
`tests/tools/breadth/test_update_breadth.py` (the reproduction-command
nit fix above).

Full suite: 685 passed.

## Live verification

Ran `tools/breadth/candidate_queue.py` directly against the real,
committed manifests, then the full `update_breadth.py --skip-acquisition`
pipeline (candidate_queue -> feasibility_entities ->
component_coverage_audit -> build_adc_asset_universe), with the baseline
restored to the pre-#38 committed state first so the delta report's
before/after snapshot is a true comparison. `DATA/feasibility/*.tsv`,
`DATA/catalog/adc_asset_universe.tsv` + `adc_clinical_development.tsv`,
`reports/validation/breadth/ADC_ASSET_UNIVERSE_COVERAGE.md`, and
`reports/delta/2026-08-31/` (`ADC_BREADTH_DELTA.md`, `delta_summary.tsv`,
`status_changes.tsv`) committed with this PR as the real evidence trail.

## Reproduction command

```bash
python3 tools/breadth/update_breadth.py --skip-acquisition \
  --data-dir DATA --delta-output reports/delta
```
