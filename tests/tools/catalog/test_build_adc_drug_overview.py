import csv

import pandas as pd

from tools.catalog.build_adc_drug_overview import (
    OVERVIEW_FIELDS,
    build_overview_rows,
    load_existing_overview,
    load_tsv,
    main as overview_main,
    write_overview_csv,
)


def _catalog_row(**kw):
    base = dict(
        asset_id="NAR_A1", canonical_name="Foo vedotin", aliases=None, development_codes=None,
        target="HER2", company="Acme", modality="PRESUMED_STRICT_ADC", adc_scope="PRESUMED_ADC",
        highest_stage="Phase1", development_status="Phase 1", nct_ids="NCT001", first_seen=None,
        last_seen=None, sources="nar_reference", source_count="1", evidence_ids="A1",
        catalog_status="REFERENCE_CONFIRMED",
    )
    base.update(kw)
    return base


def _candidate_row(**kw):
    base = dict(
        entity_id="ADC_CANDIDATE_FOO", entity_type="ADC_CANDIDATE", canonical_label="Foo vedotin",
        aliases=None, first_seen=None, last_seen=None, evidence_count="1", evidence_sources="clinicaltrials",
        confidence="high", status="VALIDATED", asset_name="Foo vedotin", development_codes=None,
        target="HER2", company="Acme", stage="Phase1", indications="breast cancer",
        payload_if_known="MMAE", payload_evidence_type="suffix", linker_if_known="vc linker",
        linker_evidence_type="suffix", modality_classification="STRICT_ADC",
    )
    base.update(kw)
    return base


def test_build_overview_rows_enriches_payload_linker_indication_from_candidates():
    catalog = [_catalog_row(asset_id="NAR_A1", evidence_ids="A1; ADC_CANDIDATE_FOO")]
    candidates = [_candidate_row()]
    rows = build_overview_rows(catalog, candidates, [], today="2026-09-01")
    assert len(rows) == 1
    row = rows[0]
    assert row["payload"] == "MMAE"
    assert row["linker"] == "vc linker"
    assert row["indication"] == "breast cancer"
    assert row["target"] == "HER2"
    assert row["clinical_phase"] == "Phase 1"
    assert row["date_added_to_table"] == "2026-09-01"


def test_build_overview_rows_leaves_payload_blank_when_no_candidate_match():
    catalog = [_catalog_row(asset_id="NAR_A1", evidence_ids="A1")]
    rows = build_overview_rows(catalog, [], [], today="2026-09-01")
    assert rows[0]["payload"] is None
    assert rows[0]["linker"] is None
    assert rows[0]["indication"] is None
    # Target/company/phase still come from the base catalog table, unaffected.
    assert rows[0]["target"] == "HER2"


def test_existing_row_order_is_never_reshuffled():
    catalog = [
        _catalog_row(asset_id="NAR_B", canonical_name="B drug", evidence_ids="B"),
        _catalog_row(asset_id="NAR_A", canonical_name="A drug", evidence_ids="A"),
    ]
    existing = [
        dict.fromkeys(OVERVIEW_FIELDS, "")
        | dict(asset_id="NAR_B", canonical_name="B drug", date_added_to_table="2026-08-01"),
    ]
    rows = build_overview_rows(catalog, [], existing, today="2026-09-01")
    # NAR_B (already present) stays first even though NAR_A sorts earlier;
    # the genuinely new NAR_A is appended at the tail.
    assert [r["asset_id"] for r in rows] == ["NAR_B", "NAR_A"]
    assert rows[1]["date_added_to_table"] == "2026-09-01"


def test_previously_added_row_keeps_its_original_date_added_on_rerun():
    catalog = [_catalog_row(asset_id="NAR_A1", evidence_ids="A1")]
    existing = [
        dict.fromkeys(OVERVIEW_FIELDS, "")
        | dict(asset_id="NAR_A1", canonical_name="Foo vedotin", date_added_to_table="2026-01-01"),
    ]
    rows = build_overview_rows(catalog, [], existing, today="2026-09-01")
    assert rows[0]["date_added_to_table"] == "2026-01-01"  # unchanged, not re-stamped


def test_rerun_with_no_new_assets_is_a_pure_no_op():
    catalog = [_catalog_row(asset_id="NAR_A1", evidence_ids="A1")]
    first = build_overview_rows(catalog, [], [], today="2026-01-01")
    second = build_overview_rows(catalog, [], first, today="2026-09-01")
    assert first == second


def test_asset_removed_from_catalog_is_kept_as_stale_historical_row_not_dropped():
    """Simulates an identity merge: NAR_OLD existed in a prior overview run
    but no longer appears in the base catalog (e.g. folded into another
    asset_id). It must be kept, not silently deleted."""
    existing = [
        dict.fromkeys(OVERVIEW_FIELDS, "")
        | dict(asset_id="NAR_OLD", canonical_name="Old drug", date_added_to_table="2026-01-01"),
    ]
    rows = build_overview_rows([], [], existing, today="2026-09-01")
    assert len(rows) == 1
    assert rows[0]["asset_id"] == "NAR_OLD"
    assert rows[0]["date_added_to_table"] == "2026-01-01"


def test_multiple_new_assets_appended_in_sorted_order_for_determinism():
    catalog = [
        _catalog_row(asset_id="NAR_C", evidence_ids="C"),
        _catalog_row(asset_id="NAR_A", evidence_ids="A"),
        _catalog_row(asset_id="NAR_B", evidence_ids="B"),
    ]
    rows = build_overview_rows(catalog, [], [], today="2026-09-01")
    assert [r["asset_id"] for r in rows] == ["NAR_A", "NAR_B", "NAR_C"]


def test_write_and_reload_round_trip(tmp_path):
    catalog = [_catalog_row(asset_id="NAR_A1", evidence_ids="A1; ADC_CANDIDATE_FOO")]
    rows = build_overview_rows(catalog, [_candidate_row()], [], today="2026-09-01")
    out_path = tmp_path / "overview.csv"
    write_overview_csv(out_path, rows)

    reloaded = load_existing_overview(out_path)
    assert len(reloaded) == 1
    assert reloaded[0]["asset_id"] == "NAR_A1"
    assert reloaded[0]["payload"] == "MMAE"
    with out_path.open() as f:
        header = next(csv.reader(f))
    assert header == OVERVIEW_FIELDS


def test_load_tsv_converts_nan_to_none(tmp_path):
    path = tmp_path / "t.tsv"
    pd.DataFrame([{"asset_id": "A", "target": None}]).to_csv(path, sep="\t", index=False)
    rows = load_tsv(path)
    assert rows[0]["target"] is None


def test_load_tsv_missing_file_returns_empty_list(tmp_path):
    assert load_tsv(tmp_path / "does_not_exist.tsv") == []


def test_load_existing_overview_missing_file_returns_empty_list(tmp_path):
    assert load_existing_overview(tmp_path / "does_not_exist.csv") == []


def test_main_end_to_end(tmp_path, monkeypatch, capsys):
    import argparse

    catalog_path = tmp_path / "adc_asset_universe.tsv"
    candidates_path = tmp_path / "adc_candidates.tsv"
    output_path = tmp_path / "adc_drug_overview.csv"
    pd.DataFrame([_catalog_row(asset_id="NAR_A1", evidence_ids="A1; ADC_CANDIDATE_FOO")]).to_csv(catalog_path, sep="\t", index=False)
    pd.DataFrame([_candidate_row()]).to_csv(candidates_path, sep="\t", index=False)

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_adc_drug_overview.py",
            "--catalog-file", str(catalog_path),
            "--candidates-file", str(candidates_path),
            "--output", str(output_path),
        ],
    )
    rc = overview_main()
    assert rc == 0
    assert output_path.exists()
    df = pd.read_csv(output_path)
    assert df.iloc[0]["payload"] == "MMAE"
    captured = capsys.readouterr()
    assert "1 total rows" in captured.err
