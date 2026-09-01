import json

import pytest
import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.pubmed.client import EUTILS_BASE, PubMedClient


@pytest.fixture
def client():
    http_client = RetryingClient(RateLimiter(1000))
    return PubMedClient(http_client, api_key="test-key", tool="adc-acquisition", email="a@b.test")


@responses.activate
def test_esearch_sends_expected_params_and_parses_result(client):
    responses.add(
        responses.GET,
        f"{EUTILS_BASE}/esearch.fcgi",
        json={"esearchresult": {"count": "2", "retmax": "200", "retstart": "0", "idlist": ["1", "2"]}},
        status=200,
    )
    result = client.esearch(term='"antibody-drug conjugate"[tiab]', retstart=0, retmax=200)
    assert result.count == 2
    assert result.idlist == ["1", "2"]

    request = responses.calls[0].request
    assert "db=pubmed" in request.url
    assert "api_key=test-key" in request.url
    assert "tool=adc-acquisition" in request.url


@responses.activate
def test_esearch_always_sorts_by_publication_date_descending(client):
    """Reviewer-flagged (round-1): NCBI ESearch defaults to relevance
    ordering, not date -- for a query truncated at the 9,999-record
    retstart ceiling (see jobs/pubmed/job.py), the retained records must
    be deterministically the NEWEST ones, or a just-published paper could
    land permanently in the unreachable tail."""
    responses.add(
        responses.GET,
        f"{EUTILS_BASE}/esearch.fcgi",
        json={"esearchresult": {"count": "0", "retmax": "200", "retstart": "0", "idlist": []}},
        status=200,
    )
    client.esearch(term="x")
    request = responses.calls[0].request
    assert "sort=pub_date" in request.url


@responses.activate
def test_esearch_adds_date_range_params(client):
    responses.add(
        responses.GET,
        f"{EUTILS_BASE}/esearch.fcgi",
        json={"esearchresult": {"count": "0", "retmax": "200", "retstart": "0", "idlist": []}},
        status=200,
    )
    client.esearch(term="x", mindate="2020/01/01", maxdate="2021/01/01")
    request = responses.calls[0].request
    assert "mindate=2020%2F01%2F01" in request.url
    assert "maxdate=2021%2F01%2F01" in request.url
    assert "datetype=pdat" in request.url


@responses.activate
def test_esearch_raises_on_ncbi_error_payload(client):
    responses.add(
        responses.GET,
        f"{EUTILS_BASE}/esearch.fcgi",
        json={"esearchresult": {"ERROR": "Invalid db name specified"}},
        status=200,
    )
    with pytest.raises(RuntimeError, match="Invalid db name"):
        client.esearch(term="x")


@responses.activate
def test_efetch_posts_id_list(client):
    responses.add(
        responses.POST,
        f"{EUTILS_BASE}/efetch.fcgi",
        body=b"<PubmedArticleSet></PubmedArticleSet>",
        status=200,
    )
    raw = client.efetch_raw_xml(["1", "2", "3"])
    assert raw == b"<PubmedArticleSet></PubmedArticleSet>"
    request = responses.calls[0].request
    assert request.method == "POST"
    assert "id=1%2C2%2C3" in request.body or "1,2,3" in request.body


def test_efetch_empty_id_list_returns_empty_bytes_without_request(client):
    assert client.efetch_raw_xml([]) == b""
