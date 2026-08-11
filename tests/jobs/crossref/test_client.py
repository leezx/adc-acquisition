import pytest
import requests
import responses

from adc_acquisition import http_utils
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.crossref.client import CROSSREF_BASE, CrossrefClient


@pytest.fixture
def client():
    return CrossrefClient(RetryingClient(RateLimiter(1000)))


@responses.activate
def test_get_work_returns_message_on_success(client):
    responses.add(
        responses.GET,
        f"{CROSSREF_BASE}/works/10.1000/xyz",
        json={"status": "ok", "message": {"DOI": "10.1000/xyz", "title": ["A Title"]}},
    )
    message = client.get_work("10.1000/xyz")
    assert message == {"DOI": "10.1000/xyz", "title": ["A Title"]}


@responses.activate
def test_get_work_returns_none_on_404(client):
    responses.add(responses.GET, f"{CROSSREF_BASE}/works/10.1000/missing", status=404)
    assert client.get_work("10.1000/missing") is None


@responses.activate
def test_get_work_raises_on_server_error_after_retries(client, monkeypatch):
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)
    for _ in range(5):
        responses.add(responses.GET, f"{CROSSREF_BASE}/works/10.1000/broken", status=500)
    with pytest.raises(requests.HTTPError):
        client.get_work("10.1000/broken")


@responses.activate
def test_get_work_includes_mailto_when_configured():
    client = CrossrefClient(RetryingClient(RateLimiter(1000)), mailto="test@example.com")
    responses.add(responses.GET, f"{CROSSREF_BASE}/works/10.1000/xyz", json={"message": {"DOI": "10.1000/xyz"}})
    client.get_work("10.1000/xyz")
    assert "mailto=test%40example.com" in responses.calls[0].request.url


@responses.activate
def test_get_work_omits_mailto_when_not_configured(client):
    responses.add(responses.GET, f"{CROSSREF_BASE}/works/10.1000/xyz", json={"message": {"DOI": "10.1000/xyz"}})
    client.get_work("10.1000/xyz")
    assert "mailto" not in responses.calls[0].request.url
