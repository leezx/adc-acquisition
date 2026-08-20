#!/usr/bin/env python3
"""Build the NAR ADCdb reference universe (reports/validation/BREADTH_PLAN.md
Phase 1 / Part 1): the 702 phase-tagged benchmark assets plus NAR's own
component reference tables (Antigens/Targets/Antibodies/Payloads/Linkers),
written to DATA/reference/nar_adcdb/*.tsv in THIS repo.

READ-ONLY against the external vault -- never writes, renames, or deletes
anything under --external-root. The raw external vault content is never
committed into this repository; only these small, derived TSVs are.

Reuses tools/validation/compare_nar_adcdb.py's proven NAR-asset extraction
(build_nar_benchmark_assets) rather than re-implementing it, per the Phase 1
plan (that module was merged into main via PR #17, a hard prerequisite for
this script).

ADC_TARGET vs. PAYLOAD_MOA_TARGET (BREADTH_PLAN.md Phase 1 ontology split,
permanent from this point forward):
  - adc_targets.tsv        <- NAR `Antigens/` (antibody-binding delivery target)
  - payload_moa_targets.tsv <- NAR `Targets/` (payload mechanism-of-action target)
These are never merged into one generic "target" table.

Usage:
    python3 tools/breadth/build_nar_reference_universe.py \
        --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
        --output DATA/reference/nar_adcdb

Re-running regenerates identical output from the external vault's current
state -- no manual editing of any output TSV is ever performed.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.breadth.nar_component_pages import load_component_pages  # noqa: E402
from tools.validation.compare_nar_adcdb import (  # noqa: E402
    NARAsset,
    build_nar_benchmark_assets,
)

PHASE_BUCKET_MAP = {
    # These are the exact 5 values NAR's own `status` field takes (verified
    # directly against _data/adc_inventory.json: Counter({'Phase 1': 297,
    # 'Investigative': 263, 'Phase 2': 84, 'Phase 3': 37, 'Approved': 21})
    # -- NOT the longer "Phase N Clinical Trial" phrasing used elsewhere in
    # NAR's per-ADC markdown pages (that phrasing is a different field,
    # STATUS_KEYWORDS in compare_nar_adcdb.py, used only to split the
    # free-text Indication cell).
    "Approved": "Approved",
    "Phase 3": "Phase3",
    "Phase 2": "Phase2",
    "Phase 1": "Phase1",
    "Investigative": "Investigative",
}


def phase_bucket(status: str) -> str:
    return PHASE_BUCKET_MAP.get(status, "Other")


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def build_asset_rows(assets: list[NARAsset]) -> list[dict]:
    rows = []
    for a in assets:
        rows.append(dict(
            nar_adc_id=a.adc_id,
            canonical_name=a.name,
            phase_bucket=phase_bucket(a.status),
            drug_status=a.drug_status_md or a.status,
            brand_name=a.brand_name or "",
            synonyms="; ".join(a.synonyms),
            # NAR's Synonyms field is a single flat list with no structural
            # marker distinguishing a development code from any other
            # synonym form -- left blank rather than guessed/fabricated.
            development_codes="",
            antigen_name=a.antigen_name_md or a.antibody_name_inv or "",
            payload_moa_target=a.therapeutic_target_md or "",
            antibody_name=a.antibody_name_md or a.antibody_name_inv or "",
            payload_name=a.payload_name_md or a.payload_name_inv or "",
            linker_name=a.linker_name_md or a.linker_name_inv or "",
            indications="; ".join(a.indications) if a.indications else a.representative_indication_inv,
            companies="; ".join(a.companies),
            reference_count=a.reference_count,
            reference_dois="; ".join(a.reference_dois),
            nct_ids="; ".join(a.nct_ids),
        ))
    return rows


def build_component_rows(vault_root: Path, subdir: str, entity_type: str, name_field: str, id_field: str, synonym_field: str = "Synonym", extra_fields: dict[str, str] | None = None) -> list[dict]:
    pages = load_component_pages(vault_root, subdir, entity_type)
    rows = []
    for p in pages:
        row = dict(
            entity_id=p.fields.get(id_field, p.entity_id),
            canonical_name=p.fields.get(name_field, p.canonical_name),
            entity_type=entity_type,
            synonyms=p.fields.get(synonym_field, ""),
            n_adc_backlinks=len(p.adc_backlink_names) + len(p.adc_backlink_ids),
            adc_backlink_names="; ".join(sorted(set(p.adc_backlink_names))[:30]),
            adc_backlink_ids="; ".join(sorted(set(p.adc_backlink_ids))[:30]),
            source_url=p.source_url,
        )
        if extra_fields:
            for out_key, table_key in extra_fields.items():
                row[out_key] = p.fields.get(table_key, "")
        rows.append(row)
    return rows


def _conjugate_type(relation_value: str) -> str:
    m = re.match(r"^(Non-[Cc]leavable|Cleavable)\b", relation_value or "")
    return m.group(1) if m else ""


def build_indication_rows(assets: list[NARAsset]) -> list[dict]:
    counter: Counter[str] = Counter()
    for a in assets:
        indications = a.indications if a.indications else ([a.representative_indication_inv] if a.representative_indication_inv else [])
        for ind in indications:
            counter[ind] += 1
    return [
        dict(indication=ind, n_nar_assets=count)
        for ind, count in sorted(counter.items(), key=lambda kv: -kv[1])
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=str, required=True)
    parser.add_argument("--output", type=str, default="DATA/reference/nar_adcdb")
    args = parser.parse_args()

    vault_root = Path(args.external_root)
    output_dir = Path(args.output)

    print("Loading NAR ADCdb 702-asset benchmark universe...", file=sys.stderr)
    assets = build_nar_benchmark_assets(vault_root)
    print(f"  {len(assets)} phase-tagged NAR assets", file=sys.stderr)
    write_tsv(
        output_dir / "assets.tsv", build_asset_rows(assets),
        ["nar_adc_id", "canonical_name", "phase_bucket", "drug_status", "brand_name",
         "synonyms", "development_codes", "antigen_name", "payload_moa_target",
         "antibody_name", "payload_name", "linker_name", "indications", "companies",
         "reference_count", "reference_dois", "nct_ids"],
    )

    print("Parsing NAR component reference pages...", file=sys.stderr)

    adc_targets = build_component_rows(
        vault_root, "Antigens", "ADC_TARGET", name_field="Antigen Name", id_field="Antigen ID",
    )
    write_tsv(
        output_dir / "adc_targets.tsv", adc_targets,
        ["entity_id", "canonical_name", "entity_type", "synonyms", "n_adc_backlinks",
         "adc_backlink_names", "adc_backlink_ids", "source_url"],
    )
    print(f"  adc_targets.tsv (NAR Antigens/, delivery target): {len(adc_targets)} rows", file=sys.stderr)

    payload_moa_targets = build_component_rows(
        vault_root, "Targets", "PAYLOAD_MOA_TARGET", name_field="Target Name", id_field="Target ID",
    )
    write_tsv(
        output_dir / "payload_moa_targets.tsv", payload_moa_targets,
        ["entity_id", "canonical_name", "entity_type", "synonyms", "n_adc_backlinks",
         "adc_backlink_names", "adc_backlink_ids", "source_url"],
    )
    print(f"  payload_moa_targets.tsv (NAR Targets/, payload MoA target): {len(payload_moa_targets)} rows "
          f"(backlinks are adc_id-only for this entity type -- see module docstring)", file=sys.stderr)

    antibodies = build_component_rows(
        vault_root, "Antibodies", "ADC_ANTIBODY", name_field="Antibody Name", id_field="Antibody ID",
        synonym_field="Antibody Subtype",
        extra_fields={"antibody_type": "Antibody Type", "binds_antigen_name": "Antigen Name"},
    )
    write_tsv(
        output_dir / "antibodies.tsv", antibodies,
        ["entity_id", "canonical_name", "entity_type", "antibody_type", "binds_antigen_name",
         "synonyms", "n_adc_backlinks", "adc_backlink_names", "adc_backlink_ids", "source_url"],
    )
    print(f"  antibodies.tsv: {len(antibodies)} rows", file=sys.stderr)

    payloads = build_component_rows(
        vault_root, "Payloads", "ADC_PAYLOAD", name_field="Name", id_field="Payload ID",
        synonym_field="Synonyms",
        extra_fields={"payload_moa_target": "Target(s)"},
    )
    write_tsv(
        output_dir / "payloads.tsv", payloads,
        ["entity_id", "canonical_name", "entity_type", "payload_moa_target", "synonyms",
         "n_adc_backlinks", "adc_backlink_names", "adc_backlink_ids", "source_url"],
    )
    print(f"  payloads.tsv: {len(payloads)} rows", file=sys.stderr)

    linker_pages = load_component_pages(vault_root, "Linkers", "ADC_LINKER")
    linker_rows = []
    for p in linker_pages:
        linker_rows.append(dict(
            entity_id=p.fields.get("Linker ID", p.entity_id),
            canonical_name=p.fields.get("Linker Name", p.canonical_name),
            entity_type="ADC_LINKER",
            conjugate_type=_conjugate_type(p.fields.get("Antibody-Linker Relation", "")),
            n_adc_backlinks=len(p.adc_backlink_names) + len(p.adc_backlink_ids),
            adc_backlink_names="; ".join(sorted(set(p.adc_backlink_names))[:30]),
            adc_backlink_ids="; ".join(sorted(set(p.adc_backlink_ids))[:30]),
            source_url=p.source_url,
        ))
    write_tsv(
        output_dir / "linkers.tsv", linker_rows,
        ["entity_id", "canonical_name", "entity_type", "conjugate_type", "n_adc_backlinks",
         "adc_backlink_names", "adc_backlink_ids", "source_url"],
    )
    print(f"  linkers.tsv: {len(linker_rows)} rows", file=sys.stderr)

    indication_rows = build_indication_rows(assets)
    write_tsv(output_dir / "indications.tsv", indication_rows, ["indication", "n_nar_assets"])
    print(f"  indications.tsv: {len(indication_rows)} distinct indication strings "
          f"(derived from the 702 assets' own free-text Indication field, not a separate "
          f"NAR entity type -- the vault has no dedicated Indications/Diseases page directory)",
          file=sys.stderr)

    print(f"\nDone. Outputs written to {output_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
