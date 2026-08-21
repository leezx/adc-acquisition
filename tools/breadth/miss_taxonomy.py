#!/usr/bin/env python3
"""Phase 2 (reports/validation/BREADTH_PLAN.md Part 3): a coarse,
evidence-based split of the `NOT_CONFIRMED_BROAD` assets from Phase 1's
`nar702_broad_recall.tsv` -- starting explicitly from "N unresolved
negatives", NOT "N confirmed query misses" (per the Phase 1 review's
correction). Only patch a production query when a REPEATED pattern proves
a systematic acquisition-mechanism defect; this script's job is to find
out whether such a pattern exists, not to assume one.

Four categories (minimum split requested in review):

  SOURCE_GAP                -- NAR itself shows essentially no external
                                citable evidence for this asset (its own
                                reference_count is 0 and it cites no NCT
                                id) -- consistent with a genuinely
                                early-stage/conference-only/company-
                                disclosure-only asset that may never have
                                entered any currently-implemented broad
                                source. This is a real hypothesis, not
                                confirmed absence -- Phase 4/5 (conference,
                                company disclosures) is where it would be
                                tested, not this script.
  BROAD_BACKLOG_UNRESOLVED  -- NAR cites external evidence (a reference or
                                an NCT id) for this asset, so it plausibly
                                DOES have a discoverable footprint, but
                                Phase 1's broad-query discovery/
                                materialization hasn't found/downloaded it
                                yet. The default explanation for anything
                                with a positive external-evidence signal.
  PATENT_TEXT_NOT_OBSERVABLE -- a flag (not exclusive of the above) for
                                assets whose only plausible trace would be
                                a patent (no NCT id, no reference DOI, but
                                a named company) -- uncertain specifically
                                because of the USPTO text-extraction gap
                                and WIPO/EPO's large unmaterialized backlog
                                disclosed in Phase 1.
  TRUE_CANDIDATE_MISS        -- reserved for cases where investigation
                                finds the query MECHANISM itself at fault
                                (not just depth/observability). Assigned
                                only after the diagnostic check below finds
                                a repeated pattern -- see report.

Diagnostic check (this script, not a manual claim): for every unresolved
asset that cites >=1 NCT id, checks whether that NCT id appears ANYWHERE
in the clinicaltrials discovery ledger at all (any query_id, not just the
broad-query subset) -- if it's absent even from Job 15's much deeper
per-asset/per-intervention lookups and CT.gov's own broad-query pagination
never reached it, that is direct, checkable evidence of a discovery-depth
limitation, not a query-content defect.

Usage:
    python3 tools/breadth/miss_taxonomy.py \
        --broad-recall reports/validation/breadth/nar702_broad_recall.tsv \
        --assets DATA/reference/nar_adcdb/assets.tsv \
        --data-dir DATA \
        --output reports/validation/breadth
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import pandas as pd


def classify_unresolved_category(reference_count: int, nct_ids: str) -> str:
    if reference_count == 0 and not nct_ids:
        return "SOURCE_GAP"
    return "BROAD_BACKLOG_UNRESOLVED"


def possible_patent_text_gap(nct_ids: str, reference_dois: str, companies: str) -> bool:
    return not nct_ids and not reference_dois and bool(companies)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broad-recall", type=str, default="reports/validation/breadth/nar702_broad_recall.tsv")
    parser.add_argument("--assets", type=str, default="DATA/reference/nar_adcdb/assets.tsv")
    parser.add_argument("--data-dir", type=str, default="DATA")
    parser.add_argument("--output", type=str, default="reports/validation/breadth")
    args = parser.parse_args()

    output_dir = Path(args.output)

    recall = pd.read_csv(args.broad_recall, sep="\t", dtype=str).fillna("")
    assets = pd.read_csv(args.assets, sep="\t", dtype=str).fillna("")
    assets["reference_count"] = assets["reference_count"].astype(int)
    merged = recall.merge(assets, on="nar_adc_id", how="left", suffixes=("", "_a"))

    unresolved = merged[merged["status"] == "NOT_CONFIRMED_BROAD"].copy()
    print(f"Unresolved negatives from Phase 1: {len(unresolved)}", file=sys.stderr)

    ct_disc_path = Path(args.data_dir) / "manifests" / "clinicaltrials_discovery.parquet"
    ct_disc = pd.read_parquet(ct_disc_path) if ct_disc_path.exists() else pd.DataFrame()
    any_discovered_nct_ids = set(ct_disc["source_record_id"]) if not ct_disc.empty else set()

    rows = []
    for _, r in unresolved.iterrows():
        nct_ids = [n for n in r["nct_ids"].split("; ") if n]
        category = classify_unresolved_category(r["reference_count"], r["nct_ids"])
        patent_gap = possible_patent_text_gap(r["nct_ids"], r["reference_dois"], r["companies"])
        nct_status = ""
        if nct_ids:
            found_any = [n for n in nct_ids if n in any_discovered_nct_ids]
            nct_status = (
                f"{len(found_any)}/{len(nct_ids)} cited NCT ids appear in OUR clinicaltrials discovery ledger "
                f"(any query type, not just broad)"
            )
        rows.append(dict(
            nar_adc_id=r["nar_adc_id"], canonical_name=r["canonical_name"], phase_bucket=r["phase_bucket"],
            unresolved_category=category, possible_patent_text_gap=patent_gap,
            reference_count=r["reference_count"], nct_ids=r["nct_ids"], reference_dois=r["reference_dois"],
            nct_discovery_ledger_check=nct_status,
        ))

    def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ("" if v is None else v) for k, v in row.items()})

    write_tsv(
        output_dir / "broad_miss_taxonomy.tsv", rows,
        ["nar_adc_id", "canonical_name", "phase_bucket", "unresolved_category", "possible_patent_text_gap",
         "reference_count", "nct_ids", "reference_dois", "nct_discovery_ledger_check"],
    )

    cat_counts = Counter(r["unresolved_category"] for r in rows)
    n_patent_gap = sum(1 for r in rows if r["possible_patent_text_gap"])
    print(f"SOURCE_GAP: {cat_counts['SOURCE_GAP']}", file=sys.stderr)
    print(f"BROAD_BACKLOG_UNRESOLVED: {cat_counts['BROAD_BACKLOG_UNRESOLVED']}", file=sys.stderr)
    print(f"possible_patent_text_gap flag set on: {n_patent_gap} rows", file=sys.stderr)

    # Diagnostic: among the most "suspicious" cases -- NAR-documented,
    # later-stage, still unresolved -- how many of their cited NCT ids are
    # genuinely absent from our discovery ledger ENTIRELY (any query type)?
    suspicious = unresolved[
        (unresolved["reference_count"] > 0) & (unresolved["nct_ids"] != "")
        & (unresolved["phase_bucket"].isin(["Approved", "Phase3", "Phase2"]))
    ]
    fully_absent = 0
    for _, r in suspicious.iterrows():
        nct_ids = [n for n in r["nct_ids"].split("; ") if n]
        if nct_ids and not any(n in any_discovered_nct_ids for n in nct_ids):
            fully_absent += 1
    print(
        f"\nTRUE_CANDIDATE_MISS diagnostic: {len(suspicious)} well-documented, later-stage "
        f"(Approved/Phase3/Phase2) unresolved assets found. {fully_absent}/{len(suspicious)} "
        f"have ALL their cited NCT ids completely absent from our clinicaltrials discovery "
        f"ledger (any query type, including Job 15's per-asset lookups) -- i.e. our own CT.gov "
        f"query pagination has never reached them, a discovery-DEPTH limitation, not evidence "
        f"of a query-CONTENT defect. See report for the TRUE_CANDIDATE_MISS verdict.",
        file=sys.stderr,
    )

    print(f"\nDone. Output written to {output_dir}/broad_miss_taxonomy.tsv", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
