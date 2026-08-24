#!/usr/bin/env python3
"""Phase 5e (reports/validation/BREADTH_PLAN.md Phase 5 Part 11): coverage
audit for DATA/feasibility/{adc_targets,adc_payloads,adc_linkers,
adc_platforms}.tsv -- quantifies (a) how much of our OWN candidate
universe has a resolved target/payload/linker, broken out by known-
registry vs. new (Phase 3/5a-discovered) candidates, and (b) how our
component vocabularies compare against the NAR reference universe
(DATA/reference/nar_adcdb/*.tsv, built read-only in Phase 1) -- which of
our entities also appear in NAR ("in both"), and which do not
("ours-only", the genuine breadth-beyond-NAR signal this whole initiative
exists to measure).

This is a COMPARISON, never a copy: NAR content is read only to classify
our own already-independently-mined entities, never to seed or backfill
any DATA/feasibility/*.tsv value -- same discipline Phase 1-2's NAR
benchmark already established.

Usage:
    python3 tools/breadth/component_coverage_audit.py \
        --feasibility-dir DATA/feasibility \
        --nar-dir DATA/reference/nar_adcdb \
        --output reports/validation/breadth/component_coverage_audit.tsv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.breadth.candidate_queue import ADC_SUFFIX_LINKER_CLASS, ADC_SUFFIX_PAYLOAD_CLASS  # noqa: E402
from tools.breadth.component_evidence import LINKER_TEXT_SIGNALS, PAYLOAD_TEXT_SIGNALS  # noqa: E402

AUDIT_FIELDS = ["metric", "value", "detail"]

PAYLOAD_LABEL_TO_SUFFIX = {v: k for k, v in ADC_SUFFIX_PAYLOAD_CLASS.items()}
LINKER_LABEL_TO_SUFFIX = {v: k for k, v in ADC_SUFFIX_LINKER_CLASS.items()}

# Documented public-pharmacology synonym pairs needed for an HONEST (not
# overclaiming) NAR comparison -- discovered while building this audit:
# NAR's own payload_moa_targets.tsv uses "Microtubule (MT)" as its MoA-
# target label for auristatin/maytansinoid payloads, never "Tubulin" (the
# more textbook-precise term for the same binding target -- a tubulin
# inhibitor disrupts microtubule dynamics, the two terms describe the
# same mechanism in this literature). Without this synonym, "Tubulin"
# would be misreported as a genuinely novel MoA target beyond NAR's
# universe, when it is really just a terminology-convention difference.
MOA_TARGET_SYNONYMS = {"Tubulin": ["Tubulin", "Microtubule"]}


def write_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_tsv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str).fillna("") if path.exists() else pd.DataFrame()


def core_label(label: str) -> list[str]:
    """A component's canonical_label may carry a descriptive parenthetical
    ("MMAE (monomethyl auristatin E)") -- both the pre-parenthetical core
    term and the parenthetical's own content are plausible NAR-matchable
    forms, so both are tried."""
    label = label.strip()
    if "(" in label and label.endswith(")"):
        pre, paren = label.split("(", 1)
        return [pre.strip().rstrip(","), paren.rstrip(")").strip()]
    return [label]


def nar_text_blob(nar_df: pd.DataFrame, name_col: str = "canonical_name", syn_col: str = "synonyms") -> str:
    """One lowercased blob of every NAR canonical_name + synonym for this
    component type, for cheap substring containment checks -- NAR's own
    molecule-level entries are far more specific than our coarse USAN-
    suffix-CLASS labels, so containment (not exact match) is the
    appropriate comparison (see module docstring)."""
    parts = list(nar_df.get(name_col, pd.Series(dtype=str)).fillna(""))
    if syn_col in nar_df.columns:
        parts += list(nar_df[syn_col].fillna(""))
    return " | ".join(parts).lower()


def matches_nar(label: str, nar_blob: str) -> bool:
    return any(term.lower() in nar_blob for term in core_label(label) if len(term) >= 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feasibility-dir", type=str, default="DATA/feasibility")
    parser.add_argument("--nar-dir", type=str, default="DATA/reference/nar_adcdb")
    parser.add_argument("--output", type=str, default="reports/validation/breadth/component_coverage_audit.tsv")
    args = parser.parse_args()

    feas = Path(args.feasibility_dir)
    nar = Path(args.nar_dir)

    candidates = _read_tsv(feas / "adc_candidates.tsv")
    payloads = _read_tsv(feas / "adc_payloads.tsv")
    linkers = _read_tsv(feas / "adc_linkers.tsv")
    platforms = _read_tsv(feas / "adc_platforms.tsv")
    moa_targets = _read_tsv(feas / "payload_moa_targets.tsv")

    nar_payloads = _read_tsv(nar / "payloads.tsv")
    nar_linkers = _read_tsv(nar / "linkers.tsv")
    nar_adc_targets = _read_tsv(nar / "adc_targets.tsv")
    nar_moa_targets = _read_tsv(nar / "payload_moa_targets.tsv")

    rows: list[dict] = []

    def add(metric: str, value, detail: str = "") -> None:
        rows.append(dict(metric=metric, value=value, detail=detail))

    # --- Resolved coverage, by candidate group -----------------------------
    is_new = candidates["entity_id"].str.contains("ADC_SUFFIX")
    known = candidates[~is_new]
    new = candidates[is_new]
    for group_name, group in (("known_registry", known), ("new_discovered", new)):
        n = len(group)
        if n == 0:
            continue
        target_resolved = int((group["target"] != "").sum())
        payload_resolved = int((group["payload_if_known"] != "").sum())
        linker_resolved = int((group["linker_if_known"] != "").sum())
        add(f"{group_name}.candidate_count", n)
        add(f"{group_name}.target_resolved", f"{target_resolved}/{n}")
        add(f"{group_name}.payload_resolved", f"{payload_resolved}/{n}")
        add(f"{group_name}.linker_resolved", f"{linker_resolved}/{n}")
        for evidence_col, name in (("payload_evidence_type", "payload"), ("linker_evidence_type", "linker")):
            for tier in ("VALIDATED_KNOWN_ASSET", "TEXT_OBSERVED", "USAN_INN_NAMING_INFERENCE"):
                n_tier = int((group[evidence_col] == tier).sum())
                if n_tier:
                    add(f"{group_name}.{name}_tier.{tier}", n_tier)

    # --- Platform coverage --------------------------------------------------
    add("adc_platforms.distinct_entities", len(platforms))
    add("adc_platforms.validated_cross_corpus", int((platforms["status"] == "VALIDATED").sum()) if not platforms.empty else 0)
    add("adc_platforms.observed_single_source", int((platforms["status"] == "OBSERVED").sum()) if not platforms.empty else 0)
    add("adc_platforms.total_evidence_mentions", int(platforms["evidence_count"].astype(int).sum()) if not platforms.empty else 0,
        detail="sum of evidence_count across all platform entities")
    add("adc_platforms.candidates_with_resolved_platform_link", 0,
        detail="associated_adc_candidates deliberately never populated this phase -- proximity-based "
               "co-occurrence was tried and rejected as unreliable (see feasibility_entities.py's "
               "build_platform_rows() docstring for the real false-positive case found)")

    # --- NAR / ours-only classification -------------------------------------
    # ADC_PLATFORM: NAR's own extraction schema (Antigen/Antibody/Payload/
    # Linker/Target component pages) has NO platform category at all --
    # this is not "not found in NAR", it is "not a concept NAR's schema
    # captures", a categorical (not merely numeric) breadth-beyond-NAR
    # finding, true for all N of our platform entities regardless of match.
    add("nar_comparison.adc_platform.nar_has_this_component_category", "NO",
        detail="NAR's reference schema (Antigen/Antibody/Payload/Linker/Target pages) has no platform "
               "category at all -- every one of our adc_platforms.tsv entities is categorically beyond "
               "what NAR's own extraction schema captures, independent of any name-level match")

    def _classify(label: str, blob: str, keywords: list[str] | None) -> str:
        """Returns 'in_both' / 'ours_only' / 'not_compared'. Prefers a
        specific suffix-derived keyword list (PAYLOAD_TEXT_SIGNALS/
        LINKER_TEXT_SIGNALS -- e.g. "MMAE" for -vedotin) over the raw
        descriptive canonical_label, which often carries prose ("an
        exatecan derivative (topoisomerase-1 inhibitor)") too specific to
        ever literally appear in NAR's own terser molecule names. Falls
        back to 'not_compared' (never a guessed verdict either way) when
        no reliable keyword exists at all (e.g. -tesirine's linker, whose
        only registered description is the too-generic "cleavable
        linker")."""
        if keywords == []:  # a suffix IS registered but has no reliable keyword (e.g. -tesirine's linker)
            return "not_compared"
        terms = keywords if keywords else MOA_TARGET_SYNONYMS.get(label, core_label(label))
        return "in_both" if any(t.lower() in blob for t in terms if len(t) >= 3) else "ours_only"

    for label, our_df, nar_df, keyword_map, label_to_suffix in (
        ("adc_payload", payloads, nar_payloads, PAYLOAD_TEXT_SIGNALS, PAYLOAD_LABEL_TO_SUFFIX),
        ("adc_linker", linkers, nar_linkers, LINKER_TEXT_SIGNALS, LINKER_LABEL_TO_SUFFIX),
        ("adc_target", _read_tsv(feas / "adc_targets.tsv"), nar_adc_targets, {}, {}),
        ("payload_moa_target", moa_targets, nar_moa_targets, {}, {}),
    ):
        if our_df.empty:
            continue
        blob = nar_text_blob(nar_df)
        verdicts = [
            _classify(l, blob, keyword_map.get(label_to_suffix.get(l)) if label_to_suffix else None)
            for l in our_df["canonical_label"]
        ]
        n_in_both = verdicts.count("in_both")
        n_ours_only = verdicts.count("ours_only")
        n_not_compared = verdicts.count("not_compared")
        add(f"nar_comparison.{label}.in_both", n_in_both, detail=f"of {len(our_df)} our entities")
        add(f"nar_comparison.{label}.ours_only", n_ours_only,
            detail="; ".join(l for l, v in zip(our_df["canonical_label"], verdicts) if v == "ours_only") or "none")
        if n_not_compared:
            add(f"nar_comparison.{label}.not_compared", n_not_compared,
                detail="; ".join(l for l, v in zip(our_df["canonical_label"], verdicts) if v == "not_compared")
                + " -- no reliable keyword exists to compare (too generic a description to search NAR by)")

    write_tsv(Path(args.output), rows)
    for row in rows:
        print(f"{row['metric']}: {row['value']}" + (f"  ({row['detail']})" if row["detail"] else ""), file=sys.stderr)
    print(f"\nWrote {len(rows)} audit rows to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
