import pandas as pd

from tools.breadth.candidate_queue import (
    build_conference_suffix_candidates,
    extract_adc_generic_name,
    extract_all_adc_generic_names_from_text,
    find_suffix_matches,
    known_identifier_set,
    mentions_known_asset,
    merge_suffix_candidates,
    normalize_name,
)


def test_find_suffix_matches_recognizes_documented_stem():
    assert find_suffix_matches("Ladiratuzumab vedotin") == "vedotin"
    assert find_suffix_matches("Depatuxizumab mafodotin") == "mafodotin"


def test_find_suffix_matches_returns_none_for_unrelated_name():
    assert find_suffix_matches("Pembrolizumab") is None
    assert find_suffix_matches("vedotin") is None  # bare suffix, not a real drug name with a stem prefix


def test_mentions_known_asset_catches_combination_regimen_strings():
    known = known_identifier_set([{"asset_id": "x", "canonical_name": "Enfortumab vedotin", "aliases": [], "dev_codes": []}])
    assert mentions_known_asset("Pembrolizumab + Enfortumab Vedotin", known)
    assert mentions_known_asset("Arm A: Belantamab Mafodotin", known_identifier_set(
        [{"asset_id": "y", "canonical_name": "Belantamab mafodotin", "aliases": [], "dev_codes": []}]
    ))


def test_mentions_known_asset_false_for_genuinely_new_name():
    known = known_identifier_set([{"asset_id": "x", "canonical_name": "Enfortumab vedotin", "aliases": [], "dev_codes": []}])
    assert not mentions_known_asset("Ladiratuzumab vedotin", known)


def test_normalize_name_strips_punctuation_and_case():
    assert normalize_name("Trastuzumab-Emtansine") == normalize_name("trastuzumab emtansine")


def test_extract_adc_generic_name_strips_combination_regimen_partner():
    assert extract_adc_generic_name("Pembrolizumab + Ladiratuzumab vedotin") == "Ladiratuzumab vedotin"


def test_extract_adc_generic_name_strips_trial_arm_label():
    assert extract_adc_generic_name("Arm A: Ladiratuzumab vedotin") == "Ladiratuzumab vedotin"


def test_extract_adc_generic_name_strips_radiolabel_prefix():
    assert extract_adc_generic_name("89Zr-Patritumab deruxtecan") == "Patritumab deruxtecan"


def test_extract_adc_generic_name_strips_trailing_parenthetical_abbreviation():
    """A real case found in clinicaltrials.parquet: the naive whole-string
    endswith() check missed these entirely because the suffix word isn't
    at the very end of the raw string."""
    assert extract_adc_generic_name("Labetuzumab Govitecan (LG)") == "Labetuzumab Govitecan"
    assert extract_adc_generic_name("Enapotamab vedotin (HuMax-AXL-ADC)") == "Enapotamab vedotin"


def test_extract_adc_generic_name_returns_none_for_bare_suffix_or_no_suffix():
    assert extract_adc_generic_name("Vedotin") is None
    assert extract_adc_generic_name("Pembrolizumab") is None


def test_extract_all_adc_generic_names_from_text_finds_multiple_distinct_names():
    text = "A comparison of Trastuzumab deruxtecan and Sacituzumab govitecan in breast cancer."
    names = extract_all_adc_generic_names_from_text(text)
    assert set(n.lower() for n in names) == {"trastuzumab deruxtecan", "sacituzumab govitecan"}


def test_extract_all_adc_generic_names_from_text_excludes_stopword_prefixes():
    # Real false-positive patterns observed scanning the actual conference
    # abstract corpus: a common English word directly before the suffix
    # word, not a real antibody-name stem.
    text = "This novel vedotin conjugate and the deruxtecan arm showed activity."
    assert extract_all_adc_generic_names_from_text(text) == []


def test_extract_all_adc_generic_names_from_text_deduplicates_repeated_mentions():
    text = "Trastuzumab deruxtecan was studied. Later, trastuzumab deruxtecan showed responses."
    names = extract_all_adc_generic_names_from_text(text)
    assert len(names) == 1


def test_build_conference_suffix_candidates_suppresses_known_asset():
    known = known_identifier_set([{"asset_id": "x", "canonical_name": "Trastuzumab deruxtecan", "aliases": [], "dev_codes": []}])
    manifest = pd.DataFrame([
        dict(source_record_id="10.1/1", title="A study of Trastuzumab deruxtecan", abstract=None, publication_or_release_date="2020-01-01"),
    ])
    assert build_conference_suffix_candidates(manifest, known) == {}


def test_build_conference_suffix_candidates_surfaces_genuinely_new_name():
    known = known_identifier_set([{"asset_id": "x", "canonical_name": "Trastuzumab deruxtecan", "aliases": [], "dev_codes": []}])
    manifest = pd.DataFrame([
        dict(source_record_id="10.1/1", title="A study of Mecbotamab vedotin in AXL-positive tumors", abstract=None, publication_or_release_date="2020-01-01"),
    ])
    candidates = build_conference_suffix_candidates(manifest, known)
    assert len(candidates) == 1
    entry = next(iter(candidates.values()))
    assert entry["label"] == "Mecbotamab vedotin"
    assert entry["sources"] == {"conference_abstract_corpus"}
    assert entry["conference_ids"] == {"10.1/1"}


def test_merge_suffix_candidates_combines_sources_for_same_name():
    ct = {"mecbotamabvedotin": dict(label="Mecbotamab vedotin", suffix="vedotin", nct_ids={"NCT1"},
                                     conference_ids=set(), phases=set(), first_seen="2021-01-01",
                                     contexts={"a trial"}, sources={"clinicaltrials"})}
    conf = {"mecbotamabvedotin": dict(label="Mecbotamab vedotin", suffix="vedotin", nct_ids=set(),
                                       conference_ids={"10.1/1"}, phases=set(), first_seen="2020-01-01",
                                       contexts={"an abstract"}, sources={"conference_abstract_corpus"})}
    merged = merge_suffix_candidates(ct, conf)
    assert len(merged) == 1
    entry = merged["mecbotamabvedotin"]
    assert entry["sources"] == {"clinicaltrials", "conference_abstract_corpus"}
    assert entry["nct_ids"] == {"NCT1"}
    assert entry["conference_ids"] == {"10.1/1"}
    assert entry["first_seen"] == "2020-01-01"  # earliest of the two


def test_merge_suffix_candidates_keeps_distinct_names_separate():
    ct = {"a": dict(label="A vedotin", suffix="vedotin", nct_ids={"NCT1"}, conference_ids=set(),
                     phases=set(), first_seen=None, contexts=set(), sources={"clinicaltrials"})}
    conf = {"b": dict(label="B vedotin", suffix="vedotin", nct_ids=set(), conference_ids={"10.1/2"},
                       phases=set(), first_seen=None, contexts=set(), sources={"conference_abstract_corpus"})}
    merged = merge_suffix_candidates(ct, conf)
    assert set(merged.keys()) == {"a", "b"}
