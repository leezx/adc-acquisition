from pathlib import Path

import pandas as pd

from adc_acquisition.company_registry import Company
from tools.validation.company_registry_gap_analysis import (
    build_company_universe_rows,
    build_gap_rows,
    load_phase1_plus_company_mentions,
    registered_identifier_index,
)


def _write_catalog(tmp_path, rows):
    path = tmp_path / "catalog.tsv"
    df = pd.DataFrame(rows)
    df.to_csv(path, sep="\t", index=False)
    return path


def test_load_phase1_plus_company_mentions_ignores_reference_unclassified_rows(tmp_path):
    path = _write_catalog(tmp_path, [
        {"canonical_name": "Foo ADC", "company": "Acme Pharma", "highest_stage": "Phase1"},
        {"canonical_name": "Bar ADC", "company": "Acme Pharma", "highest_stage": "Investigative"},
    ])
    mentions = load_phase1_plus_company_mentions(path)
    assert mentions["Acme Pharma"]["count"] == 1  # only the Phase1 row counts
    assert mentions["Acme Pharma"]["examples"] == ["Foo ADC"]


def test_load_phase1_plus_company_mentions_splits_multi_sponsor_rows(tmp_path):
    path = _write_catalog(tmp_path, [
        {"canonical_name": "Foo ADC", "company": "Acme Pharma; Beta Bio", "highest_stage": "Phase2"},
    ])
    mentions = load_phase1_plus_company_mentions(path)
    assert set(mentions) == {"Acme Pharma", "Beta Bio"}
    assert mentions["Acme Pharma"]["count"] == 1
    assert mentions["Beta Bio"]["count"] == 1


def test_registered_identifier_index_matches_canonical_name_and_aliases():
    companies = [Company(company_id="acme", canonical_name="Acme Pharma, Inc.", aliases=["Acme Bio"])]
    index = registered_identifier_index(companies)
    assert index["acmepharmainc"] == "acme"
    assert index["acmebio"] == "acme"


def test_build_gap_rows_flags_unregistered_company():
    mentions = {"Acme Pharma": {"count": 3, "examples": ["Foo ADC"], "stages": ["Phase1"] * 3}}
    rows = build_gap_rows(mentions, registry_index={})
    assert rows[0]["company_name"] == "Acme Pharma"
    assert rows[0]["in_registry"] is False
    assert rows[0]["phase1_plus_asset_count"] == 3


def test_build_gap_rows_flags_registered_company():
    mentions = {"Acme Pharma, Inc.": {"count": 1, "examples": ["Foo ADC"], "stages": ["Phase1"]}}
    registry_index = {"acmepharmainc": "acme"}
    rows = build_gap_rows(mentions, registry_index)
    assert rows[0]["in_registry"] is True
    assert rows[0]["matched_company_id"] == "acme"


def test_build_company_universe_rows_registered_with_urls():
    companies = [Company(
        company_id="acme", canonical_name="Acme Pharma, Inc.",
        official_domain="acme.com", pipeline_urls=["https://acme.com/pipeline"],
    )]
    mentions = {"Acme Pharma, Inc.": {"count": 2, "examples": ["Foo ADC"], "stages": ["Phase1", "Phase2"]}}
    rows = build_company_universe_rows(mentions, companies, run_date="2026-08-28")
    assert len(rows) == 1
    row = rows[0]
    assert row["registry_status"] == "REGISTERED"
    assert row["active_adc_count"] == 2
    assert row["highest_active_stage"] == "Phase2"  # more advanced than Phase1
    assert row["last_verified"] == "2026-08-28"


def test_build_company_universe_rows_registered_incomplete_without_urls():
    companies = [Company(company_id="acme", canonical_name="Acme Pharma, Inc.")]
    rows = build_company_universe_rows({}, companies, run_date="2026-08-28")
    assert rows[0]["registry_status"] == "REGISTERED_INCOMPLETE"


def test_build_company_universe_rows_unregistered_active_company():
    mentions = {"Beta Bio": {"count": 1, "examples": ["Bar ADC"], "stages": ["Phase3"]}}
    rows = build_company_universe_rows(mentions, companies=[], run_date="2026-08-28")
    assert rows[0]["registry_status"] == "UNREGISTERED_ACTIVE_ADC_COMPANY"
    assert rows[0]["company_id"] == ""
    assert rows[0]["last_verified"] == ""  # never verified, honestly blank not fabricated
    assert rows[0]["evidence_source"] == "master_catalog"


def test_build_company_universe_rows_includes_parent_company_id():
    companies = [Company(company_id="sub", canonical_name="Sub Co.", parent_company_id="parent")]
    rows = build_company_universe_rows({}, companies, run_date="2026-08-28")
    assert rows[0]["parent_company"] == "parent"


def test_build_company_universe_rows_sorts_unregistered_first_by_asset_count():
    companies = [Company(company_id="acme", canonical_name="Acme Pharma, Inc.",
                          official_domain="acme.com", pipeline_urls=["https://acme.com/pipeline"])]
    mentions = {
        "Acme Pharma, Inc.": {"count": 1, "examples": ["Foo"], "stages": ["Phase1"]},
        "Beta Bio": {"count": 5, "examples": ["Bar"], "stages": ["Phase3"]},
    }
    rows = build_company_universe_rows(mentions, companies, run_date="2026-08-28")
    assert rows[0]["canonical_name"] == "Beta Bio"  # unregistered, highest count -- surfaced first
    assert rows[0]["registry_status"] == "UNREGISTERED_ACTIVE_ADC_COMPANY"


def test_build_company_universe_rows_matches_via_alias_not_only_canonical_name():
    # Regression: an earlier version only checked normalize_name(canonical_name),
    # silently missing a company whose catalog mentions use an alias form --
    # found while adding aliases for the 2026-08-28 source-coverage expansion.
    companies = [Company(company_id="acme", canonical_name="Acme Pharma, Inc.",
                          aliases=["Acme Pharma Co"],
                          official_domain="acme.com", pipeline_urls=["https://acme.com/pipeline"])]
    mentions = {"Acme Pharma Co": {"count": 3, "examples": ["Foo"], "stages": ["Phase2"]}}
    rows = build_company_universe_rows(mentions, companies, run_date="2026-08-28")
    assert len(rows) == 1  # the alias-form mention must NOT also surface as a separate unregistered row
    assert rows[0]["registry_status"] == "REGISTERED"
    assert rows[0]["active_adc_count"] == 3


def test_build_company_universe_rows_aggregates_counts_across_multiple_alias_mentions():
    companies = [Company(company_id="acme", canonical_name="Acme Pharma, Inc.",
                          aliases=["Acme Pharma Co"],
                          official_domain="acme.com", pipeline_urls=["https://acme.com/pipeline"])]
    mentions = {
        "Acme Pharma, Inc.": {"count": 2, "examples": ["Foo"], "stages": ["Phase1"]},
        "Acme Pharma Co": {"count": 3, "examples": ["Bar"], "stages": ["Phase3"]},
    }
    rows = build_company_universe_rows(mentions, companies, run_date="2026-08-28")
    assert len(rows) == 1
    assert rows[0]["active_adc_count"] == 5  # summed across both mention-name variants
    assert rows[0]["highest_active_stage"] == "Phase3"  # more advanced of the two variants' stages
