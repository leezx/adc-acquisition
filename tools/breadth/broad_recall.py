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
claimed to be, exhaustive.

Text coverage is also uneven across sources relative to what the PRODUCTION
broad query itself actually searches: WIPO/EPO's broad queries search
title+abstract, so matching also greps each broad-discovered record's raw
OPS XML directly (find_raw_text_matches below), not just the structured
title/applicants/inventors manifest columns. USPTO's broad query searches
full specification text, but Job 09's own report.md already discloses that
USPTO's Specification document is stored as a raw PDF with NO text
extraction implemented anywhere in this repo (patent_bioactivity_corpus,
Job 13, covers WIPO/EPO full text only) -- this is a PRE-EXISTING, already-
disclosed capability gap, not something newly introduced or silently
worked around here, and USPTO matching in this script remains
metadata-only (title/applicants/inventors/assignees) as a result.

Given both the materialization-depth gap and this text-coverage asymmetry,
a record NOT confirmed by broad evidence is labeled `NOT_CONFIRMED_BROAD`,
not `NOT_DISCOVERED` -- the negative side of this measurement is CENSORED
by what has been materialized and what text is observable, not a proven
absence. Only `BROAD_DISCOVERED` is a positive, confirmed fact. Closing
these gaps further (deeper materialization, USPTO text extraction, and
properly root-causing NOT_CONFIRMED_BROAD into real sub-categories) is
explicit Phase 2/6 work, not this script's job.

Usage:
    python3 tools/breadth/broad_recall.py \
        --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
        --data-dir DATA \
        --output reports/validation/breadth
"""

from __future__ import annotations

import argparse
import csv
import re
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

# Conservative, heuristic collision-risk guard INSPIRED BY the confirmed
# "Polivy" false-positive failure mode from the prior audit (a bare-token
# brand-name match against unrelated authors/inventors) -- NOT a claim that
# every match below this length is that same, verified collision class, and
# not a claim that every match at or above it is safe either (a long
# generic phrase can just as easily be ambiguous, and a short but highly
# specific dev code can be perfectly safe). It only says: a match resting
# solely on a short/generic-looking token needs a human look before being
# counted as clean recall, rather than being asserted as verified.
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


# Sources whose broad-query search scope (per each source's own query
# config/job docstring) extends beyond the manifest's structured text
# columns -- WIPO/EPO's broad queries search title+abstract via OPS CQL,
# but the materialized manifest has no "abstract" column at all (confirmed
# by direct inspection of wipo.parquet/epo.parquet's schema); the abstract
# text only exists in each record's raw OPS XML response. USPTO is
# deliberately excluded here: see module docstring for why (PDF-only
# Specification, no text extraction implemented anywhere in this repo).
RAW_TEXT_SEARCHABLE_SOURCES = {"wipo", "epo"}


def build_raw_text_cache(broad_manifests: dict[str, pd.DataFrame], sources: set[str]) -> dict[str, dict[str, str]]:
    """Read each raw OPS XML file from disk exactly ONCE (not once per NAR
    asset) -- 702 assets re-reading the same ~364 files each would be
    ~250k redundant file opens, confirmed too slow in practice."""
    cache: dict[str, dict[str, str]] = {}
    for source in sources:
        df = broad_manifests.get(source)
        texts: dict[str, str] = {}
        if df is not None and not df.empty and "raw_file_path" in df.columns:
            for _, row in df.iterrows():
                raw_path = Path(row["raw_file_path"])
                if not raw_path.exists():
                    continue
                try:
                    texts[row["source_record_id"]] = raw_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
        cache[source] = texts
    return cache


def find_raw_text_matches(raw_text_cache: dict[str, str], source: str, identifiers: list[str]) -> list[dict]:
    """Grep each cached raw OPS XML response -- covers whatever text is
    actually in that response (title AND abstract), not just the subset of
    fields the manifest happens to have parsed into columns."""
    hits = []
    patterns = [(i, re.compile(re.escape(i), re.IGNORECASE)) for i in identifiers if len(i) >= 4]
    if not patterns:
        return hits
    for record_id, text in raw_text_cache.items():
        for ident, pattern in patterns:
            if pattern.search(text):
                hits.append(dict(source=source, source_record_id=record_id, matched_identifier=ident, query_id=None))
    return hits


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


def classify_broad_discovery(
    nar: NARAsset, broad_manifests: dict[str, pd.DataFrame], raw_text_cache: dict[str, dict[str, str]],
) -> dict:
    identifiers = nar.all_identifiers()
    hits = find_manifest_matches(broad_manifests, identifiers)
    for source in RAW_TEXT_SEARCHABLE_SOURCES:
        if source in raw_text_cache:
            hits.extend(find_raw_text_matches(raw_text_cache[source], source, identifiers))
    seen = set()
    deduped_hits = []
    for h in hits:
        key = (h["source"], h["source_record_id"], h["matched_identifier"])
        if key in seen:
            continue
        seen.add(key)
        deduped_hits.append(h)
    hits = deduped_hits
    if not hits:
        return dict(status="NOT_CONFIRMED_BROAD", broad_sources="", matching_evidence_ids="", match_basis="", confidence="")

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

    print("Caching raw OPS XML text for WIPO/EPO (title+abstract search coverage)...", file=sys.stderr)
    raw_text_cache = build_raw_text_cache(broad_manifests, RAW_TEXT_SEARCHABLE_SOURCES)
    for source, texts in raw_text_cache.items():
        print(f"  {source}: {len(texts)} raw files cached in memory", file=sys.stderr)

    known_assets_raw = load_known_adc_assets(Path(args.known_assets_file))
    known_assets = build_known_asset_index(known_assets_raw)
    active_known = [k for k in known_assets if k.active]

    broad_rows = []
    targeted_rows = []
    phase_counts: dict[str, Counter] = {}

    for nar in nar_assets:
        bucket = phase_bucket(nar.status)
        phase_counts.setdefault(bucket, Counter())

        broad = classify_broad_discovery(nar, broad_manifests, raw_text_cache)
        match_type, _, ka = match_nar_to_known_assets(nar, active_known)
        in_registry = ka is not None

        status = broad["status"]
        if status == "NOT_CONFIRMED_BROAD" and in_registry:
            # Targeted evidence for our 14/15 curated assets was already
            # deeply verified by the prior NAR benchmark audit (PR #17,
            # asset_source_coverage.tsv) -- re-confirm membership only,
            # not re-run the full materialization check here.
            status = "TARGETED_ONLY"

        root_cause = ""
        if status in ("NOT_CONFIRMED_BROAD", "AMBIGUOUS"):
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
          f"NOT_CONFIRMED_BROAD {overall['NOT_CONFIRMED_BROAD']}/{total}", file=sys.stderr)
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
            f"AMBIGUOUS={c['AMBIGUOUS']}, NOT_CONFIRMED_BROAD={c['NOT_CONFIRMED_BROAD']}",
            file=sys.stderr,
        )

    print(f"\nDone. Outputs written to {output_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
