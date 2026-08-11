from jobs.crossref.parser import parse_work

FULL_MESSAGE = {
    "DOI": "10.1000/xyz",
    "title": ["A Study of ADCs"],
    "author": [
        {"given": "Jane", "family": "Doe"},
        {"name": "Some Consortium"},
        {"given": "No Family"},
    ],
    "publisher": "Wiley",
    "container-title": ["Journal of Testing"],
    "type": "journal-article",
    "published": {"date-parts": [[2021, 3, 5]]},
    "published-print": {"date-parts": [[2021, 3, 1]]},
    "license": [{"URL": "http://example.com/license", "content-version": "vor"}],
    "reference": [
        {"DOI": "10.2000/ref1"},
        {"unstructured": "Some citation text"},
        {"article-title": "Fallback title"},
        {},
    ],
    "URL": "https://doi.org/10.1000/xyz",
    "abstract": "<jats:p>Background text.</jats:p>",
}


def test_parses_full_message():
    parsed = parse_work(FULL_MESSAGE)
    assert parsed.doi == "10.1000/xyz"
    assert parsed.title == "A Study of ADCs"
    assert parsed.authors == ["Jane Doe", "Some Consortium", "No Family"]
    assert parsed.publisher == "Wiley"
    assert parsed.container_title == "Journal of Testing"
    assert parsed.work_type == "journal-article"
    assert parsed.published_date == "2021-03-05"  # "published" wins over "published-print"
    assert parsed.license_url == "http://example.com/license"
    assert parsed.references == ["10.2000/ref1", "Some citation text", "Fallback title"]
    assert parsed.url == "https://doi.org/10.1000/xyz"
    assert parsed.abstract == "<jats:p>Background text.</jats:p>"


def test_none_message_returns_none():
    assert parse_work(None) is None


def test_message_without_doi_returns_none():
    assert parse_work({"title": ["x"]}) is None


def test_minimal_message_has_defaults_for_missing_fields():
    parsed = parse_work({"DOI": "10.1000/minimal"})
    assert parsed.title is None
    assert parsed.authors == []
    assert parsed.publisher is None
    assert parsed.container_title is None
    assert parsed.published_date is None
    assert parsed.license_url is None
    assert parsed.references == []
    assert parsed.abstract is None


def test_published_date_falls_back_through_preference_order():
    message = {"DOI": "10.1000/x", "published-online": {"date-parts": [[2020, 7]]}}
    parsed = parse_work(message)
    assert parsed.published_date == "2020-07"


def test_published_date_year_only():
    message = {"DOI": "10.1000/x", "issued": {"date-parts": [[2019]]}}
    parsed = parse_work(message)
    assert parsed.published_date == "2019"


def test_published_date_missing_returns_none():
    message = {"DOI": "10.1000/x", "issued": {"date-parts": [[None]]}}
    assert parse_work(message).published_date is None
