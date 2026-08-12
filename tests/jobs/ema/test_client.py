import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.ema.client import EMA_MEDICINES_XLSX_URL, EMAClient


def _client():
    return EMAClient(RetryingClient(RateLimiter(1000)))


@responses.activate
def test_fetch_medicines_xlsx_returns_bytes():
    responses.add(responses.GET, EMA_MEDICINES_XLSX_URL, body=b"fake-xlsx-bytes")
    content = _client().fetch_medicines_xlsx()
    assert content == b"fake-xlsx-bytes"
    assert "User-Agent" in responses.calls[0].request.headers


@responses.activate
def test_fetch_epar_page_returns_text():
    responses.add(responses.GET, "https://www.ema.europa.eu/en/medicines/human/EPAR/adcetris", body="<html>epar</html>")
    text = _client().fetch_epar_page("https://www.ema.europa.eu/en/medicines/human/EPAR/adcetris")
    assert text == "<html>epar</html>"


@responses.activate
def test_fetch_document_returns_bytes():
    responses.add(responses.GET, "https://www.ema.europa.eu/en/documents/x.pdf", body=b"%PDF fake")
    content = _client().fetch_document("https://www.ema.europa.eu/en/documents/x.pdf")
    assert content == b"%PDF fake"
