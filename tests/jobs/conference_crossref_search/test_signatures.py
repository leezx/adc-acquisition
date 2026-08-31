import pytest

from jobs.conference_crossref_search.signatures import matches_signature

# Real-shaped examples, live-verified 2026-08-31 (see configs/conference_crossref_search.yaml).

ESMO_ABSTRACT = {"DOI": "10.1016/j.annonc.2024.07.705", "page": "S1310-S1311"}  # no "issue" key at all
ESMO_REGULAR_ARTICLE = {"DOI": "10.1016/j.annonc.2026.04.008", "issue": "7", "page": "1181-1190"}

ASH_ABSTRACT = {"DOI": "10.1182/blood-2024-193278", "issue": "Supplement 1", "page": "5846-5846"}
ASH_REGULAR_ARTICLE = {"DOI": "10.1182/blood.2024024442", "issue": "2", "page": "137-144"}

EHA_2023_ABSTRACT = {"DOI": "10.1097/01.hs9.0000969100.45170.e9", "volume": "7", "issue": "S3", "page": "e45170e9"}
EHA_2024_ABSTRACT = {"DOI": "10.1097/eha2024-x", "volume": "8", "issue": "S1", "page": "1-1"}
# 2024 volume 8 issue S4 is the Annual Sickle Cell & Thalassaemia Conference, not EHA.
HEMASPHERE_2024_S4_NOT_EHA = {"DOI": "10.1097/ascat2024-x", "volume": "8", "issue": "S4", "page": "1-1"}
EHA_VOLUME_ISSUE_MAP = ["6:S3", "7:S3", "8:S1", "9:S1", "10:S1"]

SABCS_ABSTRACT = {"DOI": "10.1158/1538-7445.sabcs23-po3-05-14", "issue": "9_Supplement", "page": "PO3-05-14-PO3-05-14"}
AACR_ANNUAL_ABSTRACT = {"DOI": "10.1158/1538-7445.am2023-2012", "issue": "7_Supplement", "page": "2012-2012"}


def test_esmo_signature_accepts_supplement_abstract():
    assert matches_signature(ESMO_ABSTRACT, "no_issue_and_s_page", None) is True


def test_esmo_signature_rejects_regular_article():
    assert matches_signature(ESMO_REGULAR_ARTICLE, "no_issue_and_s_page", None) is False


def test_ash_signature_accepts_supplement_abstract():
    assert matches_signature(ASH_ABSTRACT, "issue_contains_supplement", None) is True


def test_ash_signature_rejects_regular_article():
    assert matches_signature(ASH_REGULAR_ARTICLE, "issue_contains_supplement", None) is False


def test_eha_signature_accepts_2023_eha_congress_abstract():
    assert matches_signature(EHA_2023_ABSTRACT, "volume_issue_map", EHA_VOLUME_ISSUE_MAP) is True


def test_eha_signature_accepts_2024_eha_congress_abstract():
    assert matches_signature(EHA_2024_ABSTRACT, "volume_issue_map", EHA_VOLUME_ISSUE_MAP) is True


def test_eha_signature_rejects_same_year_other_society_supplement():
    """HemaSphere 2024 volume 8 issue S4 is the Annual Sickle Cell &
    Thalassaemia Conference (ASCAT), not EHA -- the exact scenario a
    generic "issue starts with S" check would wrongly accept."""
    assert matches_signature(HEMASPHERE_2024_S4_NOT_EHA, "volume_issue_map", EHA_VOLUME_ISSUE_MAP) is False


def test_eha_signature_rejects_unmapped_future_volume_fails_closed():
    unmapped = {"DOI": "10.1097/eha2027-x", "volume": "11", "issue": "S1"}
    assert matches_signature(unmapped, "volume_issue_map", EHA_VOLUME_ISSUE_MAP) is False


def test_sabcs_signature_accepts_sabcs_doi():
    assert matches_signature(SABCS_ABSTRACT, "doi_suffix_contains", "sabcs") is True


def test_sabcs_signature_rejects_aacr_annual_abstract_in_same_journal_and_issue_shape():
    """Cancer Research carries AACR Annual Meeting AND SABCS abstracts in the
    same '_Supplement' issue shape -- only the DOI-suffix signature tells them
    apart. This is the exact scenario configs/conference_crossref_search.yaml's
    own CRITICAL note warns about."""
    assert matches_signature(AACR_ANNUAL_ABSTRACT, "doi_suffix_contains", "sabcs") is False


def test_unknown_signature_type_raises():
    with pytest.raises(ValueError, match="unknown signature_type"):
        matches_signature({}, "not_a_real_signature", None)


def test_missing_issue_and_page_fields_do_not_crash():
    assert matches_signature({"DOI": "10.1/x"}, "no_issue_and_s_page", None) is False
    assert matches_signature({"DOI": "10.1/x"}, "issue_contains_supplement", None) is False
    assert matches_signature({"DOI": "10.1/x"}, "volume_issue_map", EHA_VOLUME_ISSUE_MAP) is False
    assert matches_signature({}, "doi_suffix_contains", "sabcs") is False
