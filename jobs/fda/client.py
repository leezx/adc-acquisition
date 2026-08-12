"""openFDA client (drug label full-text search, Drugs@FDA submissions,
Drugs@FDA docs archive retrieval).

Docs: https://open.fda.gov/apis/drug/label/ , https://open.fda.gov/apis/drug/drugsfda/
Authentication: https://open.fda.gov/apis/authentication/

An API key is optional (unlike SEC's mandatory contact requirement) but
raises the daily quota substantially: 240 req/min either way; 1,000
req/day without a key vs. 120,000 req/day with one (verified live on
2026-08-11). Passed as the `api_key` query parameter.

Max `limit` per search request is 1000, enforced by openFDA itself
(verified live: a limit of 1001 is rejected with HTTP 400 BAD_REQUEST).

fda.gov's own web front end (as opposed to api.fda.gov) runs bot
detection that blocks Python `requests`' default User-Agent header:
verified live that a redirect chain landing on fda.gov (some older
application_docs URLs redirect there) silently ends at
fda.gov/apology_objects/abuse-detection-apology.html (HTTP 404) with the
default UA, but resolves to the real page with a descriptive one — same
class of issue as curl vs. the actual client library giving different
results, a reminder to verify reachability through the real request path,
not a substitute tool. A descriptive User-Agent is sent on every request
here as a result (accessdata.fda.gov's document archive didn't show this
behavior, but there's no reason not to send it everywhere).
"""

from __future__ import annotations

from adc_acquisition.http_utils import RetryingClient

FDA_API_BASE = "https://api.fda.gov"
DRUG_LABEL_URL = f"{FDA_API_BASE}/drug/label.json"
DRUGSFDA_URL = f"{FDA_API_BASE}/drug/drugsfda.json"

RATE_LIMIT = 3.0  # req/s; openFDA's documented limit is 240 req/min (= 4 req/s).
MAX_PAGE_SIZE = 1000
USER_AGENT = "adc-acquisition/0.1 (research data acquisition tool; https://github.com/leezx/adc-acquisition)"


class FDAClient:
    def __init__(self, http_client: RetryingClient, api_key: str | None = None):
        self.http_client = http_client
        self.api_key = api_key

    def _params(self, **kwargs) -> dict:
        params = {k: v for k, v in kwargs.items() if v is not None}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT}

    def search_label(self, search: str, skip: int = 0, limit: int = MAX_PAGE_SIZE) -> list[dict]:
        """Full-text search over /drug/label.json (structured product
        labeling). openFDA returns HTTP 404 (with a structured
        {"error": {"code": "NOT_FOUND", ...}} body) for a genuine
        no-match — verified live on 2026-08-11 — which is a normal
        "nothing matched this page" outcome, not a fetch failure, so it's
        handled here rather than propagated as an HTTPError."""
        response = self.http_client.get(
            DRUG_LABEL_URL, params=self._params(search=search, skip=skip, limit=limit), headers=self._headers()
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json().get("results") or []

    def get_drugsfda_by_application(self, application_number: str) -> dict | None:
        """One Drugs@FDA record (submissions + application_docs history)
        for a single application_number. Returns None on openFDA's HTTP
        404 no-match convention (see search_label) — a genuine "not
        found," not a network/HTTP failure."""
        response = self.http_client.get(
            DRUGSFDA_URL,
            params=self._params(search=f'application_number:"{application_number}"', limit=1),
            headers=self._headers(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[0] if results else None

    def fetch_document(self, url: str) -> bytes:
        response = self.http_client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.content
