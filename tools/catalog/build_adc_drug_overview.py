#!/usr/bin/env python3
"""Comprehensive, human-readable ADC drug overview table (user request,
2026-09-01): one row per MASTER-CATALOG ASSET, wide format, covering
target/payload/linker/indication/company/clinical-phase/evidence-strength.

WORDING CORRECTION (reviewer-flagged, round-1): this is NOT "1,029
confirmed classical ADC drugs" -- `adc_asset_universe.tsv` is a
high-recall superset (its own `adc_scope` column includes
`REFERENCE_UNCLASSIFIED` and `ADJACENT_CONJUGATE_MODALITY` rows, never
assumed to be a classical ADC without independent evidence) and its
`catalog_status` column separately tracks evidence strength
(`REFERENCE_CONFIRMED`/`MULTISOURCE_CONFIRMED`/`SINGLE_STRONG_SOURCE`/
`NEEDS_REVIEW`). Both columns are carried through unchanged here so this
overview never hides that uncertainty.

Base identity + target/company/clinical-phase/evidence-strength come from
`DATA/catalog/adc_asset_universe.tsv` (the full ~1,000-row master catalog,
PR #30) -- that table has NO payload/linker/indication columns at all.
Those three are enriched from `DATA/feasibility/adc_candidates.tsv` (the
much smaller, ~40-row VALIDATED-tier feasibility-entity table, Phase 3)
wherever this asset's own `evidence_ids` include that table's `entity_id`.
For the large majority of rows (no `adc_candidates.tsv` match), payload/
linker/indication are left BLANK -- honestly disclosing "not
independently known to this system" rather than guessed or defaulted.

Columns: `asset_id, row_status, canonical_name, aliases,
development_codes, target, payload, linker, indication, company,
clinical_phase, development_status, adc_scope, catalog_status,
source_count, sources, nct_ids, date_added_to_table`. `clinical_phase`
is the STANDARDIZED stage code (the base catalog's own `highest_stage` --
Phase1/Phase2/Phase3/Approved/Investigative); `development_status` is
the messier free-text field (approval dates, termination status, e.g.
"Phase 1 (Terminated)") kept as its own separate column so no information
is lost (reviewer-flagged, round-1 fix: `clinical_phase` previously read
`development_status` directly, which is NOT a clean clinical-phase value
for every row -- e.g. one real row's `development_status` reads
"Investigative Drug-to-Antibody Ratio 8 3D").

STABLE, APPEND-ONLY ROW ORDER (explicit user request): re-running this
script against a growing `adc_asset_universe.tsv` must never reorder or
renumber an existing row. Every previously-written row (keyed by its own
stable `asset_id`, per `candidate_id_for_name()`'s stability discipline)
keeps its exact prior position; only genuinely NEW asset_ids are appended
at the tail (sorted by asset_id among themselves, for determinism). Each
newly-appended row is stamped with `date_added_to_table` -- the date it
was FIRST added to THIS CSV, an operational bookkeeping date, never
touched again on subsequent re-runs. This is deliberately NOT the same
thing as `first_seen` (a scientific/evidence-based date from the
underlying source, when known, and often blank).

A previously-written asset_id that no longer appears in
`adc_asset_universe.tsv` (rare -- only happens via a genuine identity
merge; see `build_adc_asset_universe.py`'s own `IDENTITY_MERGE` handling
and `reports/delta/*/identity_merges.tsv`) is KEPT as its last-known
historical row, not silently dropped -- this tool makes no attempt to
re-resolve the merge target itself, that is out of scope for an overview
table. REVIEWER-FLAGGED, ROUND-1 FIX: keeping it unmarked would let a
merged-away/stale row silently masquerade as a current active asset,
breaking this table's "one row per CURRENT master-catalog entity"
semantics. Every row now carries `row_status`: `ACTIVE` (asset_id exists
in the base catalog right now) or `STALE_HISTORICAL` (asset_id only
exists in a prior overview run) -- filter to `row_status == "ACTIVE"` for
a true current snapshot. Deliberately NOT labeled `MERGED`: this script
cannot itself prove every disappearance was a genuine identity merge (vs.
e.g. a manual catalog edit), so `STALE_HISTORICAL` is the honest,
unassuming label.

Usage:
    python3 tools/catalog/build_adc_drug_overview.py \
        --catalog-file DATA/catalog/adc_asset_universe.tsv \
        --candidates-file DATA/feasibility/adc_candidates.tsv \
        --output DATA/catalog/adc_drug_overview.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import pandas as pd

OVERVIEW_FIELDS = [
    "asset_id", "row_status", "canonical_name", "aliases", "development_codes",
    "target", "payload", "linker", "indication", "company",
    "clinical_phase", "development_status", "adc_scope", "catalog_status", "source_count",
    "sources", "nct_ids", "date_added_to_table",
]

# ACTIVE: asset_id currently exists in adc_asset_universe.tsv -- this row
# is a current master-catalog entity. STALE_HISTORICAL: asset_id no longer
# appears there (reviewer-flagged, round-1 fix -- only happens via a
# genuine identity merge; see build_adc_asset_universe.py's own
# IDENTITY_MERGE handling) -- kept for the append-only history guarantee,
# but explicitly marked so a reader never mistakes it for a current entry.
# Deliberately NOT called "MERGED": this script cannot itself prove every
# disappearance was a real identity merge (vs. e.g. a manual catalog
# edit), so STALE_HISTORICAL is the honest, unassuming label.
ROW_STATUS_ACTIVE = "ACTIVE"
ROW_STATUS_STALE_HISTORICAL = "STALE_HISTORICAL"


def load_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    df = pd.read_csv(path, sep="\t", dtype=str)
    return [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in df.to_dict("records")]


def load_existing_overview(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _candidate_index(candidate_rows: list[dict]) -> dict[str, dict]:
    return {row["entity_id"]: row for row in candidate_rows if row.get("entity_id")}


def _find_candidate_match(evidence_ids: str | None, candidate_index: dict[str, dict]) -> dict | None:
    """`evidence_ids` on a catalog row is a "; "-joined list of every
    identifier that fed this asset (a NAR id, a candidate_queue.py id,
    etc, per build_adc_asset_universe.py) -- if any token is also an
    adc_candidates.tsv `entity_id`, that row's payload/linker/indication
    apply to this asset. Exact-token match only, same discipline as
    build_adc_asset_universe.py's own identity resolution -- never a
    substring/fuzzy guess."""
    if not evidence_ids:
        return None
    for token in (t.strip() for t in evidence_ids.split(";")):
        if token in candidate_index:
            return candidate_index[token]
    return None


def build_overview_rows(
    catalog_rows: list[dict], candidate_rows: list[dict], existing_rows: list[dict], today: str,
) -> list[dict]:
    candidate_index = _candidate_index(candidate_rows)
    catalog_by_id = {row["asset_id"]: row for row in catalog_rows}
    prior_added_date = {row["asset_id"]: row.get("date_added_to_table") for row in existing_rows if row.get("asset_id")}
    prior_order = [row["asset_id"] for row in existing_rows if row.get("asset_id")]
    stale_row_by_id = {row["asset_id"]: row for row in existing_rows if row.get("asset_id")}

    def _build_row(asset_id: str, catalog_row: dict) -> dict:
        enrich = _find_candidate_match(catalog_row.get("evidence_ids"), candidate_index) or {}
        return dict(
            asset_id=asset_id,
            row_status=ROW_STATUS_ACTIVE,
            canonical_name=catalog_row.get("canonical_name"),
            aliases=catalog_row.get("aliases"),
            development_codes=catalog_row.get("development_codes"),
            target=catalog_row.get("target"),
            payload=enrich.get("payload_if_known"),
            linker=enrich.get("linker_if_known"),
            indication=enrich.get("indications"),
            company=catalog_row.get("company"),
            # `highest_stage` is the STANDARDIZED clinical-stage code
            # (Phase1/Phase2/Phase3/Approved/Investigative) -- reviewer-
            # flagged, round-1 fix: `development_status` is a much
            # messier free-text field (e.g. "Investigative Drug-to-
            # Antibody Ratio 8 3D", "Phase 1 (Terminated)", approval
            # dates) that is NOT itself a clean clinical-phase value, kept
            # here as its own separate column instead so no information
            # is lost.
            clinical_phase=catalog_row.get("highest_stage"),
            development_status=catalog_row.get("development_status"),
            adc_scope=catalog_row.get("adc_scope"),
            catalog_status=catalog_row.get("catalog_status"),
            source_count=catalog_row.get("source_count"),
            sources=catalog_row.get("sources"),
            nct_ids=catalog_row.get("nct_ids"),
            date_added_to_table=prior_added_date.get(asset_id) or today,
        )

    rows = []
    seen: set[str] = set()
    # Existing rows first, in their EXACT prior order -- never reshuffled.
    for asset_id in prior_order:
        if asset_id in catalog_by_id:
            rows.append(_build_row(asset_id, catalog_by_id[asset_id]))
        else:
            # No longer in the base catalog -- kept for append-only history,
            # but explicitly relabeled so it's never mistaken for a current
            # active entity (reviewer-flagged, round-1 fix).
            stale_row = dict(stale_row_by_id[asset_id])
            stale_row["row_status"] = ROW_STATUS_STALE_HISTORICAL
            rows.append(stale_row)
        seen.add(asset_id)

    # Genuinely new asset_ids -- appended at the tail, sorted for determinism.
    for asset_id in sorted(aid for aid in catalog_by_id if aid not in seen):
        rows.append(_build_row(asset_id, catalog_by_id[asset_id]))

    return rows


def write_overview_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OVERVIEW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in OVERVIEW_FIELDS})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog-file", type=str, default="DATA/catalog/adc_asset_universe.tsv")
    parser.add_argument("--candidates-file", type=str, default="DATA/feasibility/adc_candidates.tsv")
    parser.add_argument("--output", type=str, default="DATA/catalog/adc_drug_overview.csv")
    args = parser.parse_args()

    output_path = Path(args.output)
    existing_rows = load_existing_overview(output_path)
    catalog_rows = load_tsv(Path(args.catalog_file))
    candidate_rows = load_tsv(Path(args.candidates_file))

    rows = build_overview_rows(catalog_rows, candidate_rows, existing_rows, date.today().isoformat())
    write_overview_csv(output_path, rows)

    existing_ids = {r.get("asset_id") for r in existing_rows}
    n_new = sum(1 for r in rows if r.get("asset_id") not in existing_ids)
    n_with_payload = sum(1 for r in rows if r.get("payload"))
    print(
        f"adc_drug_overview.csv: {len(rows)} total rows ({n_new} newly added this run, "
        f"{n_with_payload} with a known payload/linker/indication enrichment match) written to {output_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
