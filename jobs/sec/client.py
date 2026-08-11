"""SEC EDGAR client (submissions API + Archives document retrieval).

Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
Fair access policy: https://www.sec.gov/os/webmaster-faq#developers

Officially documented (unlike most other sources in this repo): max 10
req/s, and every request MUST carry a User-Agent header identifying the
requester (name/tool + contact) — a request without one gets HTTP 403 and
may briefly block the source IP. We use 8 req/s to stay under the limit.
"""

from __future__ import annotations

from adc_acquisition.http_utils import RetryingClient

SEC_DATA_BASE = "https://data.sec.gov"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

RATE_LIMIT = 8.0  # req/s; SEC's documented limit is 10 req/s.


class SECClient:
    def __init__(self, http_client: RetryingClient, user_agent: str):
        self.http_client = http_client
        self.user_agent = user_agent

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent}

    def get_submissions(self, cik: str) -> dict:
        padded = cik.zfill(10)
        response = self.http_client.get(f"{SEC_DATA_BASE}/submissions/CIK{padded}.json", headers=self._headers())
        response.raise_for_status()
        return response.json()

    def get_submissions_page(self, file_name: str) -> dict:
        """Follow filings.files[].name for a company with >1000 filings —
        the 'recent' block in get_submissions only covers the latest 1000."""
        response = self.http_client.get(f"{SEC_DATA_BASE}/submissions/{file_name}", headers=self._headers())
        response.raise_for_status()
        return response.json()

    def get_filing_index_page(self, cik: str, accession_number: str) -> str:
        """The human-readable `{accession-number}-index.htm` page — unlike
        `index.json`'s bare directory listing, this page's "Document Format
        Files" table carries SEC's own per-document type (form type,
        "EX-10.3", "GRAPHIC", ...), which is what distinguishes a real
        exhibit from an embedded image or XBRL data file."""
        url = f"{SEC_ARCHIVES_BASE}/{int(cik)}/{accession_number.replace('-', '')}/{accession_number}-index.htm"
        response = self.http_client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.text

    def fetch_document(self, cik: str, accession_number: str, filename: str) -> bytes:
        url = f"{SEC_ARCHIVES_BASE}/{int(cik)}/{accession_number.replace('-', '')}/{filename}"
        response = self.http_client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.content
