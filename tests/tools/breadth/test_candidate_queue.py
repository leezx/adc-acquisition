from tools.breadth.candidate_queue import (
    find_suffix_matches,
    known_identifier_set,
    mentions_known_asset,
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
