"""Crossref REST API client for live, single-journal conference-abstract
discovery (V1.1 PR #37).

Docs: https://api.crossref.org/swagger-ui/index.html

No API key required. Reuses the same `RetryingClient`/rate-limit/mailto
"polite pool" pattern already established by jobs/crossref/client.py, but
hits the `/works?` COLLECTION endpoint (relevance-ranked search) instead of
the exact `/works/{doi}` lookup -- see this package's job.py module
docstring for why this is tractable here despite
configs/crossref_reconciliation_sources.yaml's own documented warning that
Crossref free-text search is unusable for UNRESTRICTED topic discovery:
every query here is additionally filtered to one specific journal's ISSN,
which narrows the candidate pool from "all of Crossref" to "one journal,"
categorically different in scale and precision.

Cursor-based deep paging, same shape as Europe PMC's own cursorMark
pattern (jobs/europe_pmc/client.py) -- Crossref calls its equivalent field
`next-cursor` inside the response body's `message` object, not a top-level
field, and returns it as `null`/absent once exhausted rather than repeating
the same cursor (Europe PMC's own termination quirk does not apply here,
but is still checked defensively since Crossref's docs do not explicitly
guarantee non-repetition).
"""

from __future__ import annotations

from dataclasses import dataclass

from adc_acquisition.http_utils import RetryingClient

CROSSREF_BASE = "https://api.crossref.org"

RATE_LIMIT = 5.0  # req/s; same conservative margin as jobs/crossref/client.py.
DEFAULT_ROWS = 100


@dataclass
class SearchPage:
    total_results: int
    items: list[dict]
    next_cursor: str | None


class CrossrefSearchClient:
    def __init__(self, http_client: RetryingClient, mailto: str | None = None):
        self.http_client = http_client
        self.mailto = mailto

    def search(
        self, query_bibliographic: str, filters: list[str], cursor: str = "*", rows: int = DEFAULT_ROWS,
    ) -> SearchPage:
        """`filters` is the full, already-assembled list of raw Crossref
        filter clauses for this call (e.g. `["issn:0006-4971",
        "from-pub-date:2026-01-01"]`) -- comma-joined into one `filter`
        param. Same-type filters (e.g. two `issn:` clauses) are OR'd by
        Crossref; different-type filters (issn + date) are AND'd -- both
        confirmed live, see this package's job.py module docstring."""
        params = {
            "query.bibliographic": query_bibliographic,
            "filter": ",".join(filters),
            "rows": str(rows),
            "cursor": cursor,
        }
        if self.mailto:
            params["mailto"] = self.mailto
        response = self.http_client.get(f"{CROSSREF_BASE}/works", params=params)
        response.raise_for_status()
        payload = response.json()["message"]
        items = payload.get("items", [])
        next_cursor = payload.get("next-cursor")
        if next_cursor == cursor:
            next_cursor = None
        return SearchPage(
            total_results=int(payload.get("total-results", 0)),
            items=items,
            next_cursor=next_cursor,
        )
