import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.ema.client import EMA_EPAR_DOCUMENTS_JSON_URL, EMA_MEDICINES_JSON_URL, EMAClient


def _client():
    return EMAClient(RetryingClient(RateLimiter(1000)))


@responses.activate
def test_fetch_medicines_json_returns_bytes():
    responses.add(responses.GET, EMA_MEDICINES_JSON_URL, body=b'{"data": []}')
    content = _client().fetch_medicines_json()
    assert content == b'{"data": []}'
    assert "User-Agent" in responses.calls[0].request.headers


@responses.activate
def test_fetch_epar_documents_json_returns_bytes():
    responses.add(responses.GET, EMA_EPAR_DOCUMENTS_JSON_URL, body=b'{"data": []}')
    content = _client().fetch_epar_documents_json()
    assert content == b'{"data": []}'


@responses.activate
def test_fetch_document_returns_bytes():
    responses.add(responses.GET, "https://www.ema.europa.eu/en/documents/x.pdf", body=b"%PDF fake")
    content = _client().fetch_document("https://www.ema.europa.eu/en/documents/x.pdf")
    assert content == b"%PDF fake"
