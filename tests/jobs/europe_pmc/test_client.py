import pytest
import requests
import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.europe_pmc.client import EUROPEPMC_BASE, EuropePMCClient


@pytest.fixture
def client():
    return EuropePMCClient(RetryingClient(RateLimiter(1000)))


@responses.activate
def test_search_parses_hit_count_and_results(client):
    responses.add(
        responses.GET,
        f"{EUROPEPMC_BASE}/search",
        json={"hitCount": 2, "nextCursorMark": "AB==", "resultList": {"result": [{"id": "1", "source": "MED"}, {"id": "2", "source": "MED"}]}},
    )
    page = client.search('"antibody-drug conjugate"')
    assert page.hit_count == 2
    assert len(page.results) == 2
    assert page.next_cursor_mark == "AB=="

    request = responses.calls[0].request
    assert "resultType=core" in request.url
    assert "cursorMark=%2A" in request.url


@responses.activate
def test_search_treats_repeated_cursor_mark_as_end_of_results(client):
    responses.add(
        responses.GET,
        f"{EUROPEPMC_BASE}/search",
        json={"hitCount": 1, "nextCursorMark": "SAME==", "resultList": {"result": [{"id": "1", "source": "MED"}]}},
    )
    page = client.search("x", cursor_mark="SAME==")
    assert page.next_cursor_mark is None  # would otherwise loop forever


@responses.activate
def test_search_handles_missing_next_cursor_mark(client):
    responses.add(
        responses.GET,
        f"{EUROPEPMC_BASE}/search",
        json={"hitCount": 0, "resultList": {"result": []}},
    )
    page = client.search("x")
    assert page.next_cursor_mark is None
    assert page.results == []


@responses.activate
def test_fetch_fulltext_xml_returns_bytes(client):
    responses.add(responses.GET, f"{EUROPEPMC_BASE}/PMC123/fullTextXML", body=b"<article/>", status=200)
    assert client.fetch_fulltext_xml("PMC123") == b"<article/>"


@responses.activate
def test_fetch_fulltext_xml_raises_on_404(client):
    responses.add(responses.GET, f"{EUROPEPMC_BASE}/PMC999/fullTextXML", status=404)
    with pytest.raises(requests.HTTPError):
        client.fetch_fulltext_xml("PMC999")
