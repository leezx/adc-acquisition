import pytest
import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.clinicaltrials.client import CTGOV_BASE, ClinicalTrialsClient


@pytest.fixture
def client():
    return ClinicalTrialsClient(RetryingClient(RateLimiter(1000)))


@responses.activate
def test_search_sends_expected_params_and_parses_result(client):
    responses.add(
        responses.GET,
        f"{CTGOV_BASE}/studies",
        json={"studies": [{"id": "1"}], "nextPageToken": "tok123", "totalCount": 5},
    )
    page = client.search('"antibody-drug conjugate"')
    assert page.total_count == 5
    assert page.next_page_token == "tok123"
    assert len(page.studies) == 1

    request = responses.calls[0].request
    assert "query.term=" in request.url
    assert "countTotal=true" in request.url
    assert "format=json" in request.url


@responses.activate
def test_search_omits_page_token_on_first_call(client):
    responses.add(responses.GET, f"{CTGOV_BASE}/studies", json={"studies": []})
    client.search("x")
    assert "pageToken" not in responses.calls[0].request.url


@responses.activate
def test_search_includes_page_token_on_subsequent_call(client):
    responses.add(responses.GET, f"{CTGOV_BASE}/studies", json={"studies": []})
    client.search("x", page_token="abc")
    assert "pageToken=abc" in responses.calls[0].request.url


@responses.activate
def test_search_missing_next_page_token_means_no_more_pages(client):
    responses.add(responses.GET, f"{CTGOV_BASE}/studies", json={"studies": [{"id": "1"}]})
    page = client.search("x")
    assert page.next_page_token is None


@responses.activate
def test_search_adds_date_filter_when_since_or_until_set(client):
    responses.add(responses.GET, f"{CTGOV_BASE}/studies", json={"studies": []})
    client.search("x", since="2024-01-01", until="2024-12-31")
    request = responses.calls[0].request
    assert "filter.advanced=AREA%5BLastUpdatePostDate%5DRANGE%5B2024-01-01%2C2024-12-31%5D" in request.url


@responses.activate
def test_search_date_filter_uses_min_max_for_open_bound(client):
    responses.add(responses.GET, f"{CTGOV_BASE}/studies", json={"studies": []})
    client.search("x", since="2024-01-01")
    request = responses.calls[0].request
    assert "RANGE%5B2024-01-01%2CMAX%5D" in request.url


@responses.activate
def test_search_no_date_filter_when_neither_set(client):
    responses.add(responses.GET, f"{CTGOV_BASE}/studies", json={"studies": []})
    client.search("x")
    assert "filter.advanced" not in responses.calls[0].request.url


@responses.activate
def test_search_by_intervention_uses_query_intr(client):
    responses.add(responses.GET, f"{CTGOV_BASE}/studies", json={"studies": []})
    client.search_by_intervention("trastuzumab deruxtecan")
    request = responses.calls[0].request
    assert "query.intr=" in request.url
    assert "query.term=" not in request.url
