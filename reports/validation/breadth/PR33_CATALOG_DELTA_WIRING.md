# PR #33 — Wire the master catalog into `update_breadth`'s derivation + delta

Per the reviewer's explicit scope for PR #33 (the second and final planned
V1 engineering increment, after PR #32's asset-extraction recall closure):
wire `DATA/catalog/adc_asset_universe.tsv` (PR #30) into
`tools/breadth/update_breadth.py`'s derivation chain and its twice-monthly
snapshot/diff, so future 14-day cadence runs automatically report new
assets, alias merges, stage changes, `catalog_status` changes, `adc_scope`
changes, new evidence sources, and NCT additions -- with zero new
detection code, by reusing the exact same generic mechanism already
proven correct for `DATA/feasibility/*.tsv`.

## 1. Derivation chain extended by one step

`DERIVATION_STEPS` gains a 4th, final step:
`candidate_queue -> feasibility_entities -> component_coverage_audit ->
build_adc_asset_universe`. `build_adc_asset_universe.py` does not read
`component_coverage_audit.tsv` -- it depends only on
`candidate_queue.tsv`/`adc_candidates.tsv` (feasibility_entities' output)
and the read-only NAR reference tables, the same upstream dependencies
`component_coverage_audit.py` has. It is appended LAST purely to leave the
existing three-step order (and its existing tests) untouched; the two
steps' relative order has no correctness effect since neither reads the
other's output.

The chain's existing fail-closed discipline (round-1 fix, PR #29) now
covers this 4th step for free: if `candidate_queue.py` fails,
`build_adc_asset_universe.py` is recorded `SKIPPED_UPSTREAM_FAILURE`
exactly like `feasibility_entities`/`component_coverage_audit` already
were, and `DELTA_STATUS: INCOMPLETE_DERIVATION` is reported with no
partial catalog rebuild diffed against stale state.

## 2. Catalog snapshot/diff via the SAME generic mechanism

`CATALOG_TABLES = [("adc_asset_universe.tsv", ["asset_id"], None)]`,
combined with `FEASIBILITY_TABLES` into `ALL_TABLE_SPECS`, which
`diff_snapshots()` now iterates over instead of `FEASIBILITY_TABLES`
alone -- `diff_snapshots()`'s own new-row/deepened/status-change logic
required NO changes at all; it was already fully generic over
(filename, key_columns, count_col, watched_fields).

- **New assets**: a brand-new `asset_id` (persistent -- `NAR_<nar_id>` for
  a reference-seeded row, `OURS_<hash>` for an ours-only row, per
  `candidate_id_for_name()`'s source-independent identity contract) is a
  new-entity event, tiered by its `catalog_status`
  (`REFERENCE_CONFIRMED`/`MULTISOURCE_CONFIRMED` -> Tier A,
  `SINGLE_STRONG_SOURCE`/`NEEDS_REVIEW` -> Tier B,
  `EXCLUDED_ADJACENT_MODALITY` -> Tier C).
- **`catalog_status` changes** (including a Tier A confirmation-strength
  upgrade into `REFERENCE_CONFIRMED`/`MULTISOURCE_CONFIRMED`, added to
  `_TIER_A_STATUS_VALUES` alongside the existing
  `PROMOTED`/`AUTO_HIGH_CONFIDENCE`/`VALIDATED` values -- these value sets
  never collide across fields, since the catalog values only ever appear
  in `catalog_status` and the others only in `validation_status`/`status`),
  **`adc_scope` changes**, **stage changes** (`highest_stage`/
  `development_status`), **new evidence sources** (`sources`), **alias/
  dev-code crosswalk merges** (`aliases`/`development_codes` -- this is
  exactly how a PR #32-style crosswalk merge becomes visible in a future
  delta), and **new NCT ids** (`nct_ids`) are all watched fields on
  `adc_asset_universe.tsv` in `STATUS_FIELDS_BY_TABLE` -- the same
  mechanism, not new code, that already surfaces a `candidate_queue.tsv`
  confidence promotion.

`write_delta_summary_tsv()`'s and `build_delta_markdown()`'s key/label
fallback chains gained `asset_id`/`canonical_name` alongside the existing
`entity_id`/`candidate_id`/`canonical_label` fallbacks, so a new catalog
row renders with a real label instead of falling through to a raw dict
dump.

## 3. `DATA/catalog/adc_clinical_development.tsv` deliberately NOT separately tracked

It is a pure column projection of `adc_asset_universe.tsv` with the exact
same row set and no information of its own, and — unlike
`adc_asset_universe.tsv` — carries no independent persistent id column
(only `canonical_name`, not guaranteed stable across an alias merge the
way `asset_id` is). Diffing it separately would duplicate every event
already captured on `adc_asset_universe.tsv` while adding a less reliable
key. It is still regenerated every run (via
`build_adc_asset_universe.py`'s own `--clinical-development-output`,
wired into `run_derivation_stage()`'s new `build_adc_asset_universe`
branch), just not separately diffed.

## 4. `--catalog-dir` CLI argument

`update_breadth.py` gains `--catalog-dir` (default `DATA/catalog`),
mirroring the existing `--feasibility-dir` pattern -- decoupled from
`--data-dir` for the same reason `--feasibility-dir` already is (a
controlled/test run can point it anywhere). `read_feasibility_snapshot()`
takes an optional `catalog_dir` parameter (default `None`, meaning "don't
track catalog tables") so existing callers/tests that only care about the
feasibility tables are unaffected; `main()` always passes it.
`run_derivation_stage()` gained a required third parameter,
`catalog_output`, used only to construct the new step's command line.

## 5. Verified against the real repository, not just unit tests

Ran `update_breadth.py --skip-acquisition` against the real repo (full
derivation chain, all 4 steps, real data) to confirm the wiring produces
no artificial baseline flood: **0 new catalog entities**, not ~1,026 --
because the "before" snapshot is read from whatever
`adc_asset_universe.tsv` already contains ON DISK at run start, and the
real committed catalog (built by PR #30/#31/#32) already existed before
this PR shipped, so before == after when no acquisition data changed.
The next real 14-day cadence run (2026-09-08, where acquisition actually
adds new manifest rows) is what will produce the first genuine catalog
delta. `git status` after this dry run showed zero diff to any committed
`DATA/` file, confirming the derivation chain is idempotent when its
upstream inputs haven't changed.

## Test plan

- 5 new tests: `_tier_for_row`'s catalog_status ladder
  (`REFERENCE_CONFIRMED`/`MULTISOURCE_CONFIRMED` -> A,
  `SINGLE_STRONG_SOURCE`/`NEEDS_REVIEW` -> B,
  `EXCLUDED_ADJACENT_MODALITY` -> C); `read_feasibility_snapshot()`
  including/excluding the catalog table depending on whether
  `catalog_dir` is passed; `diff_snapshots()` detecting a new catalog
  asset, a `catalog_status` Tier A upgrade (with `sources`/`nct_ids`/
  `highest_stage` changes on the SAME existing key correctly reported as
  non-upgrade status changes, not new rows), and an alias-merge +
  `adc_scope` change scenario.
- 2 existing tests updated for the new required `catalog_output` parameter
  and the 4th derivation step (`run_derivation_stage` skip-chain and
  all-steps-run tests).
- 1 existing test (`test_main_incomplete_derivation_...`) updated to pass
  an explicit `--catalog-dir` pointing at a tmp path, avoiding accidental
  coupling to the real repo's `DATA/catalog/` during a mocked-failure test.
- 589 tests passing project-wide, 0 regressions.
- Real end-to-end dry run against the actual repository (see Section 5).

## What this closes

Per the reviewer's own framing, this is the second and final planned V1
engineering increment (after PR #32). With this wired in, the 14-day
acquisition -> extraction -> identity-resolution -> catalog-rebuild ->
delta-report cycle is now fully closed-loop and requires no further code
changes to operate -- future code changes are reserved for the two
triggers the reviewer named: (1) a delta/benchmark-exposed systematic
miss, or (2) a genuinely new information source or naming form.
