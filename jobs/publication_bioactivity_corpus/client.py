"""Unpaywall API client (https://unpaywall.org/products/api) -- Job 14's
mechanism for finding a legally-accessible open-access copy of a
publication by DOI -- and the NCBI PMC ID Converter client, used ONLY to
resolve a PMID-only upstream record (no DOI, no PMCID already known) onto
this job's existing DOI/PMCID acquisition paths (see job.py's module
docstring for why this is exact-identifier resolution, not a literature
search).

Unpaywall's response is METADATA ONLY (is_oa, oa_status, a list of
oa_locations each with host_type/url/url_for_pdf/url_for_landing_page) --
it never returns the document itself. Fetching the actual bytes from a
returned location is a SEPARATE request to whatever publisher/repository
host that location happens to be on, which is why
jobs/publication_bioactivity_corpus/job.py fetches content via the
generic adc_acquisition.web_snapshot_client.WebSnapshotClient rather than
anything in this module -- same "raw bytes, no parsing, arbitrary host"
framing Jobs 11/12 already established for company pages/press releases.

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

IDCONV_BASE_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
IDCONV_RATE_LIMIT = 2.8  # req/s -- same conservative no-key NCBI E-utilities default as jobs/pubmed/client.py.
IDCONV_BATCH_SIZE = 200  # NCBI's own documented per-request id limit for this endpoint.


@dataclass(frozen=True)
class OALocation:
    host_type: str | None
    url: str | None
    url_for_pdf: str | None
    url_for_landing_page: str | None

    def candidate_urls(self) -> list[str]:
        """Unique, ordered URLs worth trying for this ONE location, PDF
        first: Unpaywall's own docs note `url` already points at the PDF
        when one exists and only falls back to the landing page otherwise,
        but a location's PDF link can independently 403 a bot while its
        landing page still serves full text as HTML -- so both are tried,
        not just whichever the "best" single link happens to be, before
        moving on to the NEXT location entirely."""
        urls: list[str] = []
        for url in (self.url_for_pdf, self.url_for_landing_page, self.url):
            if url and url not in urls:
                urls.append(url)
        return urls


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
            OALocation(
                host_type=loc.get("host_type"), url=loc.get("url"),
                url_for_pdf=loc.get("url_for_pdf"), url_for_landing_page=loc.get("url_for_landing_page"),
            )
            for loc in locations_raw
        ]
        return UnpaywallResult(
            doi=data.get("doi") or doi,
            is_oa=bool(data.get("is_oa")),
            oa_status=data.get("oa_status"),
            locations=locations,
        )


@dataclass(frozen=True)
class IdConverterRecord:
    pmid: str
    pmcid: str | None
    doi: str | None


class PMCIDConverterClient:
    """NCBI's PMC ID Converter (https://www.ncbi.nlm.nih.gov/pmc/tools/id-converter-api/)
    -- exact PMID -> PMCID/DOI resolution. Used ONLY to route a PMID-only
    upstream record (one Job 01/02 already discovered, with no DOI and no
    PMCID recorded) onto this job's existing acquisition paths; it never
    discovers a new record, so this is not a literature search."""

    def __init__(self, http_client: RetryingClient, tool: str | None = None, email: str | None = None):
        self.http_client = http_client
        self.tool = tool
        self.email = email

    def convert_batch(self, pmids: list[str]) -> dict[str, IdConverterRecord]:
        """pmid -> IdConverterRecord for every pmid NCBI could resolve to
        at least a pmcid or doi. A pmid absent from the returned dict is a
        genuine negative (NCBI has no PMC/DOI mapping for it), not a
        failure -- distinguished from a request-level failure, which
        raises requests.RequestException instead of silently omitting
        pmids."""
        results: dict[str, IdConverterRecord] = {}
        for i in range(0, len(pmids), IDCONV_BATCH_SIZE):
            batch = pmids[i : i + IDCONV_BATCH_SIZE]
            if not batch:
                continue
            params = {"ids": ",".join(batch), "format": "json"}
            if self.tool:
                params["tool"] = self.tool
            if self.email:
                params["email"] = self.email
            response = self.http_client.get(IDCONV_BASE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            for record in payload.get("records", []):
                # Live-verified (2026-08-18): NCBI's JSON response encodes
                # `pmid` as a JSON NUMBER (int), not the string we sent --
                # keying results on it directly would silently never match
                # a lookup by our own string pmids, making every
                # resolution look unresolved even on a genuine hit.
                # `requested-id` always echoes back exactly the string we
                # requested, so prefer it.
                pmid = str(record.get("requested-id") or record.get("pmid") or "").strip()
                if not pmid or record.get("status") == "error":
                    continue
                results[pmid] = IdConverterRecord(pmid=pmid, pmcid=record.get("pmcid"), doi=record.get("doi"))
        return results
