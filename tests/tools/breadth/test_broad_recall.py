from pathlib import Path

from tools.breadth.broad_recall import BROAD_QUERY_CONFIGS, classify_broad_discovery, load_allowed_broad_query_ids
from tools.validation.compare_nar_adcdb import DISCOVERY_SOURCES, MANIFEST_NAMES, TEXT_COLUMNS, NARAsset

REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_conference_abstract_corpus_registered_as_a_broad_discovery_source():
    """Breadth-freeze audit (Phase 7) fix: conference_abstract_corpus
    (Phase 4) predates this being wired in nowhere -- must be present in
    every registry classify_broad_discovery's pipeline depends on, so a
    NAR asset findable only via conference abstracts is no longer
    silently invisible to Gate 1/2."""
    assert "conference_abstract_corpus" in BROAD_QUERY_CONFIGS
    assert BROAD_QUERY_CONFIGS["conference_abstract_corpus"] == "configs/conference_abstract_corpus_queries.yaml"
    assert "conference_abstract_corpus" in DISCOVERY_SOURCES
    assert "conference_abstract_corpus" in MANIFEST_NAMES
    assert TEXT_COLUMNS["conference_abstract_corpus"] == ["title", "abstract"]


def test_conference_abstract_corpus_query_config_loads_real_broad_query_ids():
    """End-to-end wiring check against the real production config -- not
    just that the registry key exists, but that it actually resolves to
    the two real, active broad-discovery query_ids."""
    allowed = load_allowed_broad_query_ids(REPO_ROOT)
    assert allowed["conference_abstract_corpus"] == {"CONFERENCE_AACR_001", "CONFERENCE_ASCO_001"}
