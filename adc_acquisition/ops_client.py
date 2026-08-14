"""EPO Open Patent Services (OPS) client — shared by every job that
acquires patent data via OPS (Job 08/WIPO for WO-prefixed PCT
publications, Job 10/EPO for EP-prefixed publications). The OPS API
surface, auth, and rate-limit behavior are identical regardless of which
country-code prefix a job's CQL queries filter to — this module is kept
source-agnostic and lives in the shared layer rather than being owned by
either job.

WIPO PATENTSCOPE itself has no public API, and its own Terms of Use
Section 2.1 explicitly prohibits automated queries, bulk downloading, and
scraping (verified live: "more than 10 search-related actions per minute
from a single IP can be considered excessive") — the reason Job 08 uses
OPS instead of PATENTSCOPE directly. EPO's OPS (https://developers.epo.org,
free registration, OAuth2 client-credentials) is the legitimate
machine-readable route. Its INPADOC/DOCDB data covers both WO- and
EP-prefixed publications' full bibliographic data (applicants, inventors,
priority/publication dates, IPC/CPC, family id, title, abstract) —
verified live on 2026-08-13 (WIPO/WO) and 2026-08-14 (EPO/EP): identical
response schema for both prefixes.

Auth: POST https://ops.epo.org/3.2/auth/accesstoken, HTTP Basic
Authorization header (base64 consumer_key:consumer_secret),
grant_type=client_credentials form body. Returns a bearer token good for
~1199s (verified live) — refreshed proactively before expiry.

Search: GET .../rest-services/published-data/search?q=<CQL>&Range=<begin>-<end>.
CQL confirmed live: `pn=WO and (ti="..." or ab="...")` / `pn=EP and (...)`,
`pd within "YYYYMMDD,YYYYMMDD"` for a publication-date range (the
comma-separated form — a hyphenated range like "YYYYMMDD->YYYYMMDD" is
rejected with CLIENT.UnknownDateFormat). Range span is capped at 100 per
request, and total-result-count access is capped at 2000 across all pages
of one query (CLIENT.InvalidQuery beyond that) — confirmed live. Each
registered query (WIPO's or EPO's) must be checked against this cap before
being registered.

Biblio fetch: GET
.../rest-services/published-data/publication/docdb/{country}.{doc-number}.{kind}/biblio.
A genuine "no such publication" is HTTP 404 with a structured
SERVER.EntityNotFound fault body (verified live) — handled as a normal
not-found outcome, not a fetch failure.

Throttling — verified live on 2026-08-13, and materially different from
every other source in this repo: OPS meters `search` and `retrieval`
(biblio fetch) as SEPARATE quota buckets, reported live via the
`X-Throttling-Control` response header (e.g. "search=black:0,
retrieval=green:100"). Running WIPO's discovery step (5 queries,
paginated) exhausted the `search` bucket specifically after ~15-20 calls,
returning HTTP 403 `CLIENT.RobotDetected` with a `Retry-After` header of
885995 seconds (~10 days) — but the bucket was independently observed back
at `green:15` about 2 minutes later, so that Retry-After value is not a
trustworthy recovery estimate; it's a burst/short-window limiter, not a
multi-day ban. `retrieval` (biblio fetch) was unaffected throughout
(stayed `green:100`) — biblio fetch and search do not share a budget.
Consequently: search and biblio fetch use SEPARATE, independently-paced
RetryingClient instances (SEARCH_RATE_LIMIT much slower than
BIBLIO_RATE_LIMIT), and a 403 specifically on the search endpoint is
treated as a bounded, retriable condition (short internal backoff, a few
attempts) rather than either a hard failure or a literal ~10-day wait.
Also observed live (2026-08-14, EPO/EP verification): an occasional
`SERVER.DomainAccess` HTTP 500 ("The request could not be processed.
Please try again later") on the search endpoint, unrelated to the
X-Throttling-Control headers (which showed ample remaining quota) —
resolved by pacing requests further apart, consistent with SEARCH_RATE_LIMIT
already being conservative; not distinguished from a generic transient
failure since RetryingClient's existing 5xx retry already covers it.
"""

from __future__ import annotations

import base64
import time

import requests

from adc_acquisition.http_utils import RetryingClient

OPS_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
OPS_BASE = "https://ops.epo.org/3.2/rest-services"
OPS_SEARCH_URL = f"{OPS_BASE}/published-data/search"

SEARCH_RATE_LIMIT = 0.15  # req/s (~1 per 6.7s); matches the observed refill cadence (black:0 -> green:15 in ~2 minutes live).
BIBLIO_RATE_LIMIT = 2.0  # req/s; `retrieval` bucket showed ample headroom (green:100) even while `search` was fully throttled.
MAX_RANGE_SPAN = 100  # verified live: a >100-wide Range is rejected with CLIENT.InvalidQuery.
MAX_TOTAL_RESULTS = 2000  # verified live: results beyond this are inaccessible regardless of Range.
TOKEN_REFRESH_MARGIN_SECONDS = 60  # refresh before the verified ~1199s expiry, not at the boundary.
SEARCH_THROTTLE_MAX_ATTEMPTS = 4
SEARCH_THROTTLE_BACKOFF_SECONDS = 30.0


class OPSAuthError(RuntimeError):
    pass


class OPSThrottleError(RuntimeError):
    pass


class OPSClient:
    def __init__(
        self, search_client: RetryingClient, biblio_client: RetryingClient,
        consumer_key: str, consumer_secret: str,
    ):
        self.search_client = search_client
        self.biblio_client = biblio_client
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _fetch_token(self) -> None:
        basic = base64.b64encode(f"{self.consumer_key}:{self.consumer_secret}".encode()).decode()
        response = self.biblio_client.post(
            OPS_AUTH_URL,
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )
        if response.status_code != 200:
            raise OPSAuthError(f"OPS token request failed: HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        self._token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 1199))
        self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_REFRESH_MARGIN_SECONDS, 0)

    def _auth_headers(self) -> dict[str, str]:
        if self._token is None or time.monotonic() >= self._token_expires_at:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, client: RetryingClient, url: str, params: dict) -> requests.Response:
        response = client.get(url, params=params, headers=self._auth_headers())
        if response.status_code == 401:
            # Token expired/revoked mid-run despite our proactive refresh margin — refresh once and retry.
            self._token = None
            response = client.get(url, params=params, headers=self._auth_headers())
        return response

    def search(self, cql_query: str, range_begin: int, range_end: int) -> bytes:
        """Raw XML bytes for one page of search results. range_end - range_begin + 1
        must be <= MAX_RANGE_SPAN, and range_end must be <= MAX_TOTAL_RESULTS."""
        params = {"q": cql_query, "Range": f"{range_begin}-{range_end}"}
        attempt = 0
        while True:
            attempt += 1
            response = self._get(self.search_client, OPS_SEARCH_URL, params)
            if response.status_code == 403 and "ThrottlingControlQuota" in response.headers.get("x-rejection-reason", ""):
                if attempt >= SEARCH_THROTTLE_MAX_ATTEMPTS:
                    raise OPSThrottleError(
                        f"OPS search quota exhausted after {attempt} attempts (query={cql_query!r}, "
                        f"range={range_begin}-{range_end}); X-Throttling-Control={response.headers.get('x-throttling-control')}"
                    )
                time.sleep(SEARCH_THROTTLE_BACKOFF_SECONDS)
                continue
            response.raise_for_status()
            return response.content

    def fetch_biblio(self, docdb_id: str) -> bytes | None:
        """docdb_id like 'WO.2026163182.A1' or 'EP.4789684.A1'. Returns
        None on OPS's genuine "no such publication" 404
        (SERVER.EntityNotFound), not a fetch failure."""
        url = f"{OPS_BASE}/published-data/publication/docdb/{docdb_id}/biblio"
        response = self._get(self.biblio_client, url, {})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content
