"""USPTO Open Data Portal (ODP) client — Patent File Wrapper API.

USPTO's own developer portal (developer.uspto.gov) was decommissioned and
PatentsView (api.patentsview.org) was shut down 2026-03-20 (it now
redirects to ODP's own transition guide) — data.uspto.gov's Open Data
Portal is the current, actively-maintained official mechanism. Unlike
WIPO/PATENTSCOPE, there's no automation ban here: a free USPTO.gov account
+ API key is required (since 2026-06-18, framed as curbing unregistered
bot/scraping traffic, not prohibiting automated access outright).

Auth: `X-API-KEY: <key>` header on every request (verified live — no OAuth
flow, no token expiry to manage, simpler than EPO OPS).

Search: GET /api/v1/patent/applications/search?q=<query>&limit=<n>&offset=<n>.
`q` is free-text and searches across specification/title/abstract content
(broader than WIPO OPS's title/abstract-only CQL fields) — confirmed live
that a phrase like "antibody-drug conjugate" or a field-restricted query
like `applicationMetaData.inventionTitle:cancer` both work and return
materially different counts (60860 vs 75296 for "cancer"), so field
restriction genuinely narrows results when used. Date-range filtering is
supported via `applicationMetaData.filingDate:[YYYY-MM-DD TO YYYY-MM-DD]`
(bracket-range syntax — confirmed live; note this differs from OPS's
comma-separated `pd within "..."` form, underscoring "verify each source's
own date syntax, don't assume a prior source's shape"). `limit` is capped
at 100 per request (CLIENT 400 above that); a full unrestricted page of
100 records can trip a 6MB response-payload cap (413) because each record
includes a large `eventDataBag` prosecution-history log — pass `fields=`
to request only the fields actually needed (verified live: this both
avoids the 413 and reduces payload). Unlike OPS, there is NO total-result
access cap — verified live that offset=50000 into a 75296-result query
still returns data cleanly.

Per-application fetch: GET /api/v1/patent/applications/{applicationNumber}
returns the COMPLETE, unrestricted record (no `fields` param needed) —
this is the "raw" source-native representation preserved verbatim, same
role as FDA's per-application drugsfda lookup. A genuine "no such
application" is HTTP 404 with a structured `{"code": "404", ...}` body —
handled as a normal not-found outcome, not a fetch failure.

Documents (secondary artifact, "claims/full text where available" per
Prompt.md): GET .../{applicationNumber}/documents lists every document in
that application's file wrapper (Notice of Publication, Filing Receipt,
Claims Worksheet, Specification, ...) with per-document PDF/XML download
URLs. The Specification (`documentCode == "SPEC"`) is the actual filed
claims/full-text document — there can be more than one (original +
amendments), all kept, same "don't collapse multi-version provenance"
principle as everywhere else in this repo.

Rate limiting: weekly quotas are generous (5,000,000 metadata retrievals,
1,200,000 document retrievals — verified live via the account's own
consumption dashboard) but a burst of rapid successive requests during
live verification did trip a short-window HTTP 429 — so a conservative
per-second pace is still used here despite the generous weekly ceiling,
same "don't assume a big weekly quota means no short-window throttle"
caution as every other source in this repo.
"""

from __future__ import annotations

from adc_acquisition.http_utils import RetryingClient

USPTO_API_BASE = "https://api.uspto.gov/api/v1/patent/applications"
SEARCH_URL = f"{USPTO_API_BASE}/search"

RATE_LIMIT = 2.0  # req/s; conservative given a live-observed short-window 429 despite generous weekly quotas.
MAX_PAGE_SIZE = 100  # verified live: CLIENT 400 above this.
SEARCH_FIELDS = "applicationNumberText"  # discovery only needs the identifier; keeps pages well under the 6MB/413 cap.


class USPTOClient:
    def __init__(self, http_client: RetryingClient, api_key: str):
        self.http_client = http_client
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key, "Accept": "application/json"}

    def search(self, query: str, limit: int, offset: int) -> tuple[list[str], int]:
        """Returns (application_number_text list for this page, total count).
        A genuine "no matches at this offset" is HTTP 404 (verified live,
        e.g. paging past a query's real total) -- treated as an empty page,
        not a fetch failure."""
        response = self.http_client.get(
            SEARCH_URL,
            params={"q": query, "limit": limit, "offset": offset, "fields": SEARCH_FIELDS},
            headers=self._headers(),
        )
        if response.status_code == 404:
            return [], 0
        response.raise_for_status()
        payload = response.json()
        ids = [row["applicationNumberText"] for row in payload.get("patentFileWrapperDataBag", [])]
        return ids, int(payload.get("count") or 0)

    def get_application(self, application_number: str) -> dict | None:
        """Complete, unrestricted raw record for one application. Returns
        None on USPTO's genuine "no such application" 404."""
        response = self.http_client.get(
            f"{USPTO_API_BASE}/{application_number}", headers=self._headers()
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        results = response.json().get("patentFileWrapperDataBag") or []
        return results[0] if results else None

    def list_documents(self, application_number: str) -> list[dict]:
        """All file-wrapper documents for one application. Returns an
        empty list on a genuine 404 (e.g. an application with no
        documents yet), not a fetch failure."""
        response = self.http_client.get(
            f"{USPTO_API_BASE}/{application_number}/documents", headers=self._headers()
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json().get("documentBag") or []

    def fetch_document(self, url: str) -> bytes:
        response = self.http_client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.content
