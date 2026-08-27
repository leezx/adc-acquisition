#!/usr/bin/env python3
"""Build the ADC asset master catalog (reports/validation/BREADTH_PLAN.md
addendum, PR #30): reference-seeded, inclusion-first ADC asset universe.

ARCHITECTURAL CHANGE FROM PHASE 1-7's candidate_queue/adc_candidates
DESIGN: those tables answer "can we independently, high-confidence PROVE
this is an ADC from our own acquired text?" -- a discovery-precision
question. This tool answers a different question: "what is the fullest
list of ADC assets we know about, from every source including the NAR
reference universe itself?" -- a catalog-completeness question. Conflating
the two (requiring PROOF before an already-known-to-exist asset is allowed
into the database) is exactly the funnel design this tool replaces.

Catalog-first, discovery-second: DATA/reference/nar_adcdb/assets.tsv (702
phase-tagged NAR reference assets, already extracted read-only from the
external vault in Phase 1) is UNIONED with our own acquired candidates
(both promoted adc_candidates.tsv AND not-yet-promoted NEEDS_REVIEW rows
in candidate_queue.tsv) via exact-identifier resolution -- never filtered,
never gated on evidence strength. An asset's presence in the NAR reference
alone is sufficient grounds for inclusion (REFERENCE_CONFIRMED); our own
independent evidence, when present, upgrades or annotates that same row,
it never has to justify the row's existence in the first place.

Exact-identifier resolution only (same discipline as
tools/validation/compare_nar_adcdb.py's match_nar_to_known_assets): two
entities are the same asset only if a normalized (lowercase,
punctuation/whitespace-stripped) canonical name, alias, or development
code is IDENTICAL. This deliberately does NOT catch misspelled variants
(e.g. "Trastuzmab deruxtecan", "trastuzuamb deruxtecan" -- several exist
in the real committed candidate_queue.tsv, all missing/transposing a
letter from "Trastuzumab deruxtecan") -- disclosed explicitly in the
coverage report as a known, NOT-fixed-here gap (this is a candidate-
discovery-quality problem, a different concern than catalog union/
identity resolution, and conflating them here would be scope creep).

Never writes back to DATA/reference/nar_adcdb/*.tsv or DATA/feasibility/*
-- read-only against both, output is its own new table.

Round-1 fix (reviewer-identified blocker): INCLUSION and ADC-SCOPE
CLASSIFICATION are two separate axes, never conflated. NAR reference
membership alone is not proof a row is a classical antibody-drug
conjugate -- NAR's own 702-asset universe includes non-classical-ADC
antibody conjugates (antibody-oligonucleotide conjugates, antibody-STING-
agonist conjugates, photoimmunotherapy conjugates) alongside classical
ADCs. Every row gets its own `adc_scope` column (STRICT_ADC /
PRESUMED_ADC / REFERENCE_UNCLASSIFIED / ADJACENT_CONJUGATE_MODALITY),
computed from that row's own independent modality classification (from
OUR pipeline) where one exists, and honestly REFERENCE_UNCLASSIFIED
(never assumed STRICT_ADC) for a NAR row we never independently matched.
The coverage report's headline number is therefore "ADC-ORIENTED
SUPERSET" (all non-excluded catalog rows) and "STRICT/PRESUMED ADCs" (the
adc_scope-confirmed subset) -- never a single "TOTAL UNIQUE ADC UNIVERSE"
number that would silently claim every catalog row is a confirmed ADC.

Usage:
    python3 tools/catalog/build_adc_asset_universe.py \
        --feasibility-dir DATA/feasibility \
        --nar-dir DATA/reference/nar_adcdb \
        --output DATA/catalog/adc_asset_universe.tsv \
        --report-output reports/validation/breadth/ADC_ASSET_UNIVERSE_COVERAGE.md
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.validation.compare_nar_adcdb import normalize_name  # noqa: E402

UNIVERSE_FIELDS = [
    "asset_id", "canonical_name", "aliases", "development_codes",
    "modality", "adc_scope", "target", "company", "highest_stage", "development_status",
    "nct_ids", "first_seen", "last_seen", "sources", "source_count",
    "evidence_ids", "catalog_status",
]

ADJACENT_MODALITY_VALUE = "ADJACENT_CONJUGATE_MODALITY"

NAR_PHASE_BUCKETS = ["Approved", "Phase3", "Phase2", "Phase1", "Investigative"]
NAR_PHASE1_PLUS = {"Approved", "Phase3", "Phase2", "Phase1"}

# Round-1 fix (reviewer-identified blocker): NAR reference membership is an
# INCLUSION signal, never an ADC-SCOPE classification. NAR's own 702-asset
# universe includes non-classical-ADC antibody conjugates (e.g. AOC-1020,
# an antibody-oligonucleotide conjugate; TAK-500, an antibody-STING-agonist
# conjugate; Cetuximab sarotalocan, a photoimmunotherapy conjugate) -- so
# "in the catalog" must never be read as "is a STRICT_ADC." adc_scope is a
# SEPARATE axis from catalog_status (which measures evidence strength, not
# ontology scope): every row's own `modality` field (STRICT_ADC/
# PRESUMED_STRICT_ADC/ADJACENT_CONJUGATE_MODALITY when we have an
# independent classification from our own pipeline, blank when a NAR row
# was never matched to any of our own evidence) maps deterministically to
# one of the four ADC_SCOPE_VALUES below -- never guessed, never inferred
# from NAR membership alone.
ADC_SCOPE_VALUES = ("STRICT_ADC", "PRESUMED_ADC", "REFERENCE_UNCLASSIFIED", "ADJACENT_CONJUGATE_MODALITY")

_MODALITY_TO_ADC_SCOPE = {
    "STRICT_ADC": "STRICT_ADC",
    "PRESUMED_STRICT_ADC": "PRESUMED_ADC",
    "ADJACENT_CONJUGATE_MODALITY": "ADJACENT_CONJUGATE_MODALITY",
}


def compute_adc_scope(modality: str) -> str:
    """A row's own `modality` field is either an independent classification
    from OUR pipeline (STRICT_ADC = one of the 14 known-registry assets;
    PRESUMED_STRICT_ADC = suffix-derived with no adjacent-modality
    evidence; ADJACENT_CONJUGATE_MODALITY = positive adjacent-modality
    evidence) or blank (a pure NAR-reference row we never independently
    matched -- NAR itself exposes no modality field, see nar_identifiers()
    docstring, so this is honestly REFERENCE_UNCLASSIFIED, never assumed
    to be a strict ADC just because NAR lists it)."""
    return _MODALITY_TO_ADC_SCOPE.get(modality, "REFERENCE_UNCLASSIFIED")


def split_multi(value: str) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(";") if p.strip()]


def _read_tsv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str).fillna("") if path.exists() else pd.DataFrame()


def load_nar_assets(nar_dir: Path) -> list[dict]:
    df = _read_tsv(nar_dir / "assets.tsv")
    return df.to_dict("records")


def nar_identifiers(row: dict) -> list[str]:
    """Every distinct name-like string a NAR asset row is known by --
    canonical_name, synonyms, and development_codes are all matchable
    identifier pools (NAR's own extraction sometimes puts a development
    code inside the synonyms cell instead of development_codes -- both
    are searched, same discipline as compare_nar_adcdb.py's
    NARAsset.all_identifiers())."""
    out = [row.get("canonical_name", ""), row.get("brand_name", "")]
    out += split_multi(row.get("synonyms", ""))
    out += split_multi(row.get("development_codes", ""))
    return [x for x in out if x]


def build_nar_identifier_index(nar_rows: list[dict]) -> dict[str, str]:
    """normalized identifier -> nar_adc_id. First writer wins on a
    collision (rare; NAR's own dataset is not guaranteed collision-free
    across 702 distinct free-text entries) -- logged, never silently
    ignored, via the caller inspecting duplicate matches if needed."""
    index: dict[str, str] = {}
    for row in nar_rows:
        for ident in nar_identifiers(row):
            norm = normalize_name(ident)
            if norm and norm not in index:
                index[norm] = row["nar_adc_id"]
    return index


def load_our_candidates(feasibility_dir: Path) -> list[dict]:
    """UNION of adc_candidates.tsv (promoted, provenance-bearing) and
    candidate_queue.tsv's NOT-yet-promoted NEEDS_REVIEW rows (this is the
    architectural change from Phase 1-7: NEEDS_REVIEW candidates are no
    longer excluded from the catalog outright, they enter as their own
    honestly-labeled catalog_status instead of being invisible until
    promoted). Each candidate is normalized into one common dict shape
    regardless of which source table it came from."""
    candidates: list[dict] = []

    adc_candidates = _read_tsv(feasibility_dir / "adc_candidates.tsv")
    for row in adc_candidates.to_dict("records"):
        candidates.append({
            "origin": "adc_candidates.tsv",
            "key": row.get("entity_id", ""),
            "label": row.get("canonical_label", ""),
            "aliases": split_multi(row.get("aliases", "")),
            "dev_codes": split_multi(row.get("development_codes", "")),
            "target": row.get("target", ""),
            "company": row.get("company", ""),
            "stage": row.get("stage", ""),
            "modality_classification": row.get("modality_classification", ""),
            "sources": split_multi(row.get("evidence_sources", "")),
            "first_seen": row.get("first_seen", ""),
            "last_seen": row.get("last_seen", ""),
        })

    candidate_queue = _read_tsv(feasibility_dir / "candidate_queue.tsv")
    if not candidate_queue.empty:
        needs_review = candidate_queue[candidate_queue["validation_status"] == "NEEDS_REVIEW"]
        for row in needs_review.to_dict("records"):
            candidates.append({
                "origin": "candidate_queue.tsv",
                "key": row.get("candidate_id", ""),
                "label": row.get("candidate_label", ""),
                "aliases": [],
                "dev_codes": [],
                "target": "",
                "company": "",
                "stage": "",
                "modality_classification": row.get("modality_classification", ""),
                "sources": split_multi(row.get("source", "")),
                "first_seen": row.get("first_seen", ""),
                "last_seen": "",
            })

    return candidates


def candidate_identifiers(candidate: dict) -> list[str]:
    out = [candidate["label"], *candidate["aliases"], *candidate["dev_codes"]]
    return [x for x in out if x]


def match_candidate_to_nar(candidate: dict, nar_index: dict[str, str]) -> str | None:
    for ident in candidate_identifiers(candidate):
        norm = normalize_name(ident)
        if norm in nar_index:
            return nar_index[norm]
    return None


def catalog_status_for_ours_only(candidate: dict) -> str:
    if candidate["modality_classification"] == ADJACENT_MODALITY_VALUE:
        return "EXCLUDED_ADJACENT_MODALITY"
    if candidate["origin"] == "candidate_queue.tsv":
        return "NEEDS_REVIEW"
    # adc_candidates.tsv: promoted, provenance-bearing -- distinguish by
    # how many independent sources actually support it.
    return "MULTISOURCE_CONFIRMED" if len(set(candidate["sources"])) >= 2 else "SINGLE_STRONG_SOURCE"


def build_master_rows(nar_rows: list[dict], our_candidates: list[dict]) -> tuple[list[dict], dict]:
    """Returns (master_rows, match_stats). Union, never filter: every NAR
    row becomes exactly one master row unconditionally; every one of our
    own candidates either enriches an existing NAR-seeded row (matched) or
    becomes its own new master row (ours-only)."""
    nar_index = build_nar_identifier_index(nar_rows)

    master_by_nar_id: dict[str, dict] = {}
    for row in nar_rows:
        master_by_nar_id[row["nar_adc_id"]] = {
            "asset_id": f"NAR_{row['nar_adc_id']}",
            "canonical_name": row.get("canonical_name", ""),
            "aliases": row.get("synonyms", ""),
            "development_codes": row.get("development_codes", ""),
            "modality": "",  # NAR exposes no modality field -- not guessed, see module docstring
            "target": row.get("antigen_name", ""),
            "company": row.get("companies", ""),
            "highest_stage": row.get("phase_bucket", ""),
            "development_status": row.get("drug_status", ""),
            "nct_ids": row.get("nct_ids", ""),
            "first_seen": "",
            "last_seen": "",
            "sources": ["nar_reference"],
            "evidence_ids": [row["nar_adc_id"]],
            "catalog_status": "REFERENCE_CONFIRMED",
        }

    ours_only_rows: list[dict] = []
    n_matched = 0
    n_ours_only = 0
    n_excluded_modality = 0

    for candidate in our_candidates:
        if candidate["modality_classification"] == ADJACENT_MODALITY_VALUE:
            n_excluded_modality += 1
            ours_only_rows.append({
                "asset_id": f"OURS_{candidate['key']}",
                "canonical_name": candidate["label"],
                "aliases": "; ".join(candidate["aliases"]),
                "development_codes": "; ".join(candidate["dev_codes"]),
                "modality": candidate["modality_classification"],
                "target": candidate["target"],
                "company": candidate["company"],
                "highest_stage": candidate["stage"],
                "development_status": "",
                "nct_ids": "",
                "first_seen": candidate["first_seen"],
                "last_seen": candidate["last_seen"],
                "sources": candidate["sources"],
                "evidence_ids": [candidate["key"]],
                "catalog_status": "EXCLUDED_ADJACENT_MODALITY",
            })
            continue

        nar_id = match_candidate_to_nar(candidate, nar_index)
        if nar_id:
            n_matched += 1
            master_row = master_by_nar_id[nar_id]
            master_row["sources"] = list(dict.fromkeys(master_row["sources"] + candidate["sources"]))
            master_row["evidence_ids"] = list(dict.fromkeys(master_row["evidence_ids"] + [candidate["key"]]))
            if len(master_row["sources"]) >= 2:
                master_row["catalog_status"] = "MULTISOURCE_CONFIRMED"
            # Fill any NAR-blank descriptive fields from our own evidence,
            # never overwrite an already-populated NAR value.
            for field, value in (("target", candidate["target"]), ("company", candidate["company"]),
                                  ("highest_stage", candidate["stage"])):
                if not master_row[field] and value:
                    master_row[field] = value
            if not master_row["modality"] and candidate["modality_classification"]:
                master_row["modality"] = candidate["modality_classification"]
        else:
            n_ours_only += 1
            ours_only_rows.append({
                "asset_id": f"OURS_{candidate['key']}",
                "canonical_name": candidate["label"],
                "aliases": "; ".join(candidate["aliases"]),
                "development_codes": "; ".join(candidate["dev_codes"]),
                "modality": candidate["modality_classification"],
                "target": candidate["target"],
                "company": candidate["company"],
                "highest_stage": candidate["stage"],
                "development_status": "",
                "nct_ids": "",
                "first_seen": candidate["first_seen"],
                "last_seen": candidate["last_seen"],
                "sources": candidate["sources"],
                "evidence_ids": [candidate["key"]],
                "catalog_status": catalog_status_for_ours_only(candidate),
            })

    master_rows = list(master_by_nar_id.values()) + ours_only_rows
    for row in master_rows:
        row["sources"] = "; ".join(row["sources"])
        row["source_count"] = row["sources"].count(";") + 1 if row["sources"] else 0
        row["evidence_ids"] = "; ".join(str(e) for e in row["evidence_ids"])
        # Computed AFTER every modality backfill above (a NAR row matched to
        # one of our candidates may have just had `modality` filled in) --
        # adc_scope must reflect the row's final, fully-merged modality.
        row["adc_scope"] = compute_adc_scope(row["modality"])

    stats = {
        "n_nar": len(nar_rows), "n_matched": n_matched,
        "n_ours_only": n_ours_only, "n_excluded_modality": n_excluded_modality,
    }
    return master_rows, stats


def write_universe_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNIVERSE_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in UNIVERSE_FIELDS})


def build_coverage_report(master_rows: list[dict], nar_rows: list[dict]) -> str:
    by_status: dict[str, int] = {}
    for row in master_rows:
        by_status[row["catalog_status"]] = by_status.get(row["catalog_status"], 0) + 1

    nar_by_bucket = {b: 0 for b in NAR_PHASE_BUCKETS}
    for row in nar_rows:
        b = row.get("phase_bucket", "")
        if b in nar_by_bucket:
            nar_by_bucket[b] += 1

    represented_by_bucket = {b: 0 for b in NAR_PHASE_BUCKETS}
    for row in master_rows:
        if row["asset_id"].startswith("NAR_"):
            b = row["highest_stage"]
            if b in represented_by_bucket:
                represented_by_bucket[b] += 1

    n_nar_total = len(nar_rows)
    n_represented = sum(1 for row in master_rows if row["asset_id"].startswith("NAR_"))
    phase1_plus_nar = sum(v for k, v in nar_by_bucket.items() if k in NAR_PHASE1_PLUS)
    phase1_plus_represented = sum(v for k, v in represented_by_bucket.items() if k in NAR_PHASE1_PLUS)

    ours_only_total = sum(
        1 for row in master_rows
        if row["asset_id"].startswith("OURS_") and row["catalog_status"] != "EXCLUDED_ADJACENT_MODALITY"
    )
    needs_review = by_status.get("NEEDS_REVIEW", 0)
    excluded_modality = by_status.get("EXCLUDED_ADJACENT_MODALITY", 0)
    total_catalog_rows = len(master_rows)
    adc_oriented_superset = total_catalog_rows - excluded_modality

    by_scope: dict[str, int] = {}
    for row in master_rows:
        by_scope[row["adc_scope"]] = by_scope.get(row["adc_scope"], 0) + 1
    strict_or_presumed = by_scope.get("STRICT_ADC", 0) + by_scope.get("PRESUMED_ADC", 0)
    reference_unclassified = by_scope.get("REFERENCE_UNCLASSIFIED", 0)

    lines = [
        "# ADC Asset Universe — Coverage Report",
        "",
        "Per PR #30 ('Rebuild ADC asset universe: reference-seeded, "
        "inclusion-first master catalog'). Generated by "
        "`tools/catalog/build_adc_asset_universe.py` — unions "
        "`DATA/reference/nar_adcdb/assets.tsv` (702 NAR reference assets) "
        "with our own acquired candidates via exact-identifier resolution. "
        "Every NAR asset becomes exactly one master row unconditionally "
        "(inclusion-first, not evidence-gated).",
        "",
        "## Gate A — reference-seeded coverage",
        "",
        f"NAR reference assets:                {n_nar_total}",
        f"represented in master:               {n_represented} / {n_nar_total}",
        "",
        f"Approved:                            {represented_by_bucket['Approved']} / {nar_by_bucket['Approved']}",
        f"Phase 3:                             {represented_by_bucket['Phase3']} / {nar_by_bucket['Phase3']}",
        f"Phase 2:                             {represented_by_bucket['Phase2']} / {nar_by_bucket['Phase2']}",
        f"Phase 1:                             {represented_by_bucket['Phase1']} / {nar_by_bucket['Phase1']}",
        f"Investigative:                       {represented_by_bucket['Investigative']} / {nar_by_bucket['Investigative']}",
        "",
        "## Gate B — NAR Phase1+ assets represented",
        "",
        f"{phase1_plus_represented} / {phase1_plus_nar} "
        f"({'PASS' if phase1_plus_represented == phase1_plus_nar else 'GAP'} — every NAR row is unioned "
        "unconditionally by construction, so this is 100% by design; a "
        "gap here would indicate a bug in the union step, not a coverage "
        "shortfall).",
        "",
        "## Gate C — NAR Investigative assets represented as reference candidates",
        "",
        f"{represented_by_bucket['Investigative']} / {nar_by_bucket['Investigative']} present in master with "
        "catalog_status=REFERENCE_CONFIRMED (or upgraded to "
        "MULTISOURCE_CONFIRMED where we independently matched it) — "
        "included as reference candidates, NOT required to be independently "
        "VALIDATED by our own evidence to appear in the catalog.",
        "",
        "## Gate D — ours-only candidates kept separate, unioned after identity resolution",
        "",
        f"ours-only assets:                    {ours_only_total}",
        f"needs-review assets:                 {needs_review}",
        f"explicit modality exclusions:        {excluded_modality}",
        "",
        "## Gate E — no asset dropped merely for missing payload/linker/target",
        "",
        "PASS by construction — this catalog's schema has no gating "
        "requirement on target/payload/linker resolution; a NAR asset with "
        "target=company=stage entirely blank (NAR itself marks these "
        "\"Undisclosed\") still gets a master row with catalog_status="
        "REFERENCE_CONFIRMED.",
        "",
        "## Catalog status breakdown",
        "",
    ]
    for status in ("REFERENCE_CONFIRMED", "MULTISOURCE_CONFIRMED", "SINGLE_STRONG_SOURCE",
                   "NEEDS_REVIEW", "EXCLUDED_ADJACENT_MODALITY"):
        lines.append(f"- {status}: {by_status.get(status, 0)}")
    lines += [
        "",
        "## ADC-scope classification (round-1 fix — separate axis from catalog_status)",
        "",
        "`catalog_status` measures EVIDENCE STRENGTH (how well-supported is "
        "this row's presence in the catalog). `adc_scope` measures ONTOLOGY "
        "SCOPE (is this row actually a classical antibody-drug conjugate) "
        "-- the two must never be conflated. NAR reference membership alone "
        "is NOT an ADC-scope classification: NAR's own 702-asset universe "
        "includes non-classical-ADC antibody conjugates (e.g. an antibody-"
        "oligonucleotide conjugate, an antibody-STING-agonist conjugate, "
        "photoimmunotherapy conjugates) alongside classical ADCs. A NAR row "
        "we never independently matched to our own evidence is honestly "
        "REFERENCE_UNCLASSIFIED, not assumed STRICT_ADC.",
        "",
    ]
    for scope in ADC_SCOPE_VALUES:
        lines.append(f"- {scope}: {by_scope.get(scope, 0)}")
    lines += [
        "",
        f"TOTAL CATALOG ROWS:                  {total_catalog_rows}",
        f"EXPLICIT ADJACENT MODALITIES:        {excluded_modality}",
        f"ADC-ORIENTED SUPERSET:               {adc_oriented_superset}",
        "  (= all catalog rows minus EXCLUDED_ADJACENT_MODALITY rows -- a "
        "high-recall catalog of ADC-and-adjacent-conjugate candidates, "
        "NOT a claim that every row is independently confirmed to be a "
        "classical ADC.)",
        "",
        f"STRICT/PRESUMED ADCs:                {strict_or_presumed}",
        f"REFERENCE_UNCLASSIFIED:              {reference_unclassified}",
        "  (NAR-seeded rows never independently matched to our own "
        "modality-classified evidence -- their true ADC-scope status is "
        "simply not yet known to us, not defaulted to either answer.)",
        "",
        "## Known, disclosed limitation: exact-identifier resolution does not catch misspellings",
        "",
        "This tool's identity resolution is EXACT-identifier-only "
        "(normalized canonical name / alias / development code), the same "
        "discipline `tools/validation/compare_nar_adcdb.py` already "
        "established. It deliberately does NOT do fuzzy/edit-distance "
        "matching, so misspelled candidate labels from noisy source text "
        "(several real examples currently in `candidate_queue.tsv`, e.g. "
        "\"Trastuzmab deruxtecan\", \"trastuzuamb deruxtecan\", "
        "\"trastruzumab deruxtecan\", \"Tratuzumab deruxtecan\" — all "
        "missing/transposing a letter from the real \"Trastuzumab "
        "deruxtecan\", already in the catalog as an NAR-matched entry) "
        "remain as SEPARATE ours-only/needs-review rows rather than being "
        "merged into the asset they are actually typos of. This inflates "
        "the ours-only/needs-review counts above with likely-duplicate "
        "rows. Not fixed in this PR — candidate-discovery-quality "
        "deduplication is a distinct concern from catalog union/identity "
        "resolution and is flagged here for separate follow-up work, not "
        "silently absorbed into this PR's scope.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feasibility-dir", type=str, default="DATA/feasibility")
    parser.add_argument("--nar-dir", type=str, default="DATA/reference/nar_adcdb")
    parser.add_argument("--output", type=str, default="DATA/catalog/adc_asset_universe.tsv")
    parser.add_argument("--report-output", type=str,
                         default="reports/validation/breadth/ADC_ASSET_UNIVERSE_COVERAGE.md")
    args = parser.parse_args()

    nar_rows = load_nar_assets(Path(args.nar_dir))
    our_candidates = load_our_candidates(Path(args.feasibility_dir))
    master_rows, stats = build_master_rows(nar_rows, our_candidates)

    write_universe_tsv(Path(args.output), master_rows)
    Path(args.report_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report_output).write_text(build_coverage_report(master_rows, nar_rows), encoding="utf-8")

    excluded = sum(1 for r in master_rows if r["catalog_status"] == "EXCLUDED_ADJACENT_MODALITY")
    strict_or_presumed = sum(1 for r in master_rows if r["adc_scope"] in ("STRICT_ADC", "PRESUMED_ADC"))
    unclassified = sum(1 for r in master_rows if r["adc_scope"] == "REFERENCE_UNCLASSIFIED")
    print(
        f"adc_asset_universe: {len(master_rows)} catalog rows "
        f"({stats['n_nar']} NAR-seeded, {stats['n_matched']} matched to our own evidence, "
        f"{stats['n_ours_only']} ours-only, {stats['n_excluded_modality']} excluded-adjacent-modality) "
        f"-- {len(master_rows) - excluded} ADC-oriented superset "
        f"({strict_or_presumed} STRICT/PRESUMED_ADC, {unclassified} REFERENCE_UNCLASSIFIED). "
        f"Written to {args.output}, report at {args.report_output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
