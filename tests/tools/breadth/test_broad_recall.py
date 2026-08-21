from tools.breadth.broad_recall import classify_broad_discovery
from tools.validation.compare_nar_adcdb import NARAsset


def _asset(**overrides) -> NARAsset:
    defaults = dict(
        adc_id="DRG_TEST", name="Test ADC", status="Investigative",
        antibody_name_inv="", payload_name_inv="", linker_name_inv="",
        representative_indication_inv="",
    )
    defaults.update(overrides)
    return NARAsset(**defaults)


def test_strong_identifier_nct_match_confirms_broad_discovered_with_no_text_evidence():
    """An exact NCT-number match needs no materialized text at all -- this
    must confirm BROAD_DISCOVERED even when every text-based manifest/raw
    lookup is empty."""
    asset = _asset(nct_ids=["NCT99999999"])
    result = classify_broad_discovery(asset, broad_manifests={}, raw_text_cache={}, broad_nct_ids={"NCT99999999"})
    assert result["status"] == "BROAD_DISCOVERED"
    assert result["match_basis"] == "STRONG_IDENTIFIER_NCT"
    assert result["confidence"] == "high"
    assert "NCT99999999" in result["matching_evidence_ids"]


def test_no_nct_overlap_stays_not_confirmed_broad():
    asset = _asset(nct_ids=["NCT11111111"])
    result = classify_broad_discovery(asset, broad_manifests={}, raw_text_cache={}, broad_nct_ids={"NCT99999999"})
    assert result["status"] == "NOT_CONFIRMED_BROAD"


def test_missing_broad_nct_ids_argument_does_not_crash():
    asset = _asset(nct_ids=["NCT99999999"])
    result = classify_broad_discovery(asset, broad_manifests={}, raw_text_cache={})
    assert result["status"] == "NOT_CONFIRMED_BROAD"
