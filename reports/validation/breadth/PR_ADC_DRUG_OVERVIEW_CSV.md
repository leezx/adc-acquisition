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

Columns: `asset_id, canonical_name, aliases, development_codes, target,
payload, linker, indication, company, clinical_phase, adc_scope,
catalog_status, source_count, sources, nct_ids, date_added_to_table`.

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
its last-known historical row, not silently dropped.

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
payload/linker/indication enrichment match, 1,029 newly added this first
run (no prior CSV existed). Spot-checked real, correct data for known
approved ADCs (Trastuzumab emtansine: HER2 / DM1 (maytansinoid) / SMCC
non-cleavable linker / Genentech, Inc / Approved (FDA): Feb 22, 2013;
Sacituzumab govitecan: TROP2 / SN-38 / cleavable CL2A linker / Gilead
Sciences, Inc / Approved (FDA): Apr, 2020).

## Tests

12 new tests in `tests/tools/catalog/test_build_adc_drug_overview.py`:
enrichment join (present and absent), stable row-order preservation
across reruns, `date_added_to_table` stamped once and never re-stamped,
a pure no-op re-run, stale/merged-away rows kept not dropped,
deterministic tail-append ordering for multiple simultaneous new assets,
CSV write/reload round-trip, NaN-to-None conversion, missing-file
handling, and a full `main()` end-to-end test. Plus 2 updated tests in
`tests/tools/breadth/test_update_breadth.py` confirming the new 5th
derivation step is wired correctly (both the normal-run and
skip-after-failure paths).

Full suite: 700 passed.

## Reproduction command

```bash
python3 tools/catalog/build_adc_drug_overview.py \
  --catalog-file DATA/catalog/adc_asset_universe.tsv \
  --candidates-file DATA/feasibility/adc_candidates.tsv \
  --output DATA/catalog/adc_drug_overview.csv
```
