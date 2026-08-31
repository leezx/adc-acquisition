import pytest
import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.conference_crossref_search.client import CROSSREF_BASE, CrossrefSearchClient


@pytest.fixture
def client():
    return CrossrefSearchClient(RetryingClient(RateLimiter(1000)))


@responses.activate
def test_search_returns_items_total_and_next_cursor(client):
    responses.add(
        responses.GET,
        f"{CROSSREF_BASE}/works",
        json={
            "message": {
                "total-results": 2,
                "items": [{"DOI": "10.1/a"}, {"DOI": "10.1/b"}],
                "next-cursor": "cursor2",
            }
        },
    )
    page = client.search(query_bibliographic="ADC", filters=["issn:0006-4971"], cursor="*")
    assert page.total_results == 2
    assert [i["DOI"] for i in page.items] == ["10.1/a", "10.1/b"]
    assert page.next_cursor == "cursor2"


@responses.activate
def test_search_treats_repeated_cursor_as_exhausted(client):
    responses.add(
        responses.GET,
        f"{CROSSREF_BASE}/works",
        json={"message": {"total-results": 0, "items": [], "next-cursor": "*"}},
    )
    page = client.search(query_bibliographic="ADC", filters=["issn:0006-4971"], cursor="*")
    assert page.next_cursor is None


@responses.activate
def test_search_joins_multiple_filters_with_comma(client):
    responses.add(responses.GET, f"{CROSSREF_BASE}/works", json={"message": {"items": []}})
    client.search(query_bibliographic="ADC", filters=["issn:0006-4971", "from-pub-date:2026-01-01"], cursor="*")
    url = responses.calls[0].request.url
    assert "filter=issn%3A0006-4971%2Cfrom-pub-date%3A2026-01-01" in url


@responses.activate
def test_search_includes_mailto_when_configured():
    client = CrossrefSearchClient(RetryingClient(RateLimiter(1000)), mailto="test@example.com")
    responses.add(responses.GET, f"{CROSSREF_BASE}/works", json={"message": {"items": []}})
    client.search(query_bibliographic="ADC", filters=["issn:0006-4971"], cursor="*")
    assert "mailto=test%40example.com" in responses.calls[0].request.url


@responses.activate
def test_search_omits_mailto_when_not_configured(client):
    responses.add(responses.GET, f"{CROSSREF_BASE}/works", json={"message": {"items": []}})
    client.search(query_bibliographic="ADC", filters=["issn:0006-4971"], cursor="*")
    assert "mailto" not in responses.calls[0].request.url
