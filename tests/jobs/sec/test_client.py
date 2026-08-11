import pytest
import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.sec.client import SEC_ARCHIVES_BASE, SEC_DATA_BASE, SECClient, list_exhibit_filenames


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
def test_get_filing_index_builds_correct_url(client):
    responses.add(
        responses.GET,
        f"{SEC_ARCHIVES_BASE}/78003/000007800300000007/index.json",
        json={"directory": {"item": []}},
    )
    client.get_filing_index("0000078003", "0000078003-00-000007")
    assert responses.calls[0].request.url.endswith("/78003/000007800300000007/index.json")


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


def test_list_exhibit_filenames_excludes_primary_and_index_artifacts():
    filing_index = {
        "directory": {
            "item": [
                {"name": "0000078003-00-000007-index.htm"},
                {"name": "0000078003-00-000007-index-headers.html"},
                {"name": "0000078003-00-000007.txt"},
                {"name": "0000078003-00-000007-d1.html"},  # primary document
                {"name": "0000078003-00-000007-d2.html"},  # exhibit
                {"name": "ex99.pdf"},  # exhibit
            ]
        }
    }
    exhibits = list_exhibit_filenames(filing_index, "0000078003-00-000007-d1.html", "0000078003-00-000007")
    assert exhibits == ["0000078003-00-000007-d2.html", "ex99.pdf"]


def test_list_exhibit_filenames_handles_missing_directory():
    assert list_exhibit_filenames({}, "primary.htm", "0000000000-00-000001") == []
