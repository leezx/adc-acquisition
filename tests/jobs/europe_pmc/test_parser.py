from jobs.europe_pmc.parser import parse_search_result

FULL_RESULT = {
    "id": "12345",
    "source": "MED",
    "pmid": "12345",
    "pmcid": "PMC999",
    "doi": "10.1000/xyz",
    "title": "An ADC Study",
    "abstractText": "Background text.",
    "firstPublicationDate": "2021-03-05",
    "pubYear": "2021",
    "journalInfo": {"journal": {"title": "Journal of Testing"}, "printPublicationDate": "2021-03-01"},
    "isOpenAccess": "Y",
    "inPMC": "Y",
    "license": "cc by",
}


def test_parses_full_result():
    parsed = parse_search_result(FULL_RESULT)
    assert parsed.epmc_source == "MED"
    assert parsed.epmc_id == "12345"
    assert parsed.pmid == "12345"
    assert parsed.pmcid == "PMC999"
    assert parsed.doi == "10.1000/xyz"
    assert parsed.title == "An ADC Study"
    assert parsed.abstract == "Background text."
    assert parsed.journal == "Journal of Testing"
    assert parsed.publication_date == "2021-03-05"  # firstPublicationDate wins
    assert parsed.is_open_access is True
    assert parsed.in_pmc is True
    assert parsed.license == "cc by"


def test_missing_source_or_id_returns_none():
    assert parse_search_result({"id": "1"}) is None
    assert parse_search_result({"source": "MED"}) is None
    assert parse_search_result({}) is None


def test_minimal_result_has_none_for_missing_optional_fields():
    parsed = parse_search_result({"id": "1", "source": "PPR"})
    assert parsed.pmid is None
    assert parsed.pmcid is None
    assert parsed.doi is None
    assert parsed.abstract is None
    assert parsed.journal is None
    assert parsed.publication_date is None
    assert parsed.is_open_access is False
    assert parsed.in_pmc is False
    assert parsed.license is None


def test_publication_date_falls_back_to_print_publication_date():
    result = dict(FULL_RESULT)
    del result["firstPublicationDate"]
    parsed = parse_search_result(result)
    assert parsed.publication_date == "2021-03-01"


def test_publication_date_falls_back_to_pub_year():
    result = dict(FULL_RESULT)
    del result["firstPublicationDate"]
    result["journalInfo"] = {}
    parsed = parse_search_result(result)
    assert parsed.publication_date == "2021"


def test_is_open_access_false_for_any_non_y_value():
    result = dict(FULL_RESULT)
    result["isOpenAccess"] = "N"
    assert parse_search_result(result).is_open_access is False
