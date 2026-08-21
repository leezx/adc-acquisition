from tools.breadth.build_nar_reference_universe import build_asset_rows
from tools.validation.compare_nar_adcdb import NARAsset


def _asset(**overrides) -> NARAsset:
    defaults = dict(
        adc_id="DRG_TEST", name="Test ADC", status="Investigative",
        antibody_name_inv="", payload_name_inv="", linker_name_inv="",
        representative_indication_inv="",
    )
    defaults.update(overrides)
    return NARAsset(**defaults)


def test_antigen_name_never_falls_back_to_antibody_name():
    """ADC_TARGET (antigen) and ADC_ANTIBODY are two different entity types
    (BREADTH_PLAN.md Phase 1 ontology split) -- when the markdown page's own
    "Antigen Name" field wasn't parsed, antigen_name must stay blank, never
    silently take on the antibody's name instead."""
    asset = _asset(antibody_name_inv="trastuzumab", antigen_name_md=None)
    row = build_asset_rows([asset])[0]
    assert row["antigen_name"] == ""
    assert row["antigen_name"] != "trastuzumab"


def test_antigen_name_uses_parsed_markdown_field_when_present():
    asset = _asset(antibody_name_inv="trastuzumab", antigen_name_md="HER2")
    row = build_asset_rows([asset])[0]
    assert row["antigen_name"] == "HER2"
