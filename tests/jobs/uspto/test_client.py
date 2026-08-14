import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.uspto.client import USPTO_API_BASE, SEARCH_URL, USPTOClient


def _client():
    return USPTOClient(RetryingClient(RateLimiter(1000)), api_key="test-key")


@responses.activate
def test_search_sends_api_key_header_and_parses_results():
    responses.add(
        responses.GET, SEARCH_URL,
        json={"count": 2, "patentFileWrapperDataBag": [{"applicationNumberText": "111"}, {"applicationNumberText": "222"}]},
    )
    ids, total = _client().search("antibody", 100, 0)
    assert ids == ["111", "222"]
    assert total == 2
    assert responses.calls[0].request.headers["X-API-KEY"] == "test-key"


@responses.activate
def test_search_404_returns_empty_page():
    responses.add(responses.GET, SEARCH_URL, status=404, json={"code": "404", "message": "Not Found"})
    ids, total = _client().search("antibody", 100, 99999)
    assert ids == []
    assert total == 0


@responses.activate
def test_get_application_returns_full_record():
    responses.add(responses.GET, f"{USPTO_API_BASE}/12345", json={"patentFileWrapperDataBag": [{"applicationNumberText": "12345", "foo": "bar"}]})
    record = _client().get_application("12345")
    assert record == {"applicationNumberText": "12345", "foo": "bar"}


@responses.activate
def test_get_application_404_returns_none():
    responses.add(responses.GET, f"{USPTO_API_BASE}/99999", status=404, json={"code": "404"})
    assert _client().get_application("99999") is None


@responses.activate
def test_list_documents_returns_document_bag():
    responses.add(responses.GET, f"{USPTO_API_BASE}/12345/documents", json={"count": 1, "documentBag": [{"documentCode": "SPEC"}]})
    docs = _client().list_documents("12345")
    assert docs == [{"documentCode": "SPEC"}]


@responses.activate
def test_list_documents_404_returns_empty_list():
    responses.add(responses.GET, f"{USPTO_API_BASE}/12345/documents", status=404, json={"code": "404"})
    assert _client().list_documents("12345") == []


@responses.activate
def test_fetch_document_returns_raw_bytes():
    url = "https://api.uspto.gov/api/v1/download/applications/12345/ABC.pdf"
    responses.add(responses.GET, url, body=b"%PDF-1.4 fake pdf")
    assert _client().fetch_document(url) == b"%PDF-1.4 fake pdf"
