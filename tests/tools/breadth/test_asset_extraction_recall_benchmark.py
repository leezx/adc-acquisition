import pandas as pd

from tools.breadth.asset_extraction_recall_benchmark import (
    build_report,
    classify_miss_cause,
    compute_benchmark,
)


def _broad_row(**kw):
    base = dict(nar_adc_id="N1", canonical_name="BAT-8008", phase_bucket="Phase1",
                status="BROAD_DISCOVERED", broad_sources="conference_abstract_corpus",
                matching_evidence_ids="", match_basis="EXACT_NAME", confidence="high",
                in_known_registry="False", root_cause_if_missing="")
    base.update(kw)
    return base


def _catalog_row(**kw):
    base = dict(asset_id="NAR_N1", canonical_name="BAT-8008", catalog_status="REFERENCE_CONFIRMED")
    base.update(kw)
    return base


def test_classify_miss_cause_dev_code_shaped():
    assert classify_miss_cause("BAT-8008") == "DEV_CODE_SHAPED"
    assert classify_miss_cause("PF-06804103") == "DEV_CODE_SHAPED"


def test_classify_miss_cause_uncovered_suffix():
    # "ecteribulin" is a real NAR USAN stem (Farletuzumab ecteribulin) NOT
    # in ADC_SUFFIX_PAYLOAD_CLASS (only a single-occurrence stem, below
    # the multi-asset confirmation bar PR #32 applied) -- genuinely uncovered.
    assert classify_miss_cause("Farletuzumab ecteribulin") == "UNCOVERED_SUFFIX"


def test_classify_miss_cause_suffix_covered_but_still_missed():
    assert classify_miss_cause("Sofituzumab vedotin") == "SUFFIX_COVERED_BUT_STILL_MISSED"


def test_classify_miss_cause_other_unclassified():
    assert classify_miss_cause("SGN-ALPV") == "OTHER_UNCLASSIFIED"


def test_compute_benchmark_only_includes_phase1_plus_broad_discovered():
    broad = pd.DataFrame([
        _broad_row(nar_adc_id="N1", phase_bucket="Phase1", status="BROAD_DISCOVERED"),
        _broad_row(nar_adc_id="N2", phase_bucket="Investigative", status="BROAD_DISCOVERED"),  # excluded: not Phase1+
        _broad_row(nar_adc_id="N3", phase_bucket="Phase2", status="NOT_CONFIRMED_BROAD"),  # excluded: not discovered
    ])
    catalog = pd.DataFrame([_catalog_row(asset_id="NAR_N1", catalog_status="MULTISOURCE_CONFIRMED")])
    benchmark = compute_benchmark(broad, catalog)
    assert len(benchmark) == 1
    assert benchmark.iloc[0]["nar_adc_id"] == "N1"


def test_compute_benchmark_marks_matched_true_for_multisource_confirmed():
    broad = pd.DataFrame([_broad_row(nar_adc_id="N1", canonical_name="Trastuzumab deruxtecan")])
    catalog = pd.DataFrame([_catalog_row(asset_id="NAR_N1", catalog_status="MULTISOURCE_CONFIRMED")])
    benchmark = compute_benchmark(broad, catalog)
    assert benchmark.iloc[0]["extractor_matched"] is True or benchmark.iloc[0]["extractor_matched"] == True  # noqa: E712
    assert benchmark.iloc[0]["miss_cause"] == ""


def test_compute_benchmark_marks_unmatched_reference_confirmed_as_miss_with_cause():
    broad = pd.DataFrame([_broad_row(nar_adc_id="N1", canonical_name="BAT-8008")])
    catalog = pd.DataFrame([_catalog_row(asset_id="NAR_N1", catalog_status="REFERENCE_CONFIRMED")])
    benchmark = compute_benchmark(broad, catalog)
    assert not benchmark.iloc[0]["extractor_matched"]
    assert benchmark.iloc[0]["miss_cause"] == "DEV_CODE_SHAPED"


def test_build_report_computes_recall_percentage_and_stop_criterion():
    benchmark = pd.DataFrame([
        dict(nar_adc_id="N1", canonical_name="A", phase_bucket="Phase1", broad_sources="x",
             match_basis="EXACT_NAME", extractor_matched=True, miss_cause=""),
        dict(nar_adc_id="N2", canonical_name="BAT-8008", phase_bucket="Phase1", broad_sources="x",
             match_basis="EXACT_NAME", extractor_matched=False, miss_cause="DEV_CODE_SHAPED"),
    ])
    report = build_report(benchmark)
    assert "Extractor recall: 1/2 = 50.0%" in report
    assert "NOT YET MET" in report
    assert "DEV_CODE_SHAPED: 1" in report


def test_build_report_stop_criterion_met_at_90_percent():
    rows = [dict(nar_adc_id=f"N{i}", canonical_name="A", phase_bucket="Phase1", broad_sources="x",
                 match_basis="EXACT_NAME", extractor_matched=(i < 9), miss_cause=("" if i < 9 else "OTHER_UNCLASSIFIED"))
            for i in range(10)]
    benchmark = pd.DataFrame(rows)
    report = build_report(benchmark)
    assert "Extractor recall: 9/10 = 90.0%" in report
    assert "-- MET." in report
