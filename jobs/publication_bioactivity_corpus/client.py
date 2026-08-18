"""Unpaywall API client (https://unpaywall.org/products/api) -- Job 14's
mechanism for finding a legally-accessible open-access copy of a
publication by DOI.

Unpaywall's response is METADATA ONLY (is_oa, oa_status, a list of
oa_locations each with host_type/url/url_for_pdf) -- it never returns the
document itself. Fetching the actual bytes from a returned location is a
SEPARATE request to whatever publisher/repository host that location
happens to be on, which is why jobs/publication_bioactivity_corpus/job.py
fetches content via the generic adc_acquisition.web_snapshot_client.
WebSnapshotClient rather than anything in this module -- same "raw bytes,
no parsing, arbitrary host" framing Jobs 11/12 already established for
company pages/press releases.

Verified live (2026-08-18): the `email` query param must look like a real
address -- a placeholder like test@example.com is rejected with HTTP 422;
any plausible domain works. Free, no API key, documented at 100,000
calls/day (https://unpaywall.org/products/api), far above what this job's
candidate volume needs, so no aggressive rate limiting is warranted.
"""

from __future__ import annotations

from dataclasses import dataclass

from adc_acquisition.http_utils import RetryingClient

RATE_LIMIT = 2.0  # req/s -- Unpaywall documents only a 100,000/day quota, no per-second limit; conservative default.
BASE_URL = "https://api.unpaywall.org/v2"


@dataclass(frozen=True)
class OALocation:
    host_type: str | None
    url: str | None
    url_for_pdf: str | None


@dataclass(frozen=True)
class UnpaywallResult:
    doi: str
    is_oa: bool
    oa_status: str | None
    locations: list[OALocation]


class UnpaywallClient:
    def __init__(self, http_client: RetryingClient, email: str):
        self.http_client = http_client
        self.email = email

    def lookup(self, doi: str) -> UnpaywallResult | None:
        """None if Unpaywall has no record at all for this DOI (HTTP 404)
        -- a genuine negative, not a failure. Any other non-2xx status
        raises requests.HTTPError (a subclass of requests.RequestException
        -- the caller treats it as a transient `failed`, same as a network
        error)."""
        response = self.http_client.get(f"{BASE_URL}/{doi}", params={"email": self.email})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()

        # best_oa_location is Unpaywall's own top pick -- always try it
        # first, but still fall back to the rest of oa_locations (a
        # publisher landing page can 403 a bot while a repository mirror
        # of the SAME work succeeds; trying only the "best" one would
        # under-count real availability, the same "attempt broadly"
        # lesson Job 13's round-1 review enforced for patent authorities).
        best = data.get("best_oa_location")
        locations_raw = list(data.get("oa_locations") or [])
        if best:
            locations_raw = [best] + [loc for loc in locations_raw if loc != best]

        locations = [
            OALocation(host_type=loc.get("host_type"), url=loc.get("url"), url_for_pdf=loc.get("url_for_pdf"))
            for loc in locations_raw
        ]
        return UnpaywallResult(
            doi=data.get("doi") or doi,
            is_oa=bool(data.get("is_oa")),
            oa_status=data.get("oa_status"),
            locations=locations,
        )
