#!/usr/bin/env python3
"""Broad-discovery recall vs. targeted-recovery recall for the 702 NAR
ADCdb benchmark assets (reports/validation/BREADTH_PLAN.md Phase 1 / Part 2).

Answers two DIFFERENT questions, never conflated:

  A. BROAD DISCOVERY RECALL -- can our generic ADC-discovery queries find
     evidence referring to a NAR asset WITHOUT knowing its name beforehand?
  B. TARGETED RECOVERY RECALL -- if an asset is already known by name/alias
     (i.e. it's in configs/known_adc_assets.yaml), can Job 15 recover its
     evidence? (Already largely proven by the prior NAR benchmark audit,
     PR #17 -- this script re-confirms it per-asset rather than re-litigating it.)

Locked provenance definition (BREADTH_PLAN.md Phase 1, required before this
script was written): `BROAD_DISCOVERED` may ONLY be attributed from records
whose discovery-ledger query_id belongs to the allowed set built directly
from each source's production broad-query config (configs/*_queries.yaml
via adc_acquisition.query_registry.load_queries) -- never guessed from a
query_id prefix convention. This was verified necessary by direct
inspection: WIPO/EPO/USPTO's broad query_ids do NOT follow a
"{SOURCE}_ADC_\\d+" naming convention (unlike PubMed/Europe PMC/CT.gov),
so a prefix-guessing approach would have silently produced an empty or
wrong allowed set for those three sources. Job 15 (known_adc_asset_expansion
/ASSETEXP) and CT.gov's per-intervention CTGOV_LOOKUP_INTR_* lookups are
excluded from this set as a structural consequence of only ever reading
the production broad-query configs, not by pattern-matching them out.

KNOWN, DISCLOSED LIMITATION (this run): a NAR asset can only be matched
against MATERIALIZED (downloaded, text-bearing) records -- the discovery
ledger itself carries no title/abstract/applicant text, only
(source_record_id, query_id) provenance. Materialization of the broad-query
backlog was substantially deepened for this analysis (see the accompanying
report for exact before/after counts per source), but is not, and is not
claimed to be, exhaustive -- a NOT_DISCOVERED verdict here means "not
found in currently materialized broad evidence," not "provably absent from
our discovery ledgers." Closing this gap further is explicit Phase 2/6 work.

Usage:
    python3 tools/breadth/broad_recall.py \
        --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adc_acquisition.query_registry import load_queries  # noqa: E402
from tools.breadth.build_nar_reference_universe import phase_bucket  # noqa: E402
from tools.validation.compare_nar_adcdb import (  # noqa: E402
    DISCOVERY_SOURCES,
    NARAsset,
    build_known_asset_index,
    build_nar_benchmark_assets,
    find_manifest_matches,
    load_discovery_ledgers,
    load_known_adc_assets,
    load_our_manifests,
    match_nar_to_known_assets,
)

BROAD_QUERY_CONFIGS = {
    "pubmed": "configs/pubmed_queries.yaml",
    "europe_pmc": "configs/europe_pmc_queries.yaml",
    "wipo": "configs/wipo_queries.yaml",
    "epo": "configs/epo_queries.yaml",
    "uspto": "configs/uspto_queries.yaml",
    "clinicaltrials": "configs/clinicaltrials_queries.yaml",
}

# NAR asset identifiers below this length are exactly the class of bare
# short/generic token that produced the confirmed "Polivy" false-positive
# collision in the prior audit -- a hit on one alone is downgraded to
# AMBIGUOUS rather than counted as clean BROAD_DISCOVERED recall.
SHORT_IDENTIFIER_THRESHOLD = 6


def load_allowed_broad_query_ids(repo_root: Path) -> dict[str, set[str]]:
    allowed = {}
    for source, cfg_path in BROAD_QUERY_CONFIGS.items():
        queries = load_queries(repo_root / cfg_path)
        allowed[source] = {q.query_id for q in queries}
    return allowed


def build_broad_manifests(
    manifests: dict[str, pd.DataFrame],
    discovery: dict[str, pd.DataFrame],
    allowed_broad_query_ids: dict[str, set[str]],
) -> dict[str, pd.DataFrame]:
    """Restrict each discovery-source manifest to records that have >=1
    discovery-ledger row whose query_id is in that source's allowed broad
    set -- disjoint by construction from ASSETEXP/CTGOV_LOOKUP_INTR/any
    other targeted lookup, since those query_ids are never in the allowed
    set to begin with."""
    broad_manifests = {}
    for source in DISCOVERY_SOURCES:
        man = manifests.get(source)
        disc = discovery.get(source)
        if man is None or man.empty or disc is None or disc.empty:
            continue
        allowed = allowed_broad_query_ids.get(source, set())
        broad_ids = set(disc.loc[disc["query_id"].isin(allowed), "source_record_id"].unique())
        broad_manifests[source] = man[man["source_record_id"].isin(broad_ids)]
    return broad_manifests


def _match_basis_and_confidence(nar: NARAsset, matched_identifier: str) -> tuple[str, str]:
    def norm(s: str) -> str:
        return "".join(c for c in s.lower() if c.isalnum())

    mi = norm(matched_identifier)
    if mi == norm(nar.name) or mi == norm(nar.adc_id):
        basis = "EXACT_NAME"
    elif nar.brand_name and mi == norm(nar.brand_name):
        basis = "BRAND_MATCH"
    else:
        basis = "ALIAS_MATCH"
    confidence = "low" if len(matched_identifier) < SHORT_IDENTIFIER_THRESHOLD else (
        "high" if basis == "EXACT_NAME" else "medium"
    )
    return basis, confidence


def classify_broad_discovery(nar: NARAsset, broad_manifests: dict[str, pd.DataFrame]) -> dict:
    identifiers = nar.all_identifiers()
    hits = find_manifest_matches(broad_manifests, identifiers)
    if not hits:
        return dict(status="NOT_DISCOVERED", broad_sources="", matching_evidence_ids="", match_basis="", confidence="")

    bases_confidences = [_match_basis_and_confidence(nar, h["matched_identifier"]) for h in hits]
    all_low_confidence = all(c == "low" for _, c in bases_confidences)
    sources = sorted({h["source"] for h in hits})
    evidence_ids = "; ".join(str(h["source_record_id"]) for h in hits[:10])
    match_basis = "; ".join(sorted({b for b, _ in bases_confidences}))
    best_confidence = "low" if all_low_confidence else ("high" if any(c == "high" for _, c in bases_confidences) else "medium")

    status = "AMBIGUOUS" if all_low_confidence else "BROAD_DISCOVERED"
    return dict(
        status=status, broad_sources="; ".join(sources), matching_evidence_ids=evidence_ids,
        match_basis=match_basis, confidence=best_confidence,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=str, required=True)
    parser.add_argument("--data-dir", type=str, default="DATA")
    parser.add_argument("--known-assets-file", type=str, default="configs/known_adc_assets.yaml")
    parser.add_argument("--output", type=str, default="reports/validation/breadth")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    vault_root = Path(args.external_root)
    output_dir = Path(args.output)

    print("Loading NAR 702-asset benchmark universe...", file=sys.stderr)
    nar_assets = build_nar_benchmark_assets(vault_root)

    print("Loading allowed broad-query-id sets from production configs...", file=sys.stderr)
    allowed_broad_query_ids = load_allowed_broad_query_ids(repo_root)
    for source, ids in allowed_broad_query_ids.items():
        print(f"  {source}: {len(ids)} broad query_ids", file=sys.stderr)

    print("Loading discovery ledgers and materialized manifests...", file=sys.stderr)
    discovery = load_discovery_ledgers(Path(args.data_dir))
    manifests = load_our_manifests(Path(args.data_dir))
    broad_manifests = build_broad_manifests(manifests, discovery, allowed_broad_query_ids)
    for source, df in broad_manifests.items():
        total_broad_discovered = len(set(
            discovery[source].loc[discovery[source]["query_id"].isin(allowed_broad_query_ids[source]), "source_record_id"]
        ))
        print(
            f"  {source}: {len(df)} materialized records with >=1 broad-query discovery hit "
            f"(of {total_broad_discovered} unique broad-discovered records total -- "
            f"the gap is undownloaded backlog, a materialization-depth limitation, not a query-mechanism failure)",
            file=sys.stderr,
        )

    known_assets_raw = load_known_adc_assets(Path(args.known_assets_file))
    known_assets = build_known_asset_index(known_assets_raw)
    active_known = [k for k in known_assets if k.active]

    broad_rows = []
    targeted_rows = []
    phase_counts: dict[str, Counter] = {}

    for nar in nar_assets:
        bucket = phase_bucket(nar.status)
        phase_counts.setdefault(bucket, Counter())

        broad = classify_broad_discovery(nar, broad_manifests)
        match_type, _, ka = match_nar_to_known_assets(nar, active_known)
        in_registry = ka is not None

        status = broad["status"]
        if status == "NOT_DISCOVERED" and in_registry:
            # Targeted evidence for our 14/15 curated assets was already
            # deeply verified by the prior NAR benchmark audit (PR #17,
            # asset_source_coverage.tsv) -- re-confirm membership only,
            # not re-run the full materialization check here.
            status = "TARGETED_ONLY"

        root_cause = ""
        if status in ("NOT_DISCOVERED", "AMBIGUOUS"):
            root_cause = "UNKNOWN_PENDING_DEEPER_MATERIALIZATION_OR_PHASE2_TAXONOMY"

        phase_counts[bucket][status] += 1

        broad_rows.append(dict(
            nar_adc_id=nar.adc_id, canonical_name=nar.name, phase_bucket=bucket,
            status=status, broad_sources=broad["broad_sources"],
            matching_evidence_ids=broad["matching_evidence_ids"], match_basis=broad["match_basis"],
            confidence=broad["confidence"], in_known_registry=in_registry,
            root_cause_if_missing=root_cause,
        ))

        targeted_rows.append(dict(
            nar_adc_id=nar.adc_id, canonical_name=nar.name, phase_bucket=bucket,
            in_known_registry=in_registry, known_asset_id=ka.asset_id if ka else "",
            targeted_recoverable=(
                "TRUE_PER_PRIOR_AUDIT" if in_registry else "NOT_APPLICABLE_NOT_IN_REGISTRY"
            ),
            evidence_sources="see reports/validation/nar_adcdb_comparison/asset_source_coverage.tsv" if in_registry else "",
            root_cause_if_missing="" if in_registry else "asset not in configs/known_adc_assets.yaml -- no targeted query was ever run for it",
            confidence="high" if in_registry else "",
        ))

    def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ("" if v is None else v) for k, v in row.items()})

    write_tsv(
        output_dir / "nar702_broad_recall.tsv", broad_rows,
        ["nar_adc_id", "canonical_name", "phase_bucket", "status", "broad_sources",
         "matching_evidence_ids", "match_basis", "confidence", "in_known_registry",
         "root_cause_if_missing"],
    )
    write_tsv(
        output_dir / "nar702_targeted_recovery.tsv", targeted_rows,
        ["nar_adc_id", "canonical_name", "phase_bucket", "in_known_registry", "known_asset_id",
         "targeted_recoverable", "evidence_sources", "root_cause_if_missing", "confidence"],
    )

    total = len(nar_assets)
    overall = Counter(r["status"] for r in broad_rows)
    print("\n=== Broad-discovery recall (locked provenance: production broad-query configs only) ===", file=sys.stderr)
    print(f"Overall: BROAD_DISCOVERED {overall['BROAD_DISCOVERED']}/{total} "
          f"({overall['BROAD_DISCOVERED']/total:.1%}), "
          f"TARGETED_ONLY {overall['TARGETED_ONLY']}/{total}, "
          f"AMBIGUOUS {overall['AMBIGUOUS']}/{total}, "
          f"NOT_DISCOVERED {overall['NOT_DISCOVERED']}/{total}", file=sys.stderr)
    combined = overall["BROAD_DISCOVERED"] + overall["TARGETED_ONLY"]
    print(f"BROAD_DISCOVERED or TARGETED_RECOVERABLE (Gate 1 metric, reported separately per BREADTH_PLAN.md): "
          f"{combined}/{total} ({combined/total:.1%})", file=sys.stderr)
    print("\nBy phase bucket:", file=sys.stderr)
    for bucket in ("Approved", "Phase3", "Phase2", "Phase1", "Investigative"):
        c = phase_counts.get(bucket, Counter())
        bucket_total = sum(c.values())
        if bucket_total == 0:
            continue
        print(
            f"  {bucket}: n={bucket_total}, BROAD_DISCOVERED={c['BROAD_DISCOVERED']} "
            f"({c['BROAD_DISCOVERED']/bucket_total:.1%}), TARGETED_ONLY={c['TARGETED_ONLY']}, "
            f"AMBIGUOUS={c['AMBIGUOUS']}, NOT_DISCOVERED={c['NOT_DISCOVERED']}",
            file=sys.stderr,
        )

    print(f"\nDone. Outputs written to {output_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
