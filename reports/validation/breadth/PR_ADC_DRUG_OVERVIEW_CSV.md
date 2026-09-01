# Add: comprehensive ADC drug overview CSV (user request)

## Why

The user asked for a single, comprehensive CSV -- one row per ADC drug,
covering target/linker/payload/indication/company/clinical phase -- to
overview this system's results at a glance, regenerated (with new drugs
appended at the tail) every time the database updates.

## What this is

`tools/catalog/build_adc_drug_overview.py`: reads
`DATA/catalog/adc_asset_universe.tsv` (the full ~1,000-row master catalog,
PR #30 -- target/company/clinical-phase/evidence-strength for every row)
and enriches it with `DATA/feasibility/adc_candidates.tsv` (the smaller,
~40-row VALIDATED-tier feasibility table, Phase 3 -- the only table in this
repo that carries payload/linker/indication at all) via exact
`evidence_ids`-contains-`entity_id` matching. Writes
`DATA/catalog/adc_drug_overview.csv`.

Columns: `asset_id, row_status, canonical_name, aliases, development_codes,
target, payload, linker, indication, company, clinical_phase,
development_status, adc_scope, catalog_status, source_count, sources,
nct_ids, date_added_to_table`.

This is one row per **master-catalog asset**, not a claim that every row
is an independently-confirmed classical ADC -- `adc_scope` and
`catalog_status` are preserved specifically to carry that uncertainty
(the master catalog is an explicit high-recall superset, including
`REFERENCE_UNCLASSIFIED` and adjacent-conjugate-modality rows).

## Stable, append-only row order (explicit user request)

Re-running this script against a growing master catalog never reorders or
renumbers an existing row. Every previously-written row (keyed by its own
stable `asset_id`) keeps its exact prior position; only genuinely NEW
`asset_id`s are appended at the tail (sorted for determinism among the new
batch). Each newly-appended row is stamped with `date_added_to_table` --
the date it was FIRST added to THIS csv, an operational bookkeeping date,
never re-stamped on later re-runs. This is deliberately NOT the same
thing as `first_seen` (the underlying source's own scientific/evidence
date, when known, and often blank).

A previously-written `asset_id` that no longer appears in the base
catalog (rare -- only via a genuine identity merge, see
`build_adc_asset_universe.py`'s own `IDENTITY_MERGE` handling) is kept as
its last-known historical row, not silently dropped, but is explicitly
marked `row_status = STALE_HISTORICAL` (see Round-1 fix below) so it can
never be mistaken for a currently-active asset.

## Disclosed limitation: payload/linker/indication coverage is partial

Only 43 of 1,029 rows (the ones matched against `adc_candidates.tsv`) have
a known payload/linker/indication -- every other row leaves those three
columns BLANK, honestly disclosing "not independently known to this
system's structured data," never guessed or defaulted. This mirrors
`adc_asset_universe.tsv`'s own schema limitation (it never carried these
fields), not something this tool invents evidence to fill in.

Also disclosed: `indication` values are the RAW, unnormalized condition
lists inherited directly from `adc_candidates.tsv` (itself sourced from
ClinicalTrials.gov's own free-text `conditions` field) -- e.g.
Enfortumab vedotin's indication list runs to ~130 semicolon-joined
condition strings, not deduplicated or canonicalized. Left as-is rather
than silently "cleaned," since normalizing indication taxonomy is a
separate, nontrivial feasibility-layer concern out of scope here.

## Round-1 fix (reviewer-flagged): 2 blockers

**Blocker 1 -- `clinical_phase` read the wrong field.** The initial
version used `catalog_row.get("development_status")`, but
`development_status` is a messy free-text field, not a standardized
clinical stage -- proven by real data: Raludotatug deruxtecan's
`development_status` is `"Investigative Drug-to-Antibody Ratio 8 3D"`,
clearly not a clinical phase. Fixed by switching `clinical_phase` to read
`catalog_row.get("highest_stage")` (the base catalog's standardized stage
code) and keeping `development_status` as its own separate output
column, so no information is lost. Regenerated CSV confirms the fix:
Raludotatug deruxtecan now reads `clinical_phase = Investigative`,
`development_status = Investigative Drug-to-Antibody Ratio 8 3D`. New
regression test:
`test_clinical_phase_uses_standardized_highest_stage_not_messy_development_status`.

**Blocker 2 -- stale/merged-away rows were indistinguishable from
current active assets.** The append-only design correctly kept historical
rows whose `asset_id` disappeared from the live catalog, but gave no
signal separating them from genuinely current rows. Fixed by adding a
`row_status` column: `ACTIVE` for rows currently in the base catalog,
`STALE_HISTORICAL` for rows only present in a prior overview run.
Deliberately not named `MERGED`, since this script cannot itself prove
every disappearance is a genuine identity merge --
`STALE_HISTORICAL` is the more honest, minimal-assumption label. This
preserves all three requirements at once: stable row position, append-only
history, and current one-row-per-asset semantics (by filtering to
`row_status = ACTIVE`). Existing test
`test_asset_removed_from_catalog_is_kept_as_stale_historical_row_not_dropped`
now also asserts `row_status == STALE_HISTORICAL`.

Also applied the reviewer's requested wording correction: "one row per
ADC drug" tightened to "one row per master-catalog asset" (see Columns
section above).

## Wired into the maintenance cadence

Added as a 5th step in `tools/breadth/update_breadth.py`'s derivation
chain, after `build_adc_asset_universe` (which it depends on):
`candidate_queue -> feasibility_entities -> component_coverage_audit ->
build_adc_asset_universe -> build_adc_drug_overview`. Every future 14-day
`updateDB.sh` cadence run regenerates this CSV automatically, appending
any genuinely new ADC assets at the tail per the stable-ordering
guarantee above -- exactly the "when you update the database, add new ADC
drugs to the tail of this table" behavior requested.

## Live verification

Ran against the real, current catalog: 1,029 total rows, 43 with a
payload/linker/indication enrichment match. Re-ran after the round-1 fix
against the real catalog: all 1,029 rows regenerated with the corrected
schema, all currently `row_status = ACTIVE` (no rows have dropped out of
the catalog since the last run), Raludotatug deruxtecan spot-checked and
confirmed correct (see Round-1 fix above). Also previously spot-checked
real, correct data for known approved ADCs (Trastuzumab emtansine: HER2 /
DM1 (maytansinoid) / SMCC non-cleavable linker / Genentech, Inc /
Approved (FDA): Feb 22, 2013; Sacituzumab govitecan: TROP2 / SN-38 /
cleavable CL2A linker / Gilead Sciences, Inc / Approved (FDA): Apr,
2020).

## Tests

13 tests in `tests/tools/catalog/test_build_adc_drug_overview.py`:
enrichment join (present and absent), the round-1
`clinical_phase`/`highest_stage` regression, stable row-order
preservation across reruns, `date_added_to_table` stamped once and never
re-stamped, a pure no-op re-run, stale/merged-away rows kept not dropped
and marked `STALE_HISTORICAL`, deterministic tail-append ordering for
multiple simultaneous new assets, CSV write/reload round-trip,
NaN-to-None conversion, missing-file handling, and a full `main()`
end-to-end test. Plus 2 updated tests in
`tests/tools/breadth/test_update_breadth.py` confirming the new 5th
derivation step is wired correctly (both the normal-run and
skip-after-failure paths).

Full suite: 698 passed.

## Reproduction command

```bash
python3 tools/catalog/build_adc_drug_overview.py \
  --catalog-file DATA/catalog/adc_asset_universe.tsv \
  --candidates-file DATA/feasibility/adc_candidates.tsv \
  --output DATA/catalog/adc_drug_overview.csv
```
