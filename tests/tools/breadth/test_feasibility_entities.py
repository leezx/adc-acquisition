import sys

import pandas as pd
import yaml

from tools.breadth.feasibility_entities import (
    build_platform_rows,
    filter_promotable,
    load_text_corpus,
    main as feasibility_main,
    text_observed_payload_linker,
)


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


def test_text_observed_payload_linker_true_when_local_context_names_chemistry():
    """Phase 5e: a new candidate's own evidence record explicitly naming
    its payload chemistry in the LOCAL context around its own mention
    upgrades it from INFERRED to OBSERVED."""
    text = "Novel Fooximab vedotin ADC was conjugated to MMAE and showed potent activity in xenograft models."
    text_by_id = {"REC1": text}
    payload_observed, linker_observed = text_observed_payload_linker(
        "Fooximab vedotin", "vedotin", ["REC1"], text_by_id,
    )
    assert payload_observed is True


def test_text_observed_payload_linker_false_when_chemistry_belongs_to_different_candidate():
    """The cross-contamination guard (Phase 5b's own round-1 fix
    discipline, reused here): a DIFFERENT candidate's chemistry mentioned
    elsewhere in the same record must not upgrade THIS candidate's tier."""
    text = (
        "Trastuzumab deruxtecan uses an exatecan derivative payload. "
        "In contrast, Fooximab vedotin was evaluated as a comparator arm with no payload details disclosed."
    )
    text_by_id = {"REC1": text}
    payload_observed, linker_observed = text_observed_payload_linker(
        "Fooximab vedotin", "vedotin", ["REC1"], text_by_id,
    )
    assert payload_observed is False


def test_text_observed_payload_linker_false_when_no_evidence_text_available():
    payload_observed, linker_observed = text_observed_payload_linker(
        "Fooximab vedotin", "vedotin", ["UNKNOWN_ID"], {},
    )
    assert payload_observed is False
    assert linker_observed is False


def test_load_text_corpus_returns_empty_dict_for_missing_file(tmp_path):
    assert load_text_corpus(tmp_path / "nonexistent.parquet", ["title", "abstract"]) == {}


def test_build_platform_rows_finds_registered_platform_with_correct_status():
    text_corpora = [
        ("conference_abstract_corpus", {"REC1": "This ADC was prepared using MediLink's TMALIN platform."}),
        ("pubmed", {}),
    ]
    rows = build_platform_rows(text_corpora)
    assert len(rows) == 1
    row = rows[0]
    assert row["canonical_label"] == "TMALIN"
    assert row["entity_type"] == "ADC_PLATFORM"
    assert row["status"] == "OBSERVED"  # single source
    assert row["associated_adc_candidates"] == ""  # never guessed via co-occurrence


def test_build_platform_rows_validated_when_corroborated_across_two_corpora():
    text_corpora = [
        ("conference_abstract_corpus", {"REC1": "Prepared using the Dolaflexin platform."}),
        ("pubmed", {"REC2": "The Dolaflexin platform enables site-specific conjugation."}),
    ]
    rows = build_platform_rows(text_corpora)
    assert len(rows) == 1
    assert rows[0]["status"] == "VALIDATED"
    assert rows[0]["confidence"] == "high"


def test_build_platform_rows_no_hits_returns_empty_list():
    text_corpora = [("conference_abstract_corpus", {"REC1": "No named platform mentioned here at all."})]
    assert build_platform_rows(text_corpora) == []


def test_main_end_to_end_produces_platform_and_moa_target_tables_with_correct_tiers(tmp_path, monkeypatch):
    """Phase 5e end-to-end: a known-registry candidate's payload/linker
    is VALIDATED, a new candidate with corroborating local text is
    OBSERVED, payload_moa_targets.tsv resolves Tubulin for -vedotin, and
    a platform mention in the SAME evidence record is mined into
    adc_platforms.tsv -- all from evidence already written to tmp_path,
    no new acquisition."""
    known_assets_yaml = tmp_path / "known_adc_assets.yaml"
    known_assets_yaml.write_text(yaml.dump(dict(assets=[dict(
        asset_id="testuzumab_vedotin", canonical_name="Testuzumab vedotin", aliases=[], dev_codes=[],
        target="HER2", company="TestCo", active=True,
    )])))

    queue_path = tmp_path / "candidate_queue.tsv"
    queue_df = pd.DataFrame([
        dict(
            candidate_id="testuzumab_vedotin", candidate_type="ADC_CANDIDATE", candidate_label="Testuzumab vedotin",
            source="configs/known_adc_assets.yaml", evidence_id="testuzumab_vedotin", context="", first_seen="",
            confidence="high", validation_status="PROMOTED", reason="", modality_classification="STRICT_ADC",
            modality_detail="",
        ),
        dict(
            candidate_id="ADC_SUFFIX_new1", candidate_type="ADC_CANDIDATE", candidate_label="Newmab vedotin",
            source="clinicaltrials; conference_abstract_corpus", evidence_id="REC1", context="", first_seen="2026-01-01",
            confidence="high", validation_status="AUTO_HIGH_CONFIDENCE", reason="", modality_classification="PRESUMED_STRICT_ADC",
            modality_detail="",
        ),
    ])
    queue_df.to_csv(queue_path, sep="\t", index=False)

    data_dir = tmp_path / "DATA"
    (data_dir / "manifests").mkdir(parents=True)
    conf_df = pd.DataFrame([dict(
        source_record_id="REC1",
        title="Newmab vedotin ADC using the TMALIN platform",
        abstract="Newmab vedotin was conjugated to MMAE and showed potent antitumor activity.",
    )])
    conf_df.to_parquet(data_dir / "manifests" / "conference_abstract_corpus.parquet")

    output_dir = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", [
        "feasibility_entities.py",
        "--candidate-queue", str(queue_path),
        "--known-assets-file", str(known_assets_yaml),
        "--data-dir", str(data_dir),
        "--output", str(output_dir),
    ])
    feasibility_main()

    payloads = pd.read_csv(output_dir / "adc_payloads.tsv", sep="\t", dtype=str).fillna("")
    mmae_row = payloads[payloads["canonical_label"].str.contains("MMAE")].iloc[0]
    assert mmae_row["status"] == "VALIDATED"  # known asset present -> best tier wins
    assert "TEXT_OBSERVED" in mmae_row["evidence_sources"]
    assert "VALIDATED_KNOWN_ASSET" in mmae_row["evidence_sources"]

    moa_targets = pd.read_csv(output_dir / "payload_moa_targets.tsv", sep="\t", dtype=str).fillna("")
    assert "Tubulin" in moa_targets["canonical_label"].tolist()

    platforms = pd.read_csv(output_dir / "adc_platforms.tsv", sep="\t", dtype=str).fillna("")
    assert "TMALIN" in platforms["canonical_label"].tolist()
    tmalin_row = platforms[platforms["canonical_label"] == "TMALIN"].iloc[0]
    assert tmalin_row["status"] == "OBSERVED"
    assert tmalin_row["associated_adc_candidates"] == ""
