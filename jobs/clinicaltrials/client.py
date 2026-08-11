"""ClinicalTrials.gov API v2 client.

Docs: https://clinicaltrials.gov/data-api/api

No API key or authentication required. No officially documented numeric
rate limit as of 2026-08-10; ~50 req/min (~0.83 req/s) is the figure
commonly cited by third-party users. We stay well under that.

Endpoint shapes verified live against the production API on 2026-08-10:
- GET /studies?query.term=...&pageSize=...&pageToken=... — pageToken-based
  pagination; `nextPageToken` is simply absent from the response once there
  are no more pages (no repeated-token trap like Europe PMC's cursorMark).
- Each returned study already contains the FULL protocolSection inline
  (identification/status/sponsor/design/arms/outcomes/eligibility/contacts
  modules) — there is no separate "fetch full record" step needed, unlike
  PubMed (esearch -> efetch) or Europe PMC (search -> fullTextXML).
- countTotal=true must be passed to get `totalCount` in the response.
"""

from __future__ import annotations

from dataclasses import dataclass

from adc_acquisition.http_utils import RetryingClient

CTGOV_BASE = "https://clinicaltrials.gov/api/v2"

RATE_LIMIT = 0.7  # req/s; conservative margin under the ~0.83 req/s community figure.
DEFAULT_PAGE_SIZE = 100


@dataclass
class SearchPage:
    total_count: int | None
    studies: list[dict]
    next_page_token: str | None


class ClinicalTrialsClient:
    def __init__(self, http_client: RetryingClient):
        self.http_client = http_client

    @staticmethod
    def _date_filter(since: str | None, until: str | None) -> str | None:
        if not since and not until:
            return None
        return f"AREA[LastUpdatePostDate]RANGE[{since or 'MIN'},{until or 'MAX'}]"

    def _search(self, query_params: dict, page_token: str | None, page_size: int, since: str | None, until: str | None) -> SearchPage:
        params = {**query_params, "pageSize": str(page_size), "format": "json", "countTotal": "true"}
        date_filter = self._date_filter(since, until)
        if date_filter:
            params["filter.advanced"] = date_filter
        if page_token:
            params["pageToken"] = page_token
        response = self.http_client.get(f"{CTGOV_BASE}/studies", params=params)
        response.raise_for_status()
        payload = response.json()
        return SearchPage(
            total_count=payload.get("totalCount"),
            studies=payload.get("studies", []),
            next_page_token=payload.get("nextPageToken"),
        )

    def search(
        self, query_term: str, page_token: str | None = None, page_size: int = DEFAULT_PAGE_SIZE,
        since: str | None = None, until: str | None = None,
    ) -> SearchPage:
        return self._search({"query.term": query_term}, page_token, page_size, since, until)

    def search_by_intervention(
        self, intervention_name: str, page_token: str | None = None, page_size: int = DEFAULT_PAGE_SIZE,
        since: str | None = None, until: str | None = None,
    ) -> SearchPage:
        """Known-asset lookup capability (Prompt.md section 10.B): find
        trials by a specific intervention/drug name rather than a broad
        discovery query."""
        return self._search({"query.intr": intervention_name}, page_token, page_size, since, until)
