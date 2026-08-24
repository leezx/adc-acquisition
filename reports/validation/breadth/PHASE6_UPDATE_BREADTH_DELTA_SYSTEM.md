# Phase 6 — `update_breadth` Delta/Update System

Per `reports/validation/BREADTH_PLAN.md` Phase 6 (Parts 12–13), started
per the reviewer's explicit instruction after PR #28's APPROVE
(`ACQUISITION_V1_FREEZE_STATUS: NOT_YET_READY_TO_FREEZE`,
`PROCEED_TO_PHASE6: YES`). Also closes Prompt.md section 31's originally
deferred `run-all` orchestrator ("should merely orchestrate independent
jobs. It must not create coupling between them.").

## 1. Design

`tools/breadth/update_breadth.py` runs two independent stages, each
invoked as its own subprocess (the exact CLI a human would run by hand
per that script's own Usage docstring) — this orchestrator adds no new
code path either stage doesn't already have and independently pass its
own tests through:

1. **Acquisition stage** — every job in `adc_acquisition.__main__.JOBS`
   (the single source of truth for the job list, never duplicated here;
   17 jobs today) run via `python -m adc_acquisition <job>`. A job's own
   failure is recorded and does **not** prevent the next job, or the
   derivation stage, from running.
2. **Breadth-derivation stage** — `candidate_queue.py` ->
   `feasibility_entities.py` -> `component_coverage_audit.py`, fixed
   dependency order, each reading the previous step's own output files.

**Snapshot-diff, not a new discovery mechanism.** `DATA/feasibility/*.tsv`
is read before stage 1 and again after stage 2; a row is NEW only if its
own natural key (`entity_id`/`candidate_id`/etc.) did not exist in the
"before" snapshot. This never touches the underlying acquisition
manifests' own immutable version history — it only compares two already-
correct snapshots of tables Phase 3/5c/5e already produce correctly.

**Tier A/B/C** (Part 13), derived from each new row's own
`status`/`validation_status` field, never a new confidence judgment:
- **A** — `VALIDATED`-tier component entities, `PROMOTED`/
  `AUTO_HIGH_CONFIDENCE` candidates, every `adc_candidates.tsv` row
  (always `VALIDATED` by construction).
- **B** — `OBSERVED`-tier components, `NEEDS_REVIEW` candidates, new
  target×indication pairs.
- **C** — `INFERRED`-tier components, new indication aggregates.

An existing entity whose own `evidence_count`/`supporting_asset_count`
grew (same key, higher count) is reported separately as **"evidence
deepened,"** never miscounted as a new-entity event.

**Immutability for delta output itself**: `reports/delta/YYYY-MM-DD/` is
never overwritten by a same-day second run — a second run on the same
date gets `_run2`, `_run3`, etc.

## 2. Real, live-verified two-controlled-run demonstration (Gate 5)

Scoped to `conference_abstract_corpus` + `company_scientific_presentations`
(2 of the 17 registered jobs) rather than the full registry — a
deliberate, disclosed choice for this demonstration's speed/cost, not a
limitation of the mechanism itself, which iterates the job list generically
regardless of length (`update_breadth.py` with no `--jobs` flag runs all
17 by default, exactly as designed).

```
$ python3 tools/breadth/update_breadth.py \
    --jobs conference_abstract_corpus,company_scientific_presentations \
    --data-dir DATA --delta-output reports/delta
update_breadth: 0 new entities, 0 stage failures. Delta written to reports/delta/2026-08-24

$ python3 tools/breadth/update_breadth.py \
    --jobs conference_abstract_corpus,company_scientific_presentations \
    --data-dir DATA --delta-output reports/delta
update_breadth: 0 new entities, 0 stage failures. Delta written to reports/delta/2026-08-24_run2
```

**Gate 5's four required properties, checked against this real run pair:**

- **Stability**: both runs report identical outcomes (2/2 jobs OK, 3/3
  derivation steps OK, 0 new entities) — `git status` after both runs
  shows `DATA/feasibility/*.tsv` byte-identical to what was already
  committed (deterministic re-derivation from unchanged evidence).
- **Correct append-only behavior**: `DATA/manifests/
  conference_abstract_corpus_attempts.parquet`/`_discovery.parquet` DID
  grow (new `run_id` rows logging `skipped_unchanged` for both runs) —
  confirmed by inspection to be pure growth, not overwritten history (4
  distinct `run_id` values present after 2 new runs on top of the 2
  already on disk from Phase 4/5e). `company_scientific_presentations`'
  own ledgers did not grow at all, because its early-stop pagination
  discipline (Phase 5d) correctly found zero new items and never even
  re-entered scope for already-resolved ones — also correct, disclosed
  behavior, not a bug.
- **No duplication**: 0 new entities on both runs (nothing to duplicate);
  `reports/delta/2026-08-24/` and `reports/delta/2026-08-24_run2/` are
  two distinct directories, neither overwriting the other.
- **Visible/retryable failures**: no job organically failed during this
  real demonstration (all evidence was already current), so this property
  is verified by a dedicated unit test instead of an organic failure —
  `test_run_acquisition_stage_isolates_one_jobs_failure_from_others`
  mocks one job's subprocess call to fail and confirms the other two
  jobs in the same run are still attempted and their outcomes correctly
  recorded independently.

## 3. What this does and does not establish

- Satisfies Prompt.md section 31's `run-all` (orchestrates all registered
  jobs, no coupling between them) as a side effect of building Phase 6's
  own orchestrator — one mechanism serves both.
- Does **not** include a cron/scheduler for the "twice-monthly" cadence
  itself — that is an operational/deployment concern (when to invoke this
  script), not a code deliverable this repo owns.
- Does **not** re-run all 17 jobs in this phase's own demonstration, for
  real time/cost reasons (many hit rate-limited external APIs) — disclosed
  above, not silently narrowed. A full run is exactly the same code path
  with a longer job list.
- Does **not** change Gate 1/2/3's open status from
  `reports/validation/breadth_closure.md` — this phase proves the delta
  MECHANISM works correctly (Gate 5), it does not itself close any
  recall/coverage gap. Re-evaluating `ACQUISITION_V1_FREEZE_STATUS`
  against all six gates together, after Phase 6 has run for real over
  time, remains explicit future work per that report's own Section 8.

## Reproduction

```bash
python3 tools/breadth/update_breadth.py --data-dir DATA --delta-output reports/delta
```
