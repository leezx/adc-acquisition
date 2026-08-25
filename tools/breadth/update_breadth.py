#!/usr/bin/env python3
"""`update_breadth` — the twice-monthly delta/update orchestrator
(reports/validation/BREADTH_PLAN.md Phase 6, Parts 12-13). Also closes
Prompt.md section 31's original, deliberately-deferred `run-all`: "should
merely orchestrate independent jobs. It must not create coupling between
them."

Two independent stages, run in sequence, neither one coupled to the
other's internals -- each stage is invoked as its own subprocess, exactly
the CLI a human would run by hand (Usage docstrings in each invoked
module), so this orchestrator adds NO new code path any single job/script
doesn't already have and independently pass its own tests through:

1. **Acquisition stage** -- every registered `adc_acquisition` job
   (`adc_acquisition.__main__.JOBS`, the single source of truth for the
   job list -- never duplicated here) is run once, in whatever order the
   registry lists them, via `python -m adc_acquisition <job>`. A job that
   fails is logged and does NOT abort the others (Prompt.md section 31's
   "must not create coupling" applies to failure isolation too, not just
   normal operation) -- this is Gate 5's "visible/retryable failures"
   requirement.
2. **Breadth-derivation stage** -- `tools/breadth/candidate_queue.py` ->
   `feasibility_entities.py` -> `component_coverage_audit.py`, in that
   fixed dependency order (each reads the previous stage's own output
   files), re-deriving the feasibility-entity universe from whatever the
   acquisition stage just added.

**Snapshot-diff, not a second discovery mechanism.** Before stage 1
starts, every `DATA/feasibility/*.tsv` table (if it already exists) is
read into memory as the "before" snapshot. After stage 2 finishes, the
same tables are re-read as "after." A row is NEW only if its own natural
key (entity_id/candidate_id/etc.) did not exist in the "before" snapshot
-- this never inspects, diffs, or touches the underlying acquisition
manifests' own immutable version history (Prompt.md section 23), only
the ALREADY-immutable derived feasibility tables Phase 3/5c/5e already
produce. `write_tsv()`-family functions elsewhere in this repo already
guarantee those tables never silently drop or overwrite a row across
runs; this module only compares two already-correct snapshots, it never
writes to DATA/feasibility/*.tsv itself.

**Tier A/B/C prioritization** (BREADTH_PLAN.md Part 13) of every newly-
appeared row, by that row's own `status`/`validation_status` field --
never a new, separate confidence judgment:
  Tier A -- VALIDATED-tier component entities, PROMOTED/AUTO_HIGH_
            CONFIDENCE candidates, and every adc_candidates.tsv row
            (always status=VALIDATED by construction).
  Tier B -- OBSERVED-tier component entities, NEEDS_REVIEW candidates,
            new target x indication associations.
  Tier C -- everything else newly-appeared (INFERRED-tier components,
            new indication-aggregate rows).
An existing entity whose own evidence_count/supporting_asset_count grew
(same key, higher count) is reported separately as "evidence deepened,"
never miscounted as a new entity.

**Status/confidence-change detection for EXISTING keys** (round-1 fix).
Persistent candidate/entity IDs (Phase 5a) deliberately do not change when
a candidate's evidence strengthens -- so a promotion like NEEDS_REVIEW ->
AUTO_HIGH_CONFIDENCE on the SAME candidate_id is invisible to both new-row
detection and count-column "deepened" detection (candidate_queue.tsv has
no count column at all). `STATUS_FIELDS_BY_TABLE` names the decision-
relevant fields watched per table; any change on an existing key is
reported in `status_changes.tsv` and in the delta markdown, and a
transition into PROMOTED/AUTO_HIGH_CONFIDENCE/VALIDATED is surfaced as a
Tier A event, not buried under "evidence deepened."

**Derivation-chain failures fail closed** (round-1 fix). The acquisition
stage's jobs are genuinely independent siblings -- one job's failure never
blocks another. The derivation stage is NOT: candidate_queue ->
feasibility_entities -> component_coverage_audit is a fixed dependency
chain where each step reads the previous step's own output. If a step
fails, every remaining step is recorded as SKIPPED_UPSTREAM_FAILURE rather
than run against stale upstream output, and no new-entity/deepened/status-
change diff is computed for that run (`DELTA_STATUS: INCOMPLETE_DERIVATION`,
`main()` returns nonzero) -- comparing before/partial-after snapshots would
misattribute stale-vs-new state.

**Immutability discipline for delta output itself**: `reports/delta/
YYYY-MM-DD/` is never overwritten by a same-day second run -- a second
run on the same date gets `YYYY-MM-DD_run2`, `_run3`, etc., so a
"controlled delta run" demonstration (or an accidental double-invocation)
can never silently erase a prior day's delta artifact.

Usage:
    python3 tools/breadth/update_breadth.py \
        --data-dir DATA \
        --delta-output reports/delta

    # Controlled/scoped run (e.g. for a demonstration or a fast source
    # subset) -- orchestration semantics identical, just a smaller job set:
    python3 tools/breadth/update_breadth.py \
        --jobs conference_abstract_corpus,company_scientific_presentations \
        --data-dir DATA --delta-output reports/delta
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from adc_acquisition.__main__ import JOBS  # noqa: E402

DERIVATION_STEPS = [
    ("candidate_queue", REPO_ROOT / "tools" / "breadth" / "candidate_queue.py"),
    ("feasibility_entities", REPO_ROOT / "tools" / "breadth" / "feasibility_entities.py"),
    ("component_coverage_audit", REPO_ROOT / "tools" / "breadth" / "component_coverage_audit.py"),
]

# (filename, key_columns, count_column_for_evidence-deepened_detection)
FEASIBILITY_TABLES = [
    ("candidate_queue.tsv", ["candidate_id"], None),
    ("adc_candidates.tsv", ["entity_id"], "evidence_count"),
    ("adc_targets.tsv", ["entity_id"], "evidence_count"),
    ("adc_payloads.tsv", ["entity_id"], "evidence_count"),
    ("adc_linkers.tsv", ["entity_id"], "evidence_count"),
    ("adc_platforms.tsv", ["entity_id"], "evidence_count"),
    ("payload_moa_targets.tsv", ["entity_id"], "evidence_count"),
    ("target_indication_feasibility.tsv", ["target_entity_id", "indication"], "supporting_asset_count"),
    ("adc_indications.tsv", ["indication"], "n_adc_candidates"),
]

# Decision-relevant fields to watch for changes on an EXISTING natural key
# (persistent candidate/entity IDs, per Phase 5a's design, deliberately do
# NOT change when evidence/confidence changes -- so a promotion like
# NEEDS_REVIEW -> AUTO_HIGH_CONFIDENCE is invisible to new-row detection and
# invisible to count-column "deepened" detection on tables with no count
# column). Deliberately narrow to fields that represent an actual decision
# state, not every text column (free-text columns like `context`/`reason`
# change constantly and are not delta-worthy).
STATUS_FIELDS_BY_TABLE = {
    "candidate_queue.tsv": ["validation_status", "confidence", "modality_classification", "source"],
    "adc_candidates.tsv": ["status", "stage", "target", "payload_evidence_type", "linker_evidence_type", "modality_classification"],
    "adc_targets.tsv": ["status", "confidence", "evidence_sources"],
    "adc_payloads.tsv": ["status", "confidence", "evidence_sources"],
    "adc_linkers.tsv": ["status", "confidence", "evidence_sources"],
    "adc_platforms.tsv": ["status", "confidence", "evidence_sources"],
    "payload_moa_targets.tsv": ["status", "confidence", "evidence_sources"],
    "target_indication_feasibility.tsv": ["status", "confidence"],
    # adc_indications.tsv intentionally excluded: it is a raw count
    # aggregate with no decision-relevant status field of its own.
}

# A status/validation_status field landing on one of these values is a
# Tier A event even when it is not a new row -- surfaced separately from
# "evidence deepened" per the reviewer's explicit requirement.
_TIER_A_STATUS_VALUES = {"PROMOTED", "AUTO_HIGH_CONFIDENCE", "VALIDATED"}


def _is_tier_a_upgrade(field: str, before_val: str, after_val: str) -> bool:
    return (
        field in ("validation_status", "status")
        and after_val in _TIER_A_STATUS_VALUES
        and before_val not in _TIER_A_STATUS_VALUES
    )


@dataclass
class JobRunOutcome:
    name: str
    ok: bool
    returncode: int
    tail_stdout: str
    tail_stderr: str
    skipped: bool = False  # True only for SKIPPED_UPSTREAM_FAILURE derivation steps


@dataclass
class DeltaResult:
    run_started_at: str
    job_outcomes: list[JobRunOutcome] = field(default_factory=list)
    derivation_outcomes: list[JobRunOutcome] = field(default_factory=list)
    new_rows_by_table: dict = field(default_factory=dict)  # table -> list[dict(row..., tier=...)]
    deepened_by_table: dict = field(default_factory=dict)  # table -> list[key tuples]
    status_changes_by_table: dict = field(default_factory=dict)  # table -> list[dict(key, field, before, after, tier_a_upgrade)]
    delta_status: str = "OK"  # or "INCOMPLETE_DERIVATION"
    delta_dir: str = ""


def _row_key(row: dict, key_columns: list[str]) -> tuple:
    return tuple(str(row.get(c, "")) for c in key_columns)


def _tier_for_row(table_name: str, row: dict) -> str:
    if table_name == "candidate_queue.tsv":
        return "A" if row.get("validation_status") in ("PROMOTED", "AUTO_HIGH_CONFIDENCE") else "B"
    if table_name == "adc_candidates.tsv":
        return "A"  # always status=VALIDATED by construction (Phase 3)
    if table_name in ("adc_targets.tsv", "adc_payloads.tsv", "adc_linkers.tsv", "adc_platforms.tsv", "payload_moa_targets.tsv"):
        status = row.get("status")
        return "A" if status == "VALIDATED" else ("B" if status == "OBSERVED" else "C")
    if table_name == "target_indication_feasibility.tsv":
        return "B"
    return "C"  # adc_indications.tsv and anything not explicitly tiered above


def read_feasibility_snapshot(feasibility_dir: Path) -> dict[str, pd.DataFrame]:
    snapshot = {}
    for filename, _keys, _count_col in FEASIBILITY_TABLES:
        path = feasibility_dir / filename
        snapshot[filename] = pd.read_csv(path, sep="\t", dtype=str).fillna("") if path.exists() else pd.DataFrame()
    return snapshot


def diff_snapshots(before: dict[str, pd.DataFrame], after: dict[str, pd.DataFrame]) -> tuple[dict, dict, dict]:
    """Returns (new_rows_by_table, deepened_by_table, status_changes_by_table).

    A row is NEW only if its natural key was absent from `before` entirely
    -- never inferred from a changed non-key column. `deepened_by_table`
    separately flags an EXISTING key whose own count_col value increased
    (more evidence for an already-known entity). `status_changes_by_table`
    flags an EXISTING key where one of that table's STATUS_FIELDS_BY_TABLE
    decision-relevant fields changed value -- this is the ONLY mechanism
    that can see a persistent-ID candidate's confidence promotion (e.g.
    NEEDS_REVIEW -> AUTO_HIGH_CONFIDENCE), since the candidate_id itself is
    deliberately stable across such a promotion (Phase 5a) and
    candidate_queue.tsv has no count column at all. All three are mutually
    exclusive per (table, key): a brand-new key is only ever reported as
    new, never also as deepened/changed."""
    new_rows_by_table: dict[str, list[dict]] = {}
    deepened_by_table: dict[str, list[tuple]] = {}
    status_changes_by_table: dict[str, list[dict]] = {}

    for filename, key_columns, count_col in FEASIBILITY_TABLES:
        before_df, after_df = before.get(filename, pd.DataFrame()), after.get(filename, pd.DataFrame())
        if after_df.empty:
            continue

        before_records = before_df.to_dict("records") if not before_df.empty else []
        before_keys = {_row_key(r, key_columns) for r in before_records}
        new_rows = []
        for row in after_df.to_dict("records"):
            key = _row_key(row, key_columns)
            if key not in before_keys:
                new_rows.append({**row, "_tier": _tier_for_row(filename, row)})
        if new_rows:
            new_rows_by_table[filename] = new_rows

        if count_col and not before_df.empty:
            before_by_key = {_row_key(r, key_columns): r.get(count_col) for r in before_records}
            deepened = []
            for row in after_df.to_dict("records"):
                key = _row_key(row, key_columns)
                if key not in before_by_key:
                    continue
                try:
                    before_count, after_count = int(before_by_key[key] or 0), int(row.get(count_col) or 0)
                except (TypeError, ValueError):
                    continue
                if after_count > before_count:
                    deepened.append((key, before_count, after_count))
            if deepened:
                deepened_by_table[filename] = deepened

        watched_fields = STATUS_FIELDS_BY_TABLE.get(filename, [])
        if watched_fields and not before_df.empty:
            before_row_by_key = {_row_key(r, key_columns): r for r in before_records}
            changes = []
            for row in after_df.to_dict("records"):
                key = _row_key(row, key_columns)
                before_row = before_row_by_key.get(key)
                if before_row is None:
                    continue  # new row -- already reported above, not a status change
                for f in watched_fields:
                    before_val, after_val = str(before_row.get(f, "")), str(row.get(f, ""))
                    if before_val != after_val:
                        changes.append({
                            "key": key, "field": f, "before": before_val, "after": after_val,
                            "tier_a_upgrade": _is_tier_a_upgrade(f, before_val, after_val),
                        })
            if changes:
                status_changes_by_table[filename] = changes

    return new_rows_by_table, deepened_by_table, status_changes_by_table


def _run_subprocess(label: str, cmd: list[str]) -> JobRunOutcome:
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
        return JobRunOutcome(
            name=label, ok=(proc.returncode == 0), returncode=proc.returncode,
            tail_stdout=proc.stdout[-2000:], tail_stderr=proc.stderr[-2000:],
        )
    except OSError as exc:
        return JobRunOutcome(name=label, ok=False, returncode=-1, tail_stdout="", tail_stderr=str(exc))


def run_acquisition_stage(job_names: list[str], output_dir: Path) -> list[JobRunOutcome]:
    """Each job is its own subprocess -- one job's failure is recorded
    and does NOT prevent the next job (or the derivation stage) from
    running. This is the failure-isolation half of Prompt.md section 31's
    "must not create coupling between them.\""""
    outcomes = []
    for name in job_names:
        cmd = [sys.executable, "-m", "adc_acquisition", name, "--output", str(output_dir)]
        outcomes.append(_run_subprocess(name, cmd))
    return outcomes


def run_derivation_stage(data_dir: Path, feasibility_output: Path) -> list[JobRunOutcome]:
    """Fixed DEPENDENCY order, not independent siblings -- candidate_queue
    -> feasibility_entities -> component_coverage_audit, each reading the
    previous step's own output files. Unlike the acquisition stage (whose
    jobs are genuinely independent and must all be attempted regardless of
    a sibling's failure), a derivation step failure must fail the REST OF
    THE CHAIN closed: running feasibility_entities against a stale
    candidate_queue.tsv (because candidate_queue.py itself failed) would
    silently blend new acquisition manifests with an old derived queue,
    producing a coverage_audit that looks normal but rests on mixed-
    generation state. Once a step fails, every remaining step is recorded
    as SKIPPED_UPSTREAM_FAILURE rather than run."""
    outcomes = []
    upstream_failed = False
    for label, script_path in DERIVATION_STEPS:
        if upstream_failed:
            outcomes.append(JobRunOutcome(
                name=label, ok=False, returncode=-2, tail_stdout="", tail_stderr="SKIPPED_UPSTREAM_FAILURE", skipped=True,
            ))
            continue
        cmd = [sys.executable, str(script_path), "--data-dir", str(data_dir), "--output", str(feasibility_output)]
        if label == "component_coverage_audit":
            cmd = [
                sys.executable, str(script_path),
                "--feasibility-dir", str(feasibility_output),
                "--nar-dir", str(data_dir / "reference" / "nar_adcdb"),
                "--output", str(REPO_ROOT / "reports" / "validation" / "breadth" / "component_coverage_audit.tsv"),
            ]
        outcome = _run_subprocess(label, cmd)
        outcomes.append(outcome)
        if not outcome.ok:
            upstream_failed = True
    return outcomes


def make_delta_dir(output_root: Path, date_str: str) -> Path:
    """Never overwrites a prior run's delta directory -- a second run on
    the same date gets a numbered suffix instead."""
    base = output_root / date_str
    if not base.exists():
        base.mkdir(parents=True)
        return base
    i = 2
    while (output_root / f"{date_str}_run{i}").exists():
        i += 1
    path = output_root / f"{date_str}_run{i}"
    path.mkdir(parents=True)
    return path


def write_delta_summary_tsv(path: Path, new_rows_by_table: dict) -> None:
    rows = []
    for table, entries in new_rows_by_table.items():
        for entry in entries:
            key_repr = entry.get("entity_id") or entry.get("candidate_id") or entry.get("indication") or str(entry)
            rows.append(dict(table=table, tier=entry["_tier"], key=key_repr, canonical_label=entry.get("canonical_label", "")))
    df = pd.DataFrame(rows, columns=["table", "tier", "key", "canonical_label"])
    df.sort_values(["tier", "table", "key"], inplace=True) if not df.empty else None
    df.to_csv(path, sep="\t", index=False)


def write_status_changes_tsv(path: Path, status_changes_by_table: dict) -> None:
    """table/key/field/before/after -- one row per decision-relevant field
    change on an EXISTING natural key (never a new row; new rows are
    delta_summary.tsv's job)."""
    rows = []
    for table, changes in status_changes_by_table.items():
        for c in changes:
            rows.append(dict(
                table=table, key="|".join(c["key"]), field=c["field"],
                before=c["before"], after=c["after"], tier_a_upgrade=c["tier_a_upgrade"],
            ))
    df = pd.DataFrame(rows, columns=["table", "key", "field", "before", "after", "tier_a_upgrade"])
    df.sort_values(["table", "key", "field"], inplace=True) if not df.empty else None
    df.to_csv(path, sep="\t", index=False)


def build_delta_markdown(result: DeltaResult) -> str:
    def _outcome_lines(outcomes: list[JobRunOutcome]) -> str:
        if not outcomes:
            return "None run this cycle (--jobs filtered to an empty/derivation-only set)."
        lines = []
        for o in outcomes:
            if o.skipped:
                lines.append(f"- {o.name}: SKIPPED_UPSTREAM_FAILURE")
            else:
                lines.append(f"- {o.name}: {'OK' if o.ok else f'FAILED (exit {o.returncode})'}")
        return "\n".join(lines)

    failed_jobs = [o for o in result.job_outcomes if not o.ok]
    failed_derivation = [o for o in result.derivation_outcomes if not o.ok and not o.skipped]
    skipped_derivation = [o for o in result.derivation_outcomes if o.skipped]

    header = f"""# ADC Breadth Delta — {result.run_started_at}

Per `reports/validation/BREADTH_PLAN.md` Phase 6 (Parts 12-13). Generated by
`tools/breadth/update_breadth.py` -- snapshot-diff of `DATA/feasibility/*.tsv`
before/after this run's acquisition + breadth-derivation stages. Never
overwrites a prior day's delta (see this directory's own creation rule).

**DELTA_STATUS: {result.delta_status}**

## Acquisition stage ({len(result.job_outcomes)} jobs)

{_outcome_lines(result.job_outcomes)}

## Breadth-derivation stage

{_outcome_lines(result.derivation_outcomes)}
"""

    if result.delta_status == "INCOMPLETE_DERIVATION":
        return header + f"""
## Derivation did not complete -- no entity/status delta computed

`candidate_queue` -> `feasibility_entities` -> `component_coverage_audit` is
a fixed DEPENDENCY chain, not independent siblings (unlike the acquisition
stage's jobs). Because {', '.join(o.name for o in failed_derivation) or '(unknown step)'} failed,
downstream step(s) {', '.join(o.name for o in skipped_derivation) or '(none)'} were
skipped rather than run against stale upstream output. Diffing the before/
after `DATA/feasibility/*.tsv` snapshot in this state would misattribute
stale vs. newly-derived rows, so no new-entity, evidence-deepened, or
status-change report was computed this run. Fix the failing step and
re-run `update_breadth`.

## Reproduction

```bash
python3 tools/breadth/update_breadth.py --data-dir DATA --delta-output reports/delta
```
"""

    tier_counts = {"A": 0, "B": 0, "C": 0}
    tier_sections = {"A": [], "B": [], "C": []}
    for table, entries in result.new_rows_by_table.items():
        for e in entries:
            tier_counts[e["_tier"]] += 1
            label = e.get("canonical_label") or e.get("candidate_label") or e.get("entity_id") or e.get("candidate_id") or e.get("indication", "")
            tier_sections[e["_tier"]].append(f"- `{table}`: {label}")

    upgrade_lines = []
    all_status_change_lines = []
    for table, changes in result.status_changes_by_table.items():
        for c in changes:
            key_repr = "|".join(c["key"])
            line = f"- `{table}` [{key_repr}] {c['field']}: {c['before']!r} -> {c['after']!r}"
            all_status_change_lines.append(line)
            if c["tier_a_upgrade"]:
                upgrade_lines.append(line)
                tier_counts["A"] += 1

    deepened_lines = "\n".join(
        f"- `{table}`: {len(entries)} existing entities gained more evidence"
        for table, entries in result.deepened_by_table.items()
    ) or "None this run."

    return header + f"""
## New entities this run, by tier

- **Tier A** (VALIDATED-tier components, PROMOTED/AUTO_HIGH_CONFIDENCE candidates, status/confidence upgrades into these tiers): {tier_counts['A']}
- **Tier B** (OBSERVED-tier components, NEEDS_REVIEW candidates, new target-indication pairs): {tier_counts['B']}
- **Tier C** (INFERRED-tier components, new indication aggregates): {tier_counts['C']}

### Tier A

{chr(10).join(tier_sections["A"]) or "None this run."}

### Tier B

{chr(10).join(tier_sections["B"]) or "None this run."}

### Tier C

{chr(10).join(tier_sections["C"]) or "None this run."}

## Status / confidence upgrades (Tier A — existing entities, not new rows)

An existing entity (same persistent candidate_id/entity_id) whose
validation_status/status field crossed into PROMOTED/AUTO_HIGH_CONFIDENCE/
VALIDATED. Surfaced here as Tier A, not buried in "evidence deepened" below.

{chr(10).join(upgrade_lines) or "None this run."}

## All status/field changes this run (existing entities, not new rows)

Every decision-relevant field change on an existing key, including
non-upgrade changes (see `status_changes.tsv` for the full machine-readable
list). Free-text fields (e.g. `context`, `reason`) are deliberately not
watched -- see STATUS_FIELDS_BY_TABLE.

{chr(10).join(all_status_change_lines) or "None this run."}

## Evidence deepened (existing entities, not new)

{deepened_lines}

## Failures this run

{'None.' if not (failed_jobs or failed_derivation) else ''}
{chr(10).join(f'- acquisition job {o.name}: exit {o.returncode}' for o in failed_jobs)}
{chr(10).join(f'- derivation step {o.name}: exit {o.returncode}' for o in failed_derivation)}

Acquisition job failures are independently retryable and never block a
sibling job or the derivation stage (Prompt.md section 31's orchestration-
without-coupling discipline). Derivation step failures, in contrast, fail
the rest of the derivation chain closed (see above) precisely because they
are NOT independent siblings.

## Reproduction

```bash
python3 tools/breadth/update_breadth.py --data-dir DATA --delta-output reports/delta
```
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=str, default=None, help="Comma-separated subset of adc_acquisition job names (default: all registered jobs).")
    parser.add_argument("--skip-acquisition", action="store_true", help="Skip the acquisition stage entirely (derivation-only re-run).")
    parser.add_argument("--data-dir", type=str, default="DATA")
    parser.add_argument("--feasibility-dir", type=str, default="DATA/feasibility")
    parser.add_argument("--delta-output", type=str, default="reports/delta")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    feasibility_dir = Path(args.feasibility_dir)
    delta_output_root = Path(args.delta_output)

    job_names = [j.strip() for j in args.jobs.split(",")] if args.jobs else list(JOBS.keys())
    unknown = set(job_names) - set(JOBS.keys())
    if unknown:
        raise SystemExit(f"unknown job name(s): {sorted(unknown)} -- must be a subset of {sorted(JOBS.keys())}")

    now = datetime.now(timezone.utc).isoformat()
    result = DeltaResult(run_started_at=now)

    before_snapshot = read_feasibility_snapshot(feasibility_dir)

    if not args.skip_acquisition:
        result.job_outcomes = run_acquisition_stage(job_names, data_dir)
    result.derivation_outcomes = run_derivation_stage(data_dir, feasibility_dir)

    derivation_ok = all(o.ok for o in result.derivation_outcomes)
    if derivation_ok:
        after_snapshot = read_feasibility_snapshot(feasibility_dir)
        result.new_rows_by_table, result.deepened_by_table, result.status_changes_by_table = diff_snapshots(before_snapshot, after_snapshot)
        result.delta_status = "OK"
    else:
        # Fail closed: a partial derivation chain must never be diffed
        # against the pre-run snapshot as if it were a complete re-
        # derivation -- that would misattribute stale-vs-new state.
        result.delta_status = "INCOMPLETE_DERIVATION"

    date_str = datetime.now(timezone.utc).date().isoformat()
    delta_dir = make_delta_dir(delta_output_root, date_str)
    result.delta_dir = str(delta_dir)

    write_delta_summary_tsv(delta_dir / "delta_summary.tsv", result.new_rows_by_table)
    write_status_changes_tsv(delta_dir / "status_changes.tsv", result.status_changes_by_table)
    (delta_dir / "ADC_BREADTH_DELTA.md").write_text(build_delta_markdown(result), encoding="utf-8")

    total_job_failed = sum(1 for o in result.job_outcomes if not o.ok)

    if result.delta_status == "INCOMPLETE_DERIVATION":
        print(f"update_breadth: DERIVATION INCOMPLETE ({total_job_failed} acquisition failures). Delta written to {delta_dir}")
        return 1

    total_new = sum(len(v) for v in result.new_rows_by_table.values())
    total_upgrades = sum(1 for changes in result.status_changes_by_table.values() for c in changes if c["tier_a_upgrade"])
    print(f"update_breadth: {total_new} new entities, {total_upgrades} tier-A status upgrades, {total_job_failed} acquisition failures. Delta written to {delta_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
