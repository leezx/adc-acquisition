#!/usr/bin/env python3
"""Phase 2 (reports/validation/BREADTH_PLAN.md Part 3): a coarse,
observation-based split of the `NOT_CONFIRMED_BROAD` assets from Phase 1's
`nar702_broad_recall.tsv` -- starting explicitly from "N unresolved
negatives", NOT "N confirmed query misses" (per the Phase 1 review's
correction). Only patch a production query when a REPEATED pattern proves
a systematic acquisition-mechanism defect; this script's job is to find
out whether such a pattern exists, not to assume one.

Two OBSERVATION-based categories (round-1 fix: the category name itself
must describe what was actually checked, not the root-cause guess -- the
guess lives in a separate `root_cause_hypothesis` column so a later phase
can revise it without having to rename/reinterpret the category):

  NO_NAR_EXTERNAL_CITATION_SIGNAL -- NAR itself cites zero references and
                                no NCT id for this asset. Does NOT mean
                                "this asset only exists in a source we
                                don't query" -- only that NAR's own curation
                                gives us nothing to check against.
                                root_cause_hypothesis: POSSIBLE_SOURCE_GAP.
  NAR_EXTERNAL_CITATION_PRESENT -- NAR cites >=1 reference or NCT id for
                                this asset. Does NOT mean "we just haven't
                                materialized/paginated deep enough yet" --
                                only that NAR itself points to something
                                external we could in principle check.
                                root_cause_hypothesis:
                                POSSIBLE_DISCOVERY_OR_MATERIALIZATION_DEPTH.

  possible_patent_text_gap  -- a flag (not exclusive of the above) for
                                assets whose only cited trace would be a
                                patent (no NCT id, no reference DOI, but a
                                named company) -- uncertain specifically
                                because of the USPTO text-extraction gap
                                and WIPO/EPO's large unmaterialized backlog
                                disclosed in Phase 1. Kept "possible" per
                                the same round-1 correction.
  TRUE_CANDIDATE_MISS        -- reserved for cases where investigation
                                finds the query MECHANISM itself at fault
                                (not just depth/observability/registry
                                scope). Not assigned by this script -- see
                                the diagnostic below and the report for why.

Diagnostic check on the 14 most NAR-documented, later-stage unresolved
assets (round-1 fix: downgraded from an overclaimed conclusion). What this
script actually checks: whether each cited NCT id appears ANYWHERE in the
clinicaltrials discovery ledger (any query_id). What that check does NOT
prove: Job 15's per-asset/per-intervention targeted lookups only ever run
for assets already in configs/known_adc_assets.yaml -- for any of these 14
NAR assets that are NOT in that curated registry, no targeted lookup was
EVER attempted for it, so its absence from the ledger's targeted query_ids
is uninformative, not evidence of anything. And CT.gov's broad-query
pagination is genuinely `--limit`-capped (jobs/clinicaltrials/job.py stops
paginating once `len(record_first_query) >= args.limit`), which makes
discovery-depth censoring PLAUSIBLE -- but absence from the ledger alone
does not distinguish "we just haven't paginated far enough" from "the
query's phrasing/terms wouldn't match this trial even with full
pagination." Confirming pagination-depth specifically (as opposed to a
query-scope mismatch) would require fetching each flagged trial's own
intervention/title text and checking it offline against the current broad
query's semantics -- not done in this script, and not needed to satisfy
Phase 2's actual job (find whether a REPEATED, evidence-backed defect
pattern exists before patching anything -- it does not, per this round's
finding, but that is "no defect confirmed," not "pagination proven").

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
        return "NO_NAR_EXTERNAL_CITATION_SIGNAL"
    return "NAR_EXTERNAL_CITATION_PRESENT"


def root_cause_hypothesis(category: str) -> str:
    return {
        "NO_NAR_EXTERNAL_CITATION_SIGNAL": "POSSIBLE_SOURCE_GAP",
        "NAR_EXTERNAL_CITATION_PRESENT": "POSSIBLE_DISCOVERY_OR_MATERIALIZATION_DEPTH",
    }[category]


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
                f"(any query type, not just broad -- but see module docstring: this is only informative for "
                f"assets already in configs/known_adc_assets.yaml)"
            )
        rows.append(dict(
            nar_adc_id=r["nar_adc_id"], canonical_name=r["canonical_name"], phase_bucket=r["phase_bucket"],
            unresolved_category=category, root_cause_hypothesis=root_cause_hypothesis(category),
            possible_patent_text_gap=patent_gap,
            reference_count=r["reference_count"], nct_ids=r["nct_ids"], reference_dois=r["reference_dois"],
            in_known_registry=r.get("in_known_registry", ""),
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
        ["nar_adc_id", "canonical_name", "phase_bucket", "unresolved_category", "root_cause_hypothesis",
         "possible_patent_text_gap", "reference_count", "nct_ids", "reference_dois", "in_known_registry",
         "nct_discovery_ledger_check"],
    )

    cat_counts = Counter(r["unresolved_category"] for r in rows)
    n_patent_gap = sum(1 for r in rows if r["possible_patent_text_gap"])
    print(f"NO_NAR_EXTERNAL_CITATION_SIGNAL: {cat_counts['NO_NAR_EXTERNAL_CITATION_SIGNAL']}", file=sys.stderr)
    print(f"NAR_EXTERNAL_CITATION_PRESENT: {cat_counts['NAR_EXTERNAL_CITATION_PRESENT']}", file=sys.stderr)
    print(f"possible_patent_text_gap flag set on: {n_patent_gap} rows", file=sys.stderr)

    # Diagnostic: among the most "suspicious" cases -- NAR-documented,
    # later-stage, still unresolved -- how many of their cited NCT ids are
    # absent from our discovery ledger ENTIRELY (any query type)? See
    # module docstring for exactly what this does and does NOT prove.
    suspicious = unresolved[
        (unresolved["reference_count"] > 0) & (unresolved["nct_ids"] != "")
        & (unresolved["phase_bucket"].isin(["Approved", "Phase3", "Phase2"]))
    ]
    fully_absent = 0
    fully_absent_and_not_in_registry = 0
    for _, r in suspicious.iterrows():
        nct_ids = [n for n in r["nct_ids"].split("; ") if n]
        if nct_ids and not any(n in any_discovered_nct_ids for n in nct_ids):
            fully_absent += 1
            if str(r.get("in_known_registry", "")).lower() != "true":
                fully_absent_and_not_in_registry += 1
    print(
        f"\nDiagnostic sample: {len(suspicious)} well-documented, later-stage (Approved/Phase3/Phase2) "
        f"unresolved assets found. {fully_absent}/{len(suspicious)} have ALL their cited NCT ids "
        f"completely absent from our clinicaltrials discovery ledger (any query type). "
        f"Of those, {fully_absent_and_not_in_registry} are NOT in configs/known_adc_assets.yaml, "
        f"meaning Job 15's targeted lookup was never attempted for them at all -- their ledger "
        f"absence is expected and uninformative for those, not evidence of anything. "
        f"CT.gov's broad-query pagination IS genuinely --limit-capped this session, which makes "
        f"discovery-depth censoring a PLAUSIBLE explanation for the rest, but this check alone "
        f"cannot distinguish pagination-depth from a query-scope/wording mismatch -- that would "
        f"require fetching each trial's own text and checking it against current query semantics, "
        f"not done here. Verdict: no evidence found in this round to CONFIRM a query-content "
        f"defect -- that is an absence of confirmed defect, not a proof of query completeness. "
        f"See report for the full TRUE_CANDIDATE_MISS discussion.",
        file=sys.stderr,
    )

    print(f"\nDone. Output written to {output_dir}/broad_miss_taxonomy.tsv", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
