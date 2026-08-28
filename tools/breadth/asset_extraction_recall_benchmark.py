#!/usr/bin/env python3
"""PR #32: formalizes `nar702_broad_recall.tsv` as the ASSET-EXTRACTION
RECALL BENCHMARK, per the reviewer's explicit request. This answers a
DIFFERENT question than `nar702_broad_recall.tsv` itself does:

  nar702_broad_recall.tsv (Phase 7) -- "can our ACQUISITION SYSTEM
  independently rediscover this NAR asset's existence in the corpus at
  all?" (broad_sources / BROAD_DISCOVERED)

  this script -- "given that the corpus already proves this asset is
  present (BROAD_DISCOVERED), did our own ASSET EXTRACTOR (candidate_queue.py
  + tools/catalog/build_adc_asset_universe.py) actually turn that
  evidence into a catalog entry?" (catalog_status == MULTISOURCE_CONFIRMED)

Conflating these two questions was PR #31's original mistake (see PR
#31/#32's "Round-1 fix: corrected root-cause diagnosis" -- attributing
extraction misses to "corpus doesn't have it" when the corpus already
did). This script exists so that distinction is never re-litigated ad
hoc again -- it is now a standing, reproducible, committed comparison.

Target set: NAR reference assets that are (a) Phase1+ (Approved/Phase3/
Phase2/Phase1 -- Investigative assets are excluded, matching Gate B's
existing precedent) and (b) already `BROAD_DISCOVERED` in
nar702_broad_recall.tsv (i.e., the corpus is PROVEN to contain evidence
for it -- extraction misses on this set can never be blamed on missing
acquisition).

Stop criterion (reviewer's explicit instruction): >=90% of the target
set should have catalog_status=MULTISOURCE_CONFIRMED. Below that, every
remaining miss must be individually classified into an explicit
extraction-limitation category, never lumped into a vague "source gap."

Usage:
    python3 tools/breadth/asset_extraction_recall_benchmark.py \
        --broad-recall reports/validation/breadth/nar702_broad_recall.tsv \
        --catalog DATA/catalog/adc_asset_universe.tsv \
        --output reports/validation/breadth/asset_extraction_recall_benchmark.tsv \
        --report-output reports/validation/breadth/ASSET_EXTRACTION_RECALL_BENCHMARK.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

PHASE1_PLUS_BUCKETS = {"Approved", "Phase3", "Phase2", "Phase1"}
STOP_CRITERION_PCT = 90.0

KNOWN_SUFFIXES = (
    "vedotin", "mafodotin", "emtansine", "soravtansine", "ozogamicin", "govitecan", "tesirine", "deruxtecan",
    "ravtansine", "mertansine", "talirine", "duocarmazine",
)


def _read_tsv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str).fillna("") if path.exists() else pd.DataFrame()


def classify_miss_cause(canonical_name: str) -> str:
    """Best-effort, name-shape-based categorization of WHY an extraction
    attempt did not resolve this asset -- never a claim about the exact
    mechanical cause (that requires reading the actual matched text, done
    manually for specific cases in reports/validation/breadth/
    PR31_DEV_CODE_ASSET_MENTION_SIGNAL.md and PR32's own report), only a
    coarse bucket so the aggregate miss list is triageable at a glance."""
    tokens = re.findall(r"[A-Za-z]+", canonical_name)
    last = tokens[-1].lower() if tokens else ""
    if any(last.endswith(s) for s in KNOWN_SUFFIXES):
        return "SUFFIX_COVERED_BUT_STILL_MISSED"
    if re.search(r"\d", canonical_name):
        return "DEV_CODE_SHAPED"
    words = canonical_name.split()
    if len(words) >= 2 and len(words[-1]) >= 6 and (words[-2].lower().endswith("mab") or words[-2].lower().endswith("map")):
        return "UNCOVERED_SUFFIX"
    return "OTHER_UNCLASSIFIED"


def compute_benchmark(broad_recall: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    cat = catalog.copy()
    cat["nar_adc_id"] = cat["asset_id"].str.replace("NAR_", "", regex=False)
    catalog_status_by_id = cat.set_index("nar_adc_id")["catalog_status"].to_dict()

    target = broad_recall[
        broad_recall["phase_bucket"].isin(PHASE1_PLUS_BUCKETS) & (broad_recall["status"] == "BROAD_DISCOVERED")
    ].copy()
    target["extractor_matched"] = target["nar_adc_id"].map(
        lambda i: catalog_status_by_id.get(i) == "MULTISOURCE_CONFIRMED"
    )
    target["miss_cause"] = target.apply(
        lambda r: "" if r["extractor_matched"] else classify_miss_cause(r["canonical_name"]), axis=1,
    )
    return target[["nar_adc_id", "canonical_name", "phase_bucket", "broad_sources", "match_basis",
                   "extractor_matched", "miss_cause"]]


def build_report(benchmark: pd.DataFrame) -> str:
    total = len(benchmark)
    matched = int(benchmark["extractor_matched"].sum())
    pct = (matched / total * 100) if total else 0.0
    misses = benchmark[~benchmark["extractor_matched"]]
    cause_counts = misses["miss_cause"].value_counts()

    lines = [
        "# Asset-Extraction Recall Benchmark",
        "",
        "Per PR #32 (formalizing `nar702_broad_recall.tsv` as a standing "
        "asset-extraction benchmark, per the reviewer's explicit request). "
        "Answers: of the NAR Phase1+ assets our ACQUISITION system already "
        "proved are present in the corpus (`BROAD_DISCOVERED`), how many "
        "did our own ASSET EXTRACTOR (`candidate_queue.py` + "
        "`tools/catalog/build_adc_asset_universe.py`) actually turn into a "
        "`MULTISOURCE_CONFIRMED` catalog entry? A miss here is an "
        "extraction-pattern gap, NEVER an acquisition/source gap -- the "
        "target set is restricted to assets already proven corpus-present.",
        "",
        f"Target set (Phase1+ AND BROAD_DISCOVERED): {total}",
        f"Extractor-matched (MULTISOURCE_CONFIRMED): {matched}",
        f"Extractor recall: {matched}/{total} = {pct:.1f}%",
        "",
        f"Stop criterion: >= {STOP_CRITERION_PCT:.0f}% "
        f"-- {'MET' if pct >= STOP_CRITERION_PCT else 'NOT YET MET'}.",
        "",
        "## Remaining misses, by cause",
        "",
    ]
    for cause, count in cause_counts.items():
        lines.append(f"- {cause}: {count}")
    lines += [
        "",
        "- `DEV_CODE_SHAPED`: development-code-named asset our dev-code "
        "signal did not catch in its current corpus text (may be a "
        "spelling/format variant the fragment regex doesn't cover, or the "
        "grammatical relationship to \"ADC\"/\"antibody-drug conjugate\" is "
        "looser than this signal's tight-grammar requirement).",
        "- `UNCOVERED_SUFFIX`: a generic two-word name ending in a USAN/INN "
        "stem not yet in `ADC_SUFFIX_PAYLOAD_CLASS` (a long tail of "
        "single-occurrence stems remains uncovered by design -- only "
        "stems confirmed against multiple distinct NAR assets are added).",
        "- `SUFFIX_COVERED_BUT_STILL_MISSED`: the suffix IS documented, "
        "but the specific candidate still wasn't exact-matched to this "
        "NAR row (e.g. the acquired text only contains an alias/dev-code "
        "form, not the canonical generic name itself).",
        "- `OTHER_UNCLASSIFIED`: does not fit the above shape heuristics; "
        "needs individual inspection.",
        "",
        "Every miss above is classified into one of these categories -- "
        "none are attributed to \"the corpus doesn't have this asset,\" "
        "since the target set is restricted to assets already proven "
        "`BROAD_DISCOVERED`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--broad-recall", type=str, default="reports/validation/breadth/nar702_broad_recall.tsv")
    parser.add_argument("--catalog", type=str, default="DATA/catalog/adc_asset_universe.tsv")
    parser.add_argument("--output", type=str,
                         default="reports/validation/breadth/asset_extraction_recall_benchmark.tsv")
    parser.add_argument("--report-output", type=str,
                         default="reports/validation/breadth/ASSET_EXTRACTION_RECALL_BENCHMARK.md")
    args = parser.parse_args()

    broad_recall = _read_tsv(Path(args.broad_recall))
    catalog = _read_tsv(Path(args.catalog))
    benchmark = compute_benchmark(broad_recall, catalog)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    benchmark.to_csv(args.output, sep="\t", index=False)
    Path(args.report_output).write_text(build_report(benchmark), encoding="utf-8")

    total, matched = len(benchmark), int(benchmark["extractor_matched"].sum())
    pct = (matched / total * 100) if total else 0.0
    print(f"asset_extraction_recall_benchmark: {matched}/{total} = {pct:.1f}% "
          f"(stop criterion {STOP_CRITERION_PCT:.0f}% {'MET' if pct >= STOP_CRITERION_PCT else 'NOT MET'}). "
          f"Written to {args.output}, report at {args.report_output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
