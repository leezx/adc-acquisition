import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.fda.client import DRUG_LABEL_URL, DRUGSFDA_URL, FDAClient


def _client():
    return FDAClient(RetryingClient(RateLimiter(1000)), api_key=None)


@responses.activate
def test_search_label_returns_results():
    responses.add(responses.GET, DRUG_LABEL_URL, json={"results": [{"openfda": {"application_number": ["BLA1"]}}]})
    results = _client().search_label('mechanism_of_action:"antibody-drug conjugate"')
    assert results == [{"openfda": {"application_number": ["BLA1"]}}]


@responses.activate
def test_search_label_404_no_match_returns_empty_list():
    """openFDA returns HTTP 404 (with a structured error body) for a
    genuine no-match -- verified live -- which must not be raised as a
    fetch failure."""
    responses.add(responses.GET, DRUG_LABEL_URL, json={"error": {"code": "NOT_FOUND"}}, status=404)
    assert _client().search_label("no such phrase") == []


@responses.activate
def test_search_label_passes_api_key_when_configured():
    responses.add(responses.GET, DRUG_LABEL_URL, json={"results": []})
    FDAClient(RetryingClient(RateLimiter(1000)), api_key="secret123").search_label("x")
    assert responses.calls[0].request.params["api_key"] == "secret123"


@responses.activate
def test_get_drugsfda_by_application_returns_first_result():
    responses.add(responses.GET, DRUGSFDA_URL, json={"results": [{"application_number": "BLA1"}]})
    record = _client().get_drugsfda_by_application("BLA1")
    assert record == {"application_number": "BLA1"}
    assert 'application_number:"BLA1"' in responses.calls[0].request.params["search"]


@responses.activate
def test_get_drugsfda_by_application_404_returns_none():
    responses.add(responses.GET, DRUGSFDA_URL, json={"error": {"code": "NOT_FOUND"}}, status=404)
    assert _client().get_drugsfda_by_application("BLA-NOT-REAL") is None


@responses.activate
def test_fetch_document_returns_bytes():
    responses.add(responses.GET, "https://www.accessdata.fda.gov/drugsatfda_docs/label/2023/x.pdf", body=b"%PDF-1.4 fake")
    content = _client().fetch_document("https://www.accessdata.fda.gov/drugsatfda_docs/label/2023/x.pdf")
    assert content == b"%PDF-1.4 fake"
