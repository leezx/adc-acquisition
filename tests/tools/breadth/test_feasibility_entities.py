import pandas as pd

from tools.breadth.feasibility_entities import filter_promotable


def _queue_row(**overrides):
    row = dict(
        candidate_id="X", candidate_type="ADC_CANDIDATE", candidate_label="Some vedotin",
        source="clinicaltrials", evidence_id="NCT1", context="", first_seen="", confidence="high",
        validation_status="AUTO_HIGH_CONFIDENCE", reason="", modality_classification="PRESUMED_STRICT_ADC",
        modality_detail="",
    )
    row.update(overrides)
    return row


def test_filter_promotable_excludes_adjacent_conjugate_modality_even_if_auto_high_confidence():
    """A candidate whose evidence positively confirms a non-strict-ADC
    modality must never be promoted, even if it were somehow
    AUTO_HIGH_CONFIDENCE -- the modality exclusion is independent of, and
    layered on top of, the validation_status check."""
    queue = pd.DataFrame([
        _queue_row(candidate_id="A", validation_status="AUTO_HIGH_CONFIDENCE",
                   modality_classification="ADJACENT_CONJUGATE_MODALITY"),
        _queue_row(candidate_id="B", validation_status="AUTO_HIGH_CONFIDENCE",
                   modality_classification="PRESUMED_STRICT_ADC"),
    ])
    promoted = filter_promotable(queue)
    assert list(promoted["candidate_id"]) == ["B"]


def test_filter_promotable_still_excludes_needs_review_regardless_of_modality():
    queue = pd.DataFrame([
        _queue_row(candidate_id="C", validation_status="NEEDS_REVIEW",
                   modality_classification="PRESUMED_STRICT_ADC"),
    ])
    promoted = filter_promotable(queue)
    assert promoted.empty


def test_filter_promotable_keeps_known_registry_strict_adc_rows():
    queue = pd.DataFrame([
        _queue_row(candidate_id="D", source="configs/known_adc_assets.yaml", validation_status="PROMOTED",
                   modality_classification="STRICT_ADC"),
    ])
    promoted = filter_promotable(queue)
    assert list(promoted["candidate_id"]) == ["D"]
