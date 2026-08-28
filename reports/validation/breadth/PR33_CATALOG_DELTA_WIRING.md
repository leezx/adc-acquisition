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
  `development_status`), **new evidence sources** (`sources`), **PR
  #32-level alias/dev-code crosswalk merges** (`aliases`/
  `development_codes` -- this is the case where
  `parenthetical_alias_crosswalk()` merges a dev-code candidate's evidence
  into an already-discovered suffix candidate's OWN row, in
  `candidate_queue.py`, BEFORE `build_adc_asset_universe.py` ever runs --
  the candidate's own key never changes, so this is a genuine same-`asset_id`
  field change), and **new NCT ids** (`nct_ids`) are all watched fields on
  `adc_asset_universe.tsv` in `STATUS_FIELDS_BY_TABLE` -- the same
  mechanism, not new code, that already surfaces a `candidate_queue.tsv`
  confidence promotion.

`write_delta_summary_tsv()`'s and `build_delta_markdown()`'s key/label
fallback chains gained `asset_id`/`canonical_name` alongside the existing
`entity_id`/`candidate_id`/`canonical_label` fallbacks, so a new catalog
row renders with a real label instead of falling through to a raw dict
dump.

## 3. Round-1 fix (reviewer-identified correctness blocker): identity-merge detection

The initial version's claim that "alias/identity merge" is visible via
the field-change mechanism above was WRONG for the one identity event
that actually matters most: `build_master_rows()`'s own semantics are
that a candidate LATER found to exact-match a NAR row is folded INTO that
NAR row (the NAR row's own `evidence_ids` gains the candidate's key) and
the candidate's OWN `OURS_<key>` row simply STOPS being emitted -- the
NAR row's `asset_id` never changes, so this is a key disappearing
entirely, not a field changing on an existing key. `diff_snapshots()`
only ever iterated over AFTER rows (new-if-absent-from-before,
changed-if-present-in-both) -- a before-only key was silently invisible
to every mechanism in the initial version.

Fixed with `IDENTITY_MERGE_EVIDENCE_FIELD` (`{"adc_asset_universe.tsv":
"evidence_ids"}`) and a new block in `diff_snapshots()`: for a before-only
key on a table in this map, look up its own evidence-id token(s) against
every AFTER row's `evidence_ids` field. An exact token match names the
survivor (`identity_merges_by_table`, `{from_key, to_key}`); no match at
all is reported honestly as `unresolved_removals_by_table` rather than a
guessed merge target -- this is a deterministic exact-token lookup,
reusing `build_master_rows()`'s own evidence-id bookkeeping, never a
fuzzy label comparison. `diff_snapshots()`'s return signature grew from a
3-tuple to a 5-tuple; every call site (9 in tests, 1 in `main()`) was
updated to unpack the two new values.

New `write_identity_merges_tsv()` writes `identity_merges.tsv`
(`table`/`kind`/`from_key`/`to_key`, `kind` = `IDENTITY_MERGE` or
`UNRESOLVED_REMOVAL`) alongside the existing `delta_summary.tsv`/
`status_changes.tsv`. `build_delta_markdown()` gained two new sections,
"Identity merges" and "Unresolved removals."

**Verified against the real repository's own history, not just the
reviewer's synthetic regression.** Ran the actual pre-round-2-fix
`adc_asset_universe.tsv` (commit `45af0d3`, before PR #32's compound-
identifier fix) as the "before" snapshot against the current real catalog
as "after" -- the real transition where the two-fragment bug's 6 stray
`OURS_*` rows (`REGN5093`, `M114`, `C004`, and 3 more) disappeared.
Result: **0 identity merges, 6 unresolved removals, 4 new assets** -- NOT
identity merges. This is the CORRECT, honest answer, not a mechanism
failure: the compound-identifier fix changed how the candidate's own
label is extracted (e.g. `"M114"` alone vs. the full `"REGN5093-M114"`
compound), which changes its normalized-label-derived key entirely (per
`candidate_id_for_name()`), so there is no shared evidence token between
the old and new rows to find -- a genuinely different transition shape
than "the same stable candidate later resolves against NAR," which is
exactly the reviewer's specified scenario and is what the new synthetic
regression test (`test_diff_snapshots_detects_identity_merge_into_nar_row`)
verifies directly. Both the positive case (a real merge is found by exact
evidence-token match) and this honest-negative case (a genuine key change
is correctly reported as removal + new-asset, never guessed as a merge)
are now covered.

## 4. `DATA/catalog/adc_clinical_development.tsv` deliberately NOT separately tracked

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

## 5. `--catalog-dir` CLI argument

`update_breadth.py` gains `--catalog-dir` (default `DATA/catalog`),
mirroring the existing `--feasibility-dir` pattern -- decoupled from
`--data-dir` for the same reason `--feasibility-dir` already is (a
controlled/test run can point it anywhere). `read_feasibility_snapshot()`
takes an optional `catalog_dir` parameter (default `None`, meaning "don't
track catalog tables") so existing callers/tests that only care about the
feasibility tables are unaffected; `main()` always passes it.
`run_derivation_stage()` gained a required third parameter,
`catalog_output`, used only to construct the new step's command line.

## 6. Verified against the real repository, not just unit tests

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

- 7 new tests: `_tier_for_row`'s catalog_status ladder
  (`REFERENCE_CONFIRMED`/`MULTISOURCE_CONFIRMED` -> A,
  `SINGLE_STRONG_SOURCE`/`NEEDS_REVIEW` -> B,
  `EXCLUDED_ADJACENT_MODALITY` -> C); `read_feasibility_snapshot()`
  including/excluding the catalog table depending on whether
  `catalog_dir` is passed; `diff_snapshots()` detecting a new catalog
  asset, a genuine `catalog_status` Tier A upgrade on a stable
  `adc_candidates.tsv`-origin `asset_id` (with `sources`/`nct_ids`/
  `highest_stage` changes on the SAME existing key correctly reported as
  non-upgrade status changes, not new rows), an alias-merge +
  `adc_scope` change scenario, the reviewer's exact identity-merge
  regression (`test_diff_snapshots_detects_identity_merge_into_nar_row`),
  and the honest-unresolved-removal case (no survivor found).
- 2 existing tests updated for the new required `catalog_output` parameter
  and the 4th derivation step (`run_derivation_stage` skip-chain and
  all-steps-run tests).
- 1 existing test (`test_main_incomplete_derivation_...`) updated to pass
  an explicit `--catalog-dir` pointing at a tmp path, avoiding accidental
  coupling to the real repo's `DATA/catalog/` during a mocked-failure test.
- 9 existing `diff_snapshots()` call sites (8 in tests, 1 in `main()`)
  updated to unpack the new 5-tuple return.
- 1 existing test's scenario corrected: the original
  `test_diff_snapshots_detects_catalog_status_upgrade_as_tier_a` used a
  `NEEDS_REVIEW -> MULTISOURCE_CONFIRMED` transition on the SAME
  `OURS_<key>` asset_id, which is impossible under `catalog_status_for_
  ours_only()`'s real logic for a `candidate_queue.tsv`-origin candidate
  (always `NEEDS_REVIEW` until either promoted or identity-merged into
  NAR) -- corrected to a `SINGLE_STRONG_SOURCE -> MULTISOURCE_CONFIRMED`
  transition on a stable `adc_candidates.tsv`-origin `asset_id`, the
  actual real scenario that mechanism covers.
- 591 tests passing project-wide, 0 regressions.
- Real end-to-end dry run against the actual repository (see Section 6),
  PLUS a real-history identity-merge check against the actual pre-PR-#32-
  round-2-fix catalog snapshot (see Section 3).

## What this closes

Per the reviewer's own framing, this is the second and final planned V1
engineering increment (after PR #32). With this wired in, the 14-day
acquisition -> extraction -> identity-resolution -> catalog-rebuild ->
delta-report cycle is now fully closed-loop and requires no further code
changes to operate -- future code changes are reserved for the two
triggers the reviewer named: (1) a delta/benchmark-exposed systematic
miss, or (2) a genuinely new information source or naming form.
