from tools.breadth.feasibility_entities import build_target_indication_rows


def _candidate(entity_id, indications):
    return dict(entity_id=entity_id, indications="; ".join(indications))


def _target(entity_id, label, candidate_ids):
    return dict(entity_id=entity_id, canonical_label=label, associated_adc_candidates="; ".join(candidate_ids))


def test_build_target_indication_rows_one_candidate_two_indications():
    candidate_rows = [_candidate("ADC_CANDIDATE_A", ["Breast Cancer", "Gastric Cancer"])]
    target_rows = [_target("ADC_TARGET_HER2", "HER2", ["ADC_CANDIDATE_A"])]

    rows = build_target_indication_rows(candidate_rows, target_rows)

    assert len(rows) == 2
    indications = {r["indication"] for r in rows}
    assert indications == {"Breast Cancer", "Gastric Cancer"}
    for r in rows:
        assert r["target"] == "HER2"
        assert r["target_entity_id"] == "ADC_TARGET_HER2"
        assert r["evidence_count"] == 1
        assert r["associated_adc_candidates"] == "ADC_CANDIDATE_A"


def test_build_target_indication_rows_merges_evidence_for_shared_target_and_indication():
    candidate_rows = [
        _candidate("ADC_CANDIDATE_A", ["Breast Cancer"]),
        _candidate("ADC_CANDIDATE_B", ["Breast Cancer"]),
    ]
    target_rows = [_target("ADC_TARGET_HER2", "HER2", ["ADC_CANDIDATE_A", "ADC_CANDIDATE_B"])]

    rows = build_target_indication_rows(candidate_rows, target_rows)

    assert len(rows) == 1
    row = rows[0]
    assert row["evidence_count"] == 2
    assert row["associated_adc_candidates"] == "ADC_CANDIDATE_A; ADC_CANDIDATE_B"


def test_build_target_indication_rows_excludes_candidates_with_no_resolved_target():
    """A candidate not referenced by any target_row's associated_adc_candidates
    (e.g. one of Phase 5a's CT.gov/conference-derived candidates with
    target="") contributes no row -- not silently guessed."""
    candidate_rows = [
        _candidate("ADC_CANDIDATE_A", ["Breast Cancer"]),
        _candidate("ADC_CANDIDATE_NEW", ["Urothelial Cancer"]),
    ]
    target_rows = [_target("ADC_TARGET_HER2", "HER2", ["ADC_CANDIDATE_A"])]

    rows = build_target_indication_rows(candidate_rows, target_rows)

    assert len(rows) == 1
    assert rows[0]["indication"] == "Breast Cancer"


def test_build_target_indication_rows_handles_missing_candidate_gracefully():
    candidate_rows = []
    target_rows = [_target("ADC_TARGET_HER2", "HER2", ["ADC_CANDIDATE_MISSING"])]

    rows = build_target_indication_rows(candidate_rows, target_rows)

    assert rows == []


def test_build_target_indication_rows_sorted_by_evidence_count_then_target_then_indication():
    candidate_rows = [
        _candidate("ADC_CANDIDATE_A", ["Breast Cancer"]),
        _candidate("ADC_CANDIDATE_B", ["Breast Cancer"]),
        _candidate("ADC_CANDIDATE_C", ["Gastric Cancer"]),
    ]
    target_rows = [_target("ADC_TARGET_HER2", "HER2", ["ADC_CANDIDATE_A", "ADC_CANDIDATE_B", "ADC_CANDIDATE_C"])]

    rows = build_target_indication_rows(candidate_rows, target_rows)

    assert [r["indication"] for r in rows] == ["Breast Cancer", "Gastric Cancer"]
    assert rows[0]["evidence_count"] == 2
    assert rows[1]["evidence_count"] == 1
