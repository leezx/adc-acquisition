import sys

import pandas as pd

from tools.breadth.component_coverage_audit import main as audit_main


def _write_tsv(path, rows):
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)


def test_audit_end_to_end_classifies_coverage_and_nar_overlap(tmp_path, monkeypatch):
    feas = tmp_path / "feasibility"
    feas.mkdir()
    nar = tmp_path / "nar"
    nar.mkdir()

    _write_tsv(feas / "adc_candidates.tsv", [
        dict(entity_id="ADC_CANDIDATE_KNOWN1", target="HER2", payload_if_known="MMAE",
             payload_evidence_type="TEXT_VALIDATED_CROSS_CORPUS", linker_if_known="vc linker",
             linker_evidence_type="TEXT_VALIDATED_CROSS_CORPUS"),
        dict(entity_id="ADC_CANDIDATE_ADC_SUFFIX_new1", target="", payload_if_known="MMAE",
             payload_evidence_type="TEXT_OBSERVED", linker_if_known="vc linker",
             linker_evidence_type="USAN_INN_NAMING_INFERENCE"),
    ])
    _write_tsv(feas / "adc_targets.tsv", [dict(canonical_label="HER2")])
    _write_tsv(feas / "adc_payloads.tsv", [dict(canonical_label="MMAE (monomethyl auristatin E)")])
    _write_tsv(feas / "adc_linkers.tsv", [dict(canonical_label="valine-citrulline cleavable linker (typical)")])
    _write_tsv(feas / "adc_platforms.tsv", [
        dict(canonical_label="TMALIN", status="OBSERVED", evidence_count="3"),
        dict(canonical_label="GlycoConnect", status="VALIDATED", evidence_count="10"),
    ])
    _write_tsv(feas / "payload_moa_targets.tsv", [dict(canonical_label="Tubulin")])

    _write_tsv(nar / "adc_targets.tsv", [dict(canonical_name="HER2 (ERBB2)", synonyms="HER2; ERBB2")])
    _write_tsv(nar / "payloads.tsv", [dict(canonical_name="MMAE", synonyms="")])
    _write_tsv(nar / "linkers.tsv", [dict(canonical_name="MC-Val-Cit-PAB", synonyms="")])
    _write_tsv(nar / "payload_moa_targets.tsv", [dict(canonical_name="Microtubule (MT)", synonyms="")])

    output_path = tmp_path / "audit.tsv"
    monkeypatch.setattr(sys, "argv", [
        "component_coverage_audit.py",
        "--feasibility-dir", str(feas),
        "--nar-dir", str(nar),
        "--output", str(output_path),
    ])
    audit_main()

    audit = pd.read_csv(output_path, sep="\t", dtype=str).fillna("")
    by_metric = dict(zip(audit["metric"], audit["value"]))

    assert by_metric["known_registry.target_resolved"] == "1/1"
    assert by_metric["new_discovered.target_resolved"] == "0/1"
    assert by_metric["new_discovered.payload_tier.TEXT_OBSERVED"] == "1"

    assert by_metric["nar_comparison.adc_platform.nar_has_this_component_category"] == "NO"
    assert by_metric["adc_platforms.distinct_entities"] == "2"
    assert by_metric["adc_platforms.validated_cross_corpus"] == "1"

    # Tubulin must be recognized as "in both" via the documented Microtubule synonym,
    # not misreported as a novel MoA target NAR has never seen.
    assert by_metric["nar_comparison.payload_moa_target.in_both"] == "1"
    assert by_metric["nar_comparison.payload_moa_target.ours_only"] == "0"


def test_audit_handles_missing_nar_files_gracefully(tmp_path, monkeypatch):
    feas = tmp_path / "feasibility"
    feas.mkdir()
    _write_tsv(feas / "adc_candidates.tsv", [dict(entity_id="ADC_CANDIDATE_X", target="", payload_if_known="",
                                                   payload_evidence_type="", linker_if_known="", linker_evidence_type="")])
    output_path = tmp_path / "audit.tsv"
    monkeypatch.setattr(sys, "argv", [
        "component_coverage_audit.py",
        "--feasibility-dir", str(feas),
        "--nar-dir", str(tmp_path / "nonexistent_nar_dir"),
        "--output", str(output_path),
    ])
    assert audit_main() == 0
    assert output_path.exists()
