import pandas as pd

from tools.catalog.build_adc_asset_universe import (
    CLINICAL_DEVELOPMENT_FIELDS,
    build_coverage_report,
    build_master_rows,
    catalog_status_for_ours_only,
    compute_adc_scope,
    load_our_candidates,
    main as universe_main,
    nar_identifiers,
    write_clinical_development_view,
)


def _nar_row(**kw):
    base = dict(
        nar_adc_id="NARID1", canonical_name="Foo mafodotin", phase_bucket="Phase2",
        drug_status="Phase 2", brand_name="", synonyms="", development_codes="",
        antigen_name="", payload_moa_target="", antibody_name="", payload_name="",
        linker_name="", indications="", companies="", reference_count="0",
        reference_dois="", nct_ids="",
    )
    base.update(kw)
    return base


def _write_tsv(path, rows):
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)


def test_nar_identifiers_pulls_name_brand_synonyms_and_dev_codes():
    row = _nar_row(canonical_name="Foo mafodotin", brand_name="Foobrand",
                    synonyms="FOO-123; FOO123", development_codes="ABC-9")
    idents = nar_identifiers(row)
    assert set(idents) == {"Foo mafodotin", "Foobrand", "FOO-123", "FOO123", "ABC-9"}


def test_build_master_rows_unions_every_nar_row_unconditionally():
    """Inclusion-first: a NAR row with zero matching evidence from us still
    gets exactly one master row with catalog_status=REFERENCE_CONFIRMED --
    this is the core architectural change from evidence-gated promotion."""
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="BAT-8008")]
    master_rows, stats = build_master_rows(nar_rows, our_candidates=[])
    assert len(master_rows) == 1
    assert master_rows[0]["catalog_status"] == "REFERENCE_CONFIRMED"
    assert master_rows[0]["canonical_name"] == "BAT-8008"
    assert stats == {"n_nar": 1, "n_matched": 0, "n_ours_only": 0, "n_excluded_modality": 0}


def test_compute_adc_scope_maps_modality_to_scope_axis():
    assert compute_adc_scope("STRICT_ADC") == "STRICT_ADC"
    assert compute_adc_scope("PRESUMED_STRICT_ADC") == "PRESUMED_ADC"
    assert compute_adc_scope("ADJACENT_CONJUGATE_MODALITY") == "ADJACENT_CONJUGATE_MODALITY"
    assert compute_adc_scope("") == "REFERENCE_UNCLASSIFIED"


def test_nar_only_row_never_independently_matched_is_reference_unclassified():
    """Round-1 fix (reviewer-identified blocker): NAR reference membership
    alone must never be read as a STRICT_ADC classification -- NAR's own
    702-asset universe includes non-classical-ADC antibody conjugates."""
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="AOC-1020")]
    master_rows, _ = build_master_rows(nar_rows, our_candidates=[])
    assert master_rows[0]["adc_scope"] == "REFERENCE_UNCLASSIFIED"
    assert master_rows[0]["modality"] == ""  # NAR itself exposes no modality field


def test_matched_known_registry_candidate_upgrades_nar_row_to_strict_adc_scope():
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="Trastuzumab deruxtecan")]
    candidate = dict(
        origin="adc_candidates.tsv", key="k1", label="Trastuzumab deruxtecan",
        aliases=[], dev_codes=[], target="HER2", company="Daiichi Sankyo", stage="Approved",
        modality_classification="STRICT_ADC", sources=["configs/known_adc_assets.yaml", "clinicaltrials"],
        first_seen="", last_seen="",
    )
    master_rows, _ = build_master_rows(nar_rows, [candidate])
    assert master_rows[0]["adc_scope"] == "STRICT_ADC"


def test_ours_only_suffix_derived_candidate_is_presumed_adc_scope():
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="Unrelated")]
    candidate = dict(
        origin="adc_candidates.tsv", key="k1", label="Brand New Vedotin",
        aliases=[], dev_codes=[], target="", company="", stage="PHASE1",
        modality_classification="PRESUMED_STRICT_ADC", sources=["clinicaltrials"],
        first_seen="", last_seen="",
    )
    master_rows, _ = build_master_rows(nar_rows, [candidate])
    ours_row = next(r for r in master_rows if r["asset_id"].startswith("OURS_"))
    assert ours_row["adc_scope"] == "PRESUMED_ADC"


def test_exact_match_merges_candidate_into_existing_nar_row_not_a_new_row():
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="Trastuzumab deruxtecan",
                          synonyms="DS-8201; T-DXd")]
    candidate = dict(
        origin="adc_candidates.tsv", key="ADC_CANDIDATE_TDXD", label="Trastuzumab deruxtecan",
        aliases=[], dev_codes=["DS-8201"], target="HER2", company="Daiichi Sankyo", stage="Approved",
        modality_classification="STRICT_ADC", sources=["configs/known_adc_assets.yaml", "clinicaltrials"],
        first_seen="2026-01-01", last_seen="2026-01-01",
    )
    master_rows, stats = build_master_rows(nar_rows, [candidate])
    assert len(master_rows) == 1  # merged, NOT a second row
    assert stats["n_matched"] == 1
    assert stats["n_ours_only"] == 0
    row = master_rows[0]
    assert row["catalog_status"] == "MULTISOURCE_CONFIRMED"
    assert "nar_reference" in row["sources"]
    assert "clinicaltrials" in row["sources"]
    assert row["target"] == "HER2"  # backfilled from our evidence since NAR left it blank


def test_no_exact_match_creates_a_new_ours_only_row():
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="Something else entirely")]
    candidate = dict(
        origin="adc_candidates.tsv", key="ADC_CANDIDATE_NEW1", label="Brand New Vedotin",
        aliases=[], dev_codes=[], target="", company="", stage="PHASE1",
        modality_classification="PRESUMED_STRICT_ADC", sources=["clinicaltrials"],
        first_seen="2026-01-01", last_seen="2026-01-01",
    )
    master_rows, stats = build_master_rows(nar_rows, [candidate])
    assert len(master_rows) == 2  # NAR row untouched + one new ours-only row
    assert stats["n_matched"] == 0
    assert stats["n_ours_only"] == 1
    ours_row = next(r for r in master_rows if r["asset_id"].startswith("OURS_"))
    assert ours_row["catalog_status"] == "SINGLE_STRONG_SOURCE"
    assert ours_row["canonical_name"] == "Brand New Vedotin"


def test_misspelled_variant_does_not_exact_match_the_real_asset():
    """Documents the disclosed limitation: exact-identifier resolution
    does NOT catch a misspelled variant -- it becomes its own separate
    row, not merged into the real asset."""
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="Trastuzumab deruxtecan")]
    typo_candidate = dict(
        origin="candidate_queue.tsv", key="ADC_SUFFIX_typo1", label="Trastuzmab deruxtecan",
        aliases=[], dev_codes=[], target="", company="", stage="",
        modality_classification="PRESUMED_STRICT_ADC", sources=["conference_abstract_corpus"],
        first_seen="2026-01-01", last_seen="",
    )
    master_rows, stats = build_master_rows(nar_rows, [typo_candidate])
    assert len(master_rows) == 2  # NOT merged -- exact match only
    assert stats["n_matched"] == 0
    assert stats["n_ours_only"] == 1


def test_candidate_queue_needs_review_candidate_gets_needs_review_status():
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="Unrelated asset")]
    candidate = dict(
        origin="candidate_queue.tsv", key="ADC_SUFFIX_x1", label="Some New Vedotin",
        aliases=[], dev_codes=[], target="", company="", stage="",
        modality_classification="PRESUMED_STRICT_ADC", sources=["conference_abstract_corpus"],
        first_seen="2026-01-01", last_seen="",
    )
    assert catalog_status_for_ours_only(candidate) == "NEEDS_REVIEW"


def test_adjacent_modality_candidate_is_excluded_not_merged_or_ours_only():
    nar_rows = [_nar_row(nar_adc_id="NARID1", canonical_name="Some Peptide Conjugate")]
    candidate = dict(
        origin="candidate_queue.tsv", key="ADC_SUFFIX_adj1", label="Some Peptide Conjugate",
        aliases=[], dev_codes=[], target="", company="", stage="",
        modality_classification="ADJACENT_CONJUGATE_MODALITY", sources=["conference_abstract_corpus"],
        first_seen="2026-01-01", last_seen="",
    )
    master_rows, stats = build_master_rows(nar_rows, [candidate])
    assert stats["n_excluded_modality"] == 1
    assert stats["n_matched"] == 0  # never attempted a merge, even though the label would exact-match
    excluded_row = next(r for r in master_rows if r["asset_id"].startswith("OURS_"))
    assert excluded_row["catalog_status"] == "EXCLUDED_ADJACENT_MODALITY"
    assert excluded_row["adc_scope"] == "ADJACENT_CONJUGATE_MODALITY"
    nar_row = next(r for r in master_rows if r["asset_id"].startswith("NAR_"))
    assert nar_row["catalog_status"] == "REFERENCE_CONFIRMED"  # untouched


def test_single_source_promoted_candidate_stays_single_strong_source():
    candidate = dict(
        origin="adc_candidates.tsv", key="k1", label="X", aliases=[], dev_codes=[],
        target="", company="", stage="", modality_classification="STRICT_ADC",
        sources=["clinicaltrials"], first_seen="", last_seen="",
    )
    assert catalog_status_for_ours_only(candidate) == "SINGLE_STRONG_SOURCE"


def test_multi_source_promoted_candidate_is_multisource_confirmed():
    candidate = dict(
        origin="adc_candidates.tsv", key="k1", label="X", aliases=[], dev_codes=[],
        target="", company="", stage="", modality_classification="STRICT_ADC",
        sources=["clinicaltrials", "conference_abstract_corpus"], first_seen="", last_seen="",
    )
    assert catalog_status_for_ours_only(candidate) == "MULTISOURCE_CONFIRMED"


def test_coverage_report_gate_a_shows_full_nar_representation():
    nar_rows = [
        _nar_row(nar_adc_id="N1", canonical_name="A", phase_bucket="Approved"),
        _nar_row(nar_adc_id="N2", canonical_name="B", phase_bucket="Phase1"),
    ]
    master_rows, _ = build_master_rows(nar_rows, our_candidates=[])
    report = build_coverage_report(master_rows, nar_rows)
    assert "represented in master:               2 / 2" in report
    assert "Approved:                            1 / 1" in report
    assert "Phase 1:                             1 / 1" in report


def test_coverage_report_total_universe_excludes_adjacent_modality_rows():
    nar_rows = [_nar_row(nar_adc_id="N1", canonical_name="A")]
    excluded_candidate = dict(
        origin="candidate_queue.tsv", key="k1", label="Adjacent Thing", aliases=[], dev_codes=[],
        target="", company="", stage="", modality_classification="ADJACENT_CONJUGATE_MODALITY",
        sources=["conference_abstract_corpus"], first_seen="", last_seen="",
    )
    master_rows, _ = build_master_rows(nar_rows, [excluded_candidate])
    report = build_coverage_report(master_rows, nar_rows)
    # 1 NAR row + 1 excluded row = 2 catalog rows, but the ADC-oriented
    # superset excludes the adjacent-modality row.
    assert "TOTAL CATALOG ROWS:                  2" in report
    assert "ADC-ORIENTED SUPERSET:               1" in report
    assert "explicit modality exclusions:        1" in report
    assert "TOTAL UNIQUE ADC UNIVERSE" not in report  # round-1 fix: this framing must not reappear


def test_load_our_candidates_combines_promoted_and_needs_review_only(tmp_path):
    feas = tmp_path / "feasibility"
    feas.mkdir()
    _write_tsv(feas / "adc_candidates.tsv", [
        dict(entity_id="E1", canonical_label="Promoted One", aliases="", development_codes="",
             target="HER2", company="Acme", stage="Approved", modality_classification="STRICT_ADC",
             evidence_sources="clinicaltrials", first_seen="2026-01-01", last_seen="2026-01-01"),
    ])
    _write_tsv(feas / "candidate_queue.tsv", [
        dict(candidate_id="C1", candidate_label="Pending Review One", source="conference_abstract_corpus",
             confidence="medium", validation_status="NEEDS_REVIEW", modality_classification="PRESUMED_STRICT_ADC",
             first_seen="2026-02-01"),
        dict(candidate_id="C2", candidate_label="Already Promoted Two", source="clinicaltrials",
             confidence="high", validation_status="AUTO_HIGH_CONFIDENCE", modality_classification="STRICT_ADC",
             first_seen="2026-01-01"),
    ])
    candidates = load_our_candidates(feas)
    labels = {c["label"] for c in candidates}
    assert labels == {"Promoted One", "Pending Review One"}  # AUTO_HIGH_CONFIDENCE row excluded (already promoted)


def test_end_to_end_main_writes_universe_tsv_and_report(tmp_path):
    feas = tmp_path / "feasibility"
    feas.mkdir()
    nar = tmp_path / "nar"
    nar.mkdir()
    _write_tsv(nar / "assets.tsv", [
        _nar_row(nar_adc_id="N1", canonical_name="Known Drug", phase_bucket="Approved"),
        _nar_row(nar_adc_id="N2", canonical_name="BAT-8008", phase_bucket="Phase1"),
    ])
    _write_tsv(feas / "adc_candidates.tsv", [
        dict(entity_id="E1", canonical_label="Known Drug", aliases="", development_codes="",
             target="HER2", company="Acme", stage="Approved", modality_classification="STRICT_ADC",
             evidence_sources="clinicaltrials", first_seen="2026-01-01", last_seen="2026-01-01"),
    ])
    _write_tsv(feas / "candidate_queue.tsv", [
        dict(candidate_id="C1", candidate_label="New Candidate Vedotin", source="conference_abstract_corpus",
             confidence="medium", validation_status="NEEDS_REVIEW", modality_classification="PRESUMED_STRICT_ADC",
             first_seen="2026-02-01"),
    ])

    output = tmp_path / "adc_asset_universe.tsv"
    report_output = tmp_path / "report.md"
    clinical_output = tmp_path / "adc_clinical_development.tsv"
    import sys
    argv_backup = sys.argv
    sys.argv = [
        "build_adc_asset_universe.py",
        "--feasibility-dir", str(feas), "--nar-dir", str(nar),
        "--output", str(output), "--report-output", str(report_output),
        "--clinical-development-output", str(clinical_output),
    ]
    try:
        rc = universe_main()
    finally:
        sys.argv = argv_backup
    assert rc == 0
    df = pd.read_csv(output, sep="\t", dtype=str).fillna("")
    assert len(df) == 3  # 2 NAR rows (1 merged, 1 untouched) + 1 ours-only NEEDS_REVIEW row
    assert set(df["catalog_status"]) == {"MULTISOURCE_CONFIRMED", "REFERENCE_CONFIRMED", "NEEDS_REVIEW"}
    # adc_scope: the merged known-registry row is STRICT_ADC, the untouched
    # NAR-only row (BAT-8008) is honestly REFERENCE_UNCLASSIFIED, the
    # ours-only NEEDS_REVIEW row is PRESUMED_ADC.
    assert set(df["adc_scope"]) == {"STRICT_ADC", "REFERENCE_UNCLASSIFIED", "PRESUMED_ADC"}
    assert report_output.exists()
    report_text = report_output.read_text()
    assert "ADC-ORIENTED SUPERSET" in report_text
    assert "TOTAL UNIQUE ADC UNIVERSE" not in report_text
    assert clinical_output.exists()
    clinical_df = pd.read_csv(clinical_output, sep="\t", dtype=str).fillna("")
    assert len(clinical_df) == 3
    assert list(clinical_df.columns) == CLINICAL_DEVELOPMENT_FIELDS


def test_write_clinical_development_view_projects_only_the_documented_columns(tmp_path):
    rows = [dict(
        asset_id="NAR_N1", canonical_name="BAT-8008", aliases="", development_codes="",
        modality="", adc_scope="REFERENCE_UNCLASSIFIED", target="", company="", highest_stage="Phase1",
        development_status="Phase 1", nct_ids="", first_seen="", last_seen="", sources="nar_reference",
        source_count="1", evidence_ids="N1", catalog_status="REFERENCE_CONFIRMED",
    )]
    path = tmp_path / "clinical.tsv"
    write_clinical_development_view(path, rows)
    df = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    assert list(df.columns) == CLINICAL_DEVELOPMENT_FIELDS
    assert "asset_id" not in df.columns  # not part of the lightweight projection
    assert df.iloc[0]["canonical_name"] == "BAT-8008"
