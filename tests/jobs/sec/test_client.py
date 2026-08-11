import pytest
import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.sec.client import SEC_ARCHIVES_BASE, SEC_DATA_BASE, SECClient


@pytest.fixture
def client():
    return SECClient(RetryingClient(RateLimiter(1000)), user_agent="adc-acquisition (test@example.com)")


@responses.activate
def test_get_submissions_pads_cik_and_sends_user_agent(client):
    responses.add(responses.GET, f"{SEC_DATA_BASE}/submissions/CIK0000078003.json", json={"cik": "78003"})
    data = client.get_submissions("78003")
    assert data == {"cik": "78003"}
    request = responses.calls[0].request
    assert request.headers["User-Agent"] == "adc-acquisition (test@example.com)"


@responses.activate
def test_get_submissions_page(client):
    responses.add(responses.GET, f"{SEC_DATA_BASE}/submissions/CIK0000078003-submissions-001.json", json={"form": []})
    data = client.get_submissions_page("CIK0000078003-submissions-001.json")
    assert data == {"form": []}


@responses.activate
def test_get_filing_index_page_builds_correct_url_and_returns_html(client):
    responses.add(
        responses.GET,
        f"{SEC_ARCHIVES_BASE}/78003/000007800300000007/0000078003-00-000007-index.htm",
        body="<html>Document Format Files</html>",
    )
    html = client.get_filing_index_page("0000078003", "0000078003-00-000007")
    assert html == "<html>Document Format Files</html>"
    assert responses.calls[0].request.url.endswith(
        "/78003/000007800300000007/0000078003-00-000007-index.htm"
    )


@responses.activate
def test_fetch_document_builds_correct_url_and_returns_bytes(client):
    responses.add(
        responses.GET,
        f"{SEC_ARCHIVES_BASE}/78003/000007800300000007/doc.htm",
        body=b"<html>filing</html>",
    )
    content = client.fetch_document("0000078003", "0000078003-00-000007", "doc.htm")
    assert content == b"<html>filing</html>"
    assert responses.calls[0].request.url.endswith("/78003/000007800300000007/doc.htm")
