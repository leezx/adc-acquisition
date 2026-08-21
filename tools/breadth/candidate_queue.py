#!/usr/bin/env python3
"""Phase 3 (reports/validation/BREADTH_PLAN.md Part 9): a high-recall
DISCOVERY CANDIDATE queue, built entirely from evidence already in this
repo (`configs/known_adc_assets.yaml` + `DATA/manifests/clinicaltrials.
parquet`) -- no new acquisition sources in this phase.

Two-stage design, per Part 9: DISCOVERY CANDIDATE -> VALIDATED FEASIBILITY
ENTITY. This script builds the candidate queue only (`candidate_queue.tsv`);
`tools/breadth/feasibility_entities.py` consumes it and decides what
actually becomes a feasibility entity. Fuzzy-only promotion is explicitly
avoided (Part 9): every candidate here is either (a) already independently
curated/verified (`configs/known_adc_assets.yaml`, carried over from prior
audits), or (b) matched via a documented USAN/INN naming-convention stem
that is specific to ADC payload/linker chemistry -- not a free-text/fuzzy
guess.

ADC_SUFFIX_PAYLOAD_CLASS below is public pharmaceutical-nomenclature
knowledge (USAN/INN stems for antibody-drug-conjugate payload/linker
classes), independent of and not copied from the NAR ADCdb benchmark used
in Phases 1-2 -- confirmed empirically against all 8 distinct suffixes
present among our own 14 active known assets' canonical names. This list
is NOT claimed to be exhaustive; newer/rarer stems will be missed by
design in this phase (a Phase 5 concern, not this one).

Usage:
    python3 tools/breadth/candidate_queue.py \
        --known-assets-file configs/known_adc_assets.yaml \
        --data-dir DATA \
        --output DATA/feasibility
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

from adc_acquisition.hashing import sha256_bytes

# Documented USAN/INN stems for antibody-drug-conjugate payload/linker
# classes -- general pharmaceutical-nomenclature knowledge, not derived
# from or copied out of the NAR ADCdb vault used in Phases 1-2. Split into
# separate payload/linker maps (rather than one combined description) so
# tools/breadth/feasibility_entities.py can populate ADC_CANDIDATE's
# distinct payload_if_known/linker_if_known fields directly.
ADC_SUFFIX_PAYLOAD_CLASS = {
    "vedotin": "MMAE (monomethyl auristatin E)",
    "mafodotin": "MMAF (monomethyl auristatin F)",
    "emtansine": "DM1 (maytansinoid)",
    "soravtansine": "DM4 (maytansinoid)",
    "ozogamicin": "calicheamicin",
    "govitecan": "SN-38 (topoisomerase-1 inhibitor, irinotecan metabolite)",
    "tesirine": "a PBD (pyrrolobenzodiazepine) dimer",
    "deruxtecan": "an exatecan derivative (topoisomerase-1 inhibitor)",
}
ADC_SUFFIX_LINKER_CLASS = {
    "vedotin": "valine-citrulline cleavable linker (typical)",
    "mafodotin": "maleimidocaproyl non-cleavable linker (typical)",
    "emtansine": "SMCC non-cleavable linker (typical)",
    "soravtansine": "SPDB-based cleavable linker (typical)",
    "ozogamicin": "acid-cleavable AcBut linker (typical)",
    "govitecan": "cleavable CL2A linker (typical)",
    "tesirine": "cleavable linker (typical)",
    "deruxtecan": "cleavable GGFG peptide linker (typical)",
}

NON_DRUG_INTERVENTION_TERMS = {
    "surgery", "radiation therapy", "radiotherapy", "chemotherapy", "placebo", "observation",
    "best supportive care", "biopsy procedure", "quality-of-life assessment", "questionnaire administration",
    "laboratory biomarker analysis", "conventional surgery", "standard of care",
}


def load_known_registry(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("assets", [])


def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def known_identifier_set(assets: list[dict]) -> set[str]:
    out = set()
    for a in assets:
        out.add(normalize_name(a["canonical_name"]))
        for alias in a.get("aliases") or []:
            out.add(normalize_name(alias))
        for code in a.get("dev_codes") or []:
            out.add(normalize_name(code))
    return out


def mentions_known_asset(name: str, known_ids: set[str]) -> bool:
    """True if a known asset's identifier is EMBEDDED in this intervention
    string -- CT.gov intervention_names frequently records a combination
    regimen or trial-arm label (e.g. "Pembrolizumab + Enfortumab Vedotin",
    "Arm A: Belantamab Mafodotin") rather than a clean single-drug name.
    An exact normalized-string match alone misses these and would
    otherwise surface an already-known asset as a spurious "new"
    candidate -- confirmed empirically: every messy/combo-looking string
    in an initial run turned out to be exactly this, not a genuinely new
    but messily-labeled candidate. Substring containment (in either
    direction, to also catch a known canonical_name that itself carries
    extra qualifying text) is intentionally used only for this KNOWN-id
    suppression check -- never for asset-to-asset matching/promotion,
    which stays strict elsewhere in this pipeline."""
    normalized = normalize_name(name)
    return any(kid in normalized or normalized in kid for kid in known_ids if len(kid) >= 6)


def find_suffix_matches(name: str) -> str | None:
    normalized = name.lower().strip()
    for suffix in ADC_SUFFIX_PAYLOAD_CLASS:
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            return suffix
    return None


def build_ctgov_suffix_candidates(ct_manifest: pd.DataFrame, known_ids: set[str]) -> dict[str, dict]:
    """One aggregated candidate per distinct intervention name (across all
    trials that mention it), keyed by normalized name -- never split into
    fuzzy near-duplicates, never merged across genuinely different names."""
    candidates: dict[str, dict] = {}
    for _, row in ct_manifest.iterrows():
        names = row.get("intervention_names")
        if names is None:
            continue
        for raw_name in names:
            if not raw_name or raw_name.lower().strip() in NON_DRUG_INTERVENTION_TERMS:
                continue
            if mentions_known_asset(raw_name, known_ids):
                continue
            suffix = find_suffix_matches(raw_name)
            if not suffix:
                continue
            key = normalize_name(raw_name)
            entry = candidates.setdefault(key, dict(
                label=raw_name, suffix=suffix, nct_ids=set(), phases=set(),
                first_seen=None, contexts=set(),
            ))
            entry["nct_ids"].add(row["nct_id"])
            phases = row.get("phases")
            if phases is not None:
                for p in phases:
                    entry["phases"].add(p)
            entry["contexts"].add(str(row.get("brief_title", ""))[:150])
            posted = row.get("study_first_post_date")
            if posted and (entry["first_seen"] is None or str(posted) < entry["first_seen"]):
                entry["first_seen"] = str(posted)
    return candidates


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


CANDIDATE_QUEUE_FIELDS = [
    "candidate_id", "candidate_type", "candidate_label", "source", "evidence_id", "context",
    "first_seen", "confidence", "validation_status", "reason",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--known-assets-file", type=str, default="configs/known_adc_assets.yaml")
    parser.add_argument("--data-dir", type=str, default="DATA")
    parser.add_argument("--output", type=str, default="DATA/feasibility")
    args = parser.parse_args()

    output_dir = Path(args.output)
    known_assets = load_known_registry(Path(args.known_assets_file))
    active_known = [a for a in known_assets if a.get("active", True)]
    known_ids = known_identifier_set(active_known)

    rows = []
    for a in active_known:
        rows.append(dict(
            candidate_id=f"KNOWN_{a['asset_id'].upper()}",
            candidate_type="ADC_CANDIDATE",
            candidate_label=a["canonical_name"],
            source="configs/known_adc_assets.yaml",
            evidence_id=a["asset_id"],
            context="curated known-asset registry entry, independently verified in prior audits (PR #17)",
            first_seen="",
            confidence="high",
            validation_status="PROMOTED",
            reason="pre-curated, independently verified known ADC asset",
        ))

    ct_path = Path(args.data_dir) / "manifests" / "clinicaltrials.parquet"
    if ct_path.exists():
        ct_manifest = pd.read_parquet(ct_path)
        suffix_candidates = build_ctgov_suffix_candidates(ct_manifest, known_ids)
        print(f"Found {len(suffix_candidates)} distinct new candidate interventions via ADC USAN/INN suffix match",
              file=sys.stderr)
        for key, c in suffix_candidates.items():
            payload_class = ADC_SUFFIX_PAYLOAD_CLASS[c["suffix"]]
            nct_list = sorted(c["nct_ids"])
            rows.append(dict(
                candidate_id=f"CTGOV_SUFFIX_{sha256_bytes(key.encode('utf-8'))[:12]}",
                candidate_type="ADC_CANDIDATE",
                candidate_label=c["label"],
                source="clinicaltrials",
                evidence_id="; ".join(nct_list[:10]),
                context=f"generic name ends in '-{c['suffix']}' ({payload_class}); example trial: "
                        f"{sorted(c['contexts'])[0] if c['contexts'] else ''}",
                first_seen=c["first_seen"] or "",
                confidence="high",
                validation_status="AUTO_HIGH_CONFIDENCE",
                reason=f"generic drug name ends in the documented ADC USAN/INN payload-class stem '-{c['suffix']}'",
            ))

    write_tsv(output_dir / "candidate_queue.tsv", rows, CANDIDATE_QUEUE_FIELDS)
    n_promoted = sum(1 for r in rows if r["validation_status"] == "PROMOTED")
    n_auto = sum(1 for r in rows if r["validation_status"] == "AUTO_HIGH_CONFIDENCE")
    print(f"candidate_queue.tsv: {len(rows)} total ({n_promoted} PROMOTED from known registry, "
          f"{n_auto} AUTO_HIGH_CONFIDENCE from CT.gov suffix match)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
