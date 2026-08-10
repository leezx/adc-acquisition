"""Europe PMC RESTful Web Service client.

Docs: https://europepmc.org/RestfulWebService

No API key or authentication is required. There is no officially published
numeric rate limit in the documentation itself; ~10 req/s is the figure
commonly cited by users on the Europe PMC developer forum
(https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/cZLnV1JhCj8).
We stay well under that (see RATE_LIMIT below) since it isn't an official
guarantee.

Endpoint shapes verified live against the production API on 2026-08-10:
- search: cursorMark-based pagination (start with "*", follow nextCursorMark).
- full text: GET /{pmcid}/fullTextXML (no source segment) returns JATS XML
  for open-access PMC records; 404 otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

from adc_acquisition.http_utils import RetryingClient

EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

RATE_LIMIT = 5.0  # req/s; conservative margin under the ~10 req/s community figure.
DEFAULT_PAGE_SIZE = 200


@dataclass
class SearchPage:
    hit_count: int
    results: list[dict]
    next_cursor_mark: str | None


class EuropePMCClient:
    def __init__(self, http_client: RetryingClient):
        self.http_client = http_client

    def search(self, query: str, cursor_mark: str = "*", page_size: int = DEFAULT_PAGE_SIZE) -> SearchPage:
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": str(page_size),
            "cursorMark": cursor_mark,
        }
        response = self.http_client.get(f"{EUROPEPMC_BASE}/search", params=params)
        response.raise_for_status()
        payload = response.json()
        result_list = payload.get("resultList", {}).get("result", [])
        next_cursor = payload.get("nextCursorMark")
        # Europe PMC repeats the same cursorMark at the end of the result set
        # instead of returning None; without this check pagination would
        # never terminate.
        if next_cursor == cursor_mark:
            next_cursor = None
        return SearchPage(hit_count=int(payload.get("hitCount", 0)), results=result_list, next_cursor_mark=next_cursor)

    def fetch_fulltext_xml(self, pmcid: str) -> bytes:
        response = self.http_client.get(f"{EUROPEPMC_BASE}/{pmcid}/fullTextXML")
        response.raise_for_status()
        return response.content
