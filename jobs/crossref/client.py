"""Crossref REST API client.

Docs: https://api.crossref.org/swagger-ui/index.html

No API key required. Including a `mailto` param opts into Crossref's
"polite pool" (better reliability/priority) per their documented etiquette.
Rate limit is dynamic and returned in response headers (`X-Rate-Limit-Limit`,
`X-Rate-Limit-Interval`) — observed live on 2026-08-11 as 10 req/s with a
concurrency limit of 3. We don't adapt to the header in real time; we use a
conservative static default instead.
"""

from __future__ import annotations

from adc_acquisition.http_utils import RetryingClient

CROSSREF_BASE = "https://api.crossref.org"

RATE_LIMIT = 5.0  # req/s; conservative margin under the observed 10 req/s.


class CrossrefClient:
    def __init__(self, http_client: RetryingClient, mailto: str | None = None):
        self.http_client = http_client
        self.mailto = mailto

    def get_work(self, doi: str) -> dict | None:
        """Look up one DOI. Returns the `message` object, or None if
        Crossref doesn't have this DOI (404) — not an error, just "not
        found," so the caller can record it as a distinct outcome rather
        than a generic failure."""
        params = {"mailto": self.mailto} if self.mailto else {}
        response = self.http_client.get(f"{CROSSREF_BASE}/works/{doi}", params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["message"]
