#!/usr/bin/env python3
"""Phase 3 (reports/validation/BREADTH_PLAN.md Part 4): turns the
VALIDATED (PROMOTED / AUTO_HIGH_CONFIDENCE) rows of `candidate_queue.tsv`
(built by tools/breadth/candidate_queue.py) into the first counted,
provenance-preserving feasibility entities. `NEEDS_REVIEW`/`REJECTED`/
`UNREVIEWED` candidates are deliberately NOT promoted here -- that is the
whole point of the two-stage design in Part 9.

Populates, from evidence already in this repo (no new acquisition):

  DATA/feasibility/adc_candidates.tsv    (entity_type = ADC_CANDIDATE)
  DATA/feasibility/adc_targets.tsv       (entity_type = ADC_TARGET -- delivery
                                           antigen, ontology-locked per
                                           BREADTH_PLAN.md Phase 1; ONLY from
                                           configs/known_adc_assets.yaml's
                                           own `target` field in this phase --
                                           new candidates have no known
                                           target yet, honestly left absent)
  DATA/feasibility/adc_payloads.tsv      (ADC_PAYLOAD, status = INFERRED --
                                           from the USAN/INN suffix map, a
                                           naming-convention inference, NOT
                                           a validated chemistry fact --
                                           known registry AND new candidates)
  DATA/feasibility/adc_linkers.tsv       (ADC_LINKER, status = INFERRED, same
                                           basis and same caveat as payloads)
  DATA/feasibility/adc_indications.tsv  (from clinicaltrials `conditions`,
                                           aggregated per candidate)

`adc_antibodies.tsv` is NOT written in this phase (round-1 fix): the full
intervention string (e.g. "Trastuzumab deruxtecan") is the complete ADC
asset, not its antibody moiety (e.g. "Trastuzumab") -- neither the known
registry nor clinicaltrials.parquet carries a reliable structured
antibody-moiety field, and guessing one by stripping the payload suffix
word is not safe in general (naming structure varies and isn't guaranteed
splittable that way). Antibody-entity extraction is deferred until a
source explicitly supports antibody identity.

`adc_platforms.tsv` and `target_indication_feasibility.tsv` are explicitly
Phase 5 work (BREADTH_PLAN.md Parts 5/10) and are NOT written here -- this
script does not create empty placeholder files for them, to avoid implying
they've been started.

Usage:
    python3 tools/breadth/feasibility_entities.py \
        --candidate-queue DATA/feasibility/candidate_queue.tsv \
        --known-assets-file configs/known_adc_assets.yaml \
        --data-dir DATA \
        --output DATA/feasibility
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.breadth.candidate_queue import (  # noqa: E402
    ADC_SUFFIX_LINKER_CLASS,
    ADC_SUFFIX_PAYLOAD_CLASS,
    find_suffix_matches,
    known_identifier_set,
    mentions_known_asset,
    normalize_name,
)

PROMOTABLE_STATUSES = {"PROMOTED", "AUTO_HIGH_CONFIDENCE"}
NAMING_INFERENCE = "USAN_INN_NAMING_INFERENCE"

CANDIDATE_FIELDS = [
    "entity_id", "entity_type", "canonical_label", "aliases", "first_seen", "last_seen",
    "evidence_count", "evidence_sources", "confidence", "status",
    "asset_name", "development_codes", "target", "company", "stage", "indications",
    "payload_if_known", "payload_evidence_type", "linker_if_known", "linker_evidence_type",
]
COMPONENT_FIELDS = [
    "entity_id", "entity_type", "canonical_label", "aliases", "first_seen", "last_seen",
    "evidence_count", "evidence_sources", "confidence", "status", "associated_adc_candidates",
]


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def load_known_registry(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {a["asset_id"]: a for a in data.get("assets", [])}


def indications_for_nct_ids(ct_manifest: pd.DataFrame, nct_ids: list[str]) -> tuple[list[str], str]:
    if not nct_ids or ct_manifest is None:
        return [], ""
    rows = ct_manifest[ct_manifest["nct_id"].isin(nct_ids)]
    conditions: set[str] = set()
    max_phase = ""
    phase_rank = {"PHASE1": 1, "PHASE2": 2, "PHASE3": 3, "PHASE4": 4}
    for _, row in rows.iterrows():
        conds = row.get("conditions")
        if conds is not None:
            conditions.update(str(c) for c in conds)
        phases = row.get("phases")
        if phases is not None:
            for p in phases:
                if phase_rank.get(p, 0) > phase_rank.get(max_phase, 0):
                    max_phase = p
    return sorted(conditions), max_phase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-queue", type=str, default="DATA/feasibility/candidate_queue.tsv")
    parser.add_argument("--known-assets-file", type=str, default="configs/known_adc_assets.yaml")
    parser.add_argument("--data-dir", type=str, default="DATA")
    parser.add_argument("--output", type=str, default="DATA/feasibility")
    args = parser.parse_args()

    output_dir = Path(args.output)
    queue = pd.read_csv(args.candidate_queue, sep="\t", dtype=str).fillna("")
    promoted = queue[queue["validation_status"].isin(PROMOTABLE_STATUSES)]
    print(f"{len(promoted)}/{len(queue)} candidate_queue.tsv rows are validated "
          f"(PROMOTED/AUTO_HIGH_CONFIDENCE); building feasibility entities from those only",
          file=sys.stderr)

    known_registry = load_known_registry(Path(args.known_assets_file))
    ct_path = Path(args.data_dir) / "manifests" / "clinicaltrials.parquet"
    ct_manifest = pd.read_parquet(ct_path) if ct_path.exists() else None

    candidate_rows = []
    payload_usage: dict[str, list[str]] = defaultdict(list)
    linker_usage: dict[str, list[str]] = defaultdict(list)

    for _, c in promoted.iterrows():
        nct_ids = [n for n in c["evidence_id"].split("; ") if n.startswith("NCT")]
        suffix = find_suffix_matches(c["candidate_label"])
        payload_if_known = ADC_SUFFIX_PAYLOAD_CLASS.get(suffix, "") if suffix else ""
        linker_if_known = ADC_SUFFIX_LINKER_CLASS.get(suffix, "") if suffix else ""
        # Round-1 fix: a suffix-derived payload/linker is a naming-convention
        # INFERENCE, not a directly-extracted structured fact -- tagged
        # explicitly so adc_candidates.tsv never implies more certainty
        # than it has, independent of the ADC_CANDIDATE row's own identity
        # confidence (which can legitimately be "high").
        payload_evidence_type = NAMING_INFERENCE if payload_if_known else ""
        linker_evidence_type = NAMING_INFERENCE if linker_if_known else ""

        if c["source"] == "configs/known_adc_assets.yaml":
            asset = known_registry[c["evidence_id"]]
            # Known assets don't carry their own trial list directly in
            # the registry -- indications are looked up by matching the
            # asset's own identifiers against clinicaltrials intervention
            # names. Round-1 fix: reuses the SAME containment matcher
            # (mentions_known_asset) as candidate_queue.py's own dedup
            # step, restricted to just this one asset's identifiers --
            # an exact normalized-string match previously missed trials
            # whose intervention_names recorded a combination-regimen or
            # trial-arm label instead of a clean single-drug name,
            # undercounting evidence_count/indications for known assets.
            this_asset_ids = known_identifier_set([asset])
            matched_ncts = []
            if ct_manifest is not None:
                for _, row in ct_manifest.iterrows():
                    names = row.get("intervention_names")
                    if names is None:
                        continue
                    if any(mentions_known_asset(n, this_asset_ids) for n in names):
                        matched_ncts.append(row["nct_id"])
            indications, stage = indications_for_nct_ids(ct_manifest, matched_ncts)
            candidate_rows.append(dict(
                entity_id=f"ADC_CANDIDATE_{asset['asset_id'].upper()}",
                entity_type="ADC_CANDIDATE", canonical_label=asset["canonical_name"],
                aliases="; ".join(asset.get("aliases") or []),
                first_seen="", last_seen="",
                evidence_count=len(matched_ncts), evidence_sources="configs/known_adc_assets.yaml; clinicaltrials",
                confidence="high", status="VALIDATED",
                asset_name=asset["canonical_name"], development_codes="; ".join(asset.get("dev_codes") or []),
                target=asset.get("target", ""), company=asset.get("company", ""),
                stage="Approved",  # established in the prior NAR benchmark audit (PR #17): all 14 match NAR's Approved subset
                indications="; ".join(indications),
                payload_if_known=payload_if_known, payload_evidence_type=payload_evidence_type,
                linker_if_known=linker_if_known, linker_evidence_type=linker_evidence_type,
            ))
        else:
            indications, stage = indications_for_nct_ids(ct_manifest, nct_ids)
            candidate_rows.append(dict(
                entity_id=f"ADC_CANDIDATE_{c['candidate_id']}",
                entity_type="ADC_CANDIDATE", canonical_label=c["candidate_label"], aliases="",
                first_seen=c["first_seen"], last_seen="",
                evidence_count=len(nct_ids), evidence_sources=c["source"],
                confidence=c["confidence"], status="VALIDATED",
                asset_name=c["candidate_label"], development_codes="",
                target="", company="",  # honestly unknown -- Part 4 explicitly tolerates partial entities
                stage=stage or "unknown", indications="; ".join(indications),
                payload_if_known=payload_if_known, payload_evidence_type=payload_evidence_type,
                linker_if_known=linker_if_known, linker_evidence_type=linker_evidence_type,
            ))

        if suffix:
            payload_usage[payload_if_known].append(candidate_rows[-1]["entity_id"])
            linker_usage[linker_if_known].append(candidate_rows[-1]["entity_id"])

    write_tsv(output_dir / "adc_candidates.tsv", candidate_rows, CANDIDATE_FIELDS)
    print(f"adc_candidates.tsv: {len(candidate_rows)} entities "
          f"({sum(1 for r in candidate_rows if r['confidence'] == 'high')} high-confidence)", file=sys.stderr)

    # adc_targets.tsv: thin, known-registry-only in this phase -- new
    # candidates have no known target identity yet (honestly left absent,
    # per Part 4's explicit tolerance for partial entities), not guessed.
    # adc_antibodies.tsv is deliberately NOT produced this phase (round-1
    # fix) -- see module docstring for why.
    target_rows = []
    for asset in known_registry.values():
        if not asset.get("active", True):
            continue
        candidate_entity_id = f"ADC_CANDIDATE_{asset['asset_id'].upper()}"
        target_rows.append(dict(
            entity_id=f"ADC_TARGET_{normalize_name(asset['target']).upper()}", entity_type="ADC_TARGET",
            canonical_label=asset["target"], aliases="", first_seen="", last_seen="",
            evidence_count=1, evidence_sources="configs/known_adc_assets.yaml",
            confidence="high", status="VALIDATED", associated_adc_candidates=candidate_entity_id,
        ))
    # Merge duplicate targets (multiple known assets can share one target,
    # e.g. HER2) into one entity with all associated candidates listed.
    merged_targets: dict[str, dict] = {}
    for row in target_rows:
        existing = merged_targets.get(row["entity_id"])
        if existing:
            existing["evidence_count"] += 1
            existing["associated_adc_candidates"] += "; " + row["associated_adc_candidates"]
        else:
            merged_targets[row["entity_id"]] = row
    write_tsv(output_dir / "adc_targets.tsv", list(merged_targets.values()), COMPONENT_FIELDS)
    print(f"adc_targets.tsv: {len(merged_targets)} entities (known-registry only this phase)", file=sys.stderr)

    # adc_payloads.tsv / adc_linkers.tsv: status = INFERRED (round-1 fix,
    # not VALIDATED) -- these are naming-convention inferences from a
    # generic drug name's USAN/INN stem, not a directly-extracted or
    # independently confirmed chemistry fact for any specific asset.
    payload_rows = [
        dict(
            entity_id=f"ADC_PAYLOAD_{normalize_name(label).upper()}", entity_type="ADC_PAYLOAD",
            canonical_label=label, aliases="", first_seen="", last_seen="",
            evidence_count=len(ids), evidence_sources=NAMING_INFERENCE,
            confidence="medium", status="INFERRED", associated_adc_candidates="; ".join(ids),
        )
        for label, ids in payload_usage.items() if label
    ]
    linker_rows = [
        dict(
            entity_id=f"ADC_LINKER_{normalize_name(label).upper()}", entity_type="ADC_LINKER",
            canonical_label=label, aliases="", first_seen="", last_seen="",
            evidence_count=len(ids), evidence_sources=NAMING_INFERENCE,
            confidence="medium", status="INFERRED", associated_adc_candidates="; ".join(ids),
        )
        for label, ids in linker_usage.items() if label
    ]
    write_tsv(output_dir / "adc_payloads.tsv", payload_rows, COMPONENT_FIELDS)
    write_tsv(output_dir / "adc_linkers.tsv", linker_rows, COMPONENT_FIELDS)
    print(f"adc_payloads.tsv: {len(payload_rows)} entities (status=INFERRED, medium confidence -- "
          f"a naming-convention inference, not a validated chemistry fact)", file=sys.stderr)
    print(f"adc_linkers.tsv: {len(linker_rows)} entities (same basis and caveat as payloads)", file=sys.stderr)

    # adc_indications.tsv: aggregate distinct condition strings across all
    # validated candidates, with a count of how many candidates cite each.
    indication_counts: dict[str, int] = defaultdict(int)
    for row in candidate_rows:
        for ind in [i for i in row["indications"].split("; ") if i]:
            indication_counts[ind] += 1
    indication_rows = [
        dict(indication=ind, n_adc_candidates=count)
        for ind, count in sorted(indication_counts.items(), key=lambda kv: -kv[1])
    ]
    write_tsv(output_dir / "adc_indications.tsv", indication_rows, ["indication", "n_adc_candidates"])
    print(f"adc_indications.tsv: {len(indication_rows)} distinct indications "
          f"(from clinicaltrials 'conditions', not yet cross-checked against NAR)", file=sys.stderr)

    print(f"\nDone. Outputs written to {output_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
