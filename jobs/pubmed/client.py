"""NCBI E-utilities client for PubMed (esearch + efetch).

Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""

from __future__ import annotations

from dataclasses import dataclass

from adc_acquisition.http_utils import RetryingClient

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# NCBI's own documented limits: 3 req/s without a key, 10 req/s with one.
# We stay slightly under each to leave headroom for jitter/clock drift.
RATE_LIMIT_WITH_KEY = 9.0
RATE_LIMIT_WITHOUT_KEY = 2.8

# NCBI asks that batch efetch calls stay at a couple hundred UIDs per call.
# We always POST (rather than GET) so the URL-length limit never becomes a
# per-batch-size concern.
EFETCH_BATCH_SIZE = 200


@dataclass
class EsearchResult:
    count: int
    idlist: list[str]


class PubMedClient:
    def __init__(
        self,
        http_client: RetryingClient,
        api_key: str | None = None,
        tool: str | None = None,
        email: str | None = None,
    ):
        self.http_client = http_client
        self.api_key = api_key
        self.tool = tool
        self.email = email

    def _common_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.tool:
            params["tool"] = self.tool
        if self.email:
            params["email"] = self.email
        return params

    def esearch(
        self,
        term: str,
        retstart: int = 0,
        retmax: int = 200,
        mindate: str | None = None,
        maxdate: str | None = None,
    ) -> EsearchResult:
        params = {
            **self._common_params(),
            "db": "pubmed",
            "term": term,
            "retmode": "json",
            "retstart": str(retstart),
            "retmax": str(retmax),
        }
        if mindate or maxdate:
            params["datetype"] = "pdat"
            params["mindate"] = mindate or "1900/01/01"
            params["maxdate"] = maxdate or "3000/01/01"

        response = self.http_client.get(f"{EUTILS_BASE}/esearch.fcgi", params=params)
        response.raise_for_status()
        payload = response.json()
        result = payload.get("esearchresult", {})
        if "ERROR" in result:
            raise RuntimeError(f"esearch error for term={term!r}: {result['ERROR']}")
        return EsearchResult(
            count=int(result.get("count", 0)),
            idlist=list(result.get("idlist", [])),
        )

    def efetch_raw_xml(self, pmids: list[str]) -> bytes:
        """Fetch full PubmedArticleSet XML for up to EFETCH_BATCH_SIZE PMIDs."""
        if not pmids:
            return b""
        params = {
            **self._common_params(),
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        response = self.http_client.post(f"{EUTILS_BASE}/efetch.fcgi", data=params)
        response.raise_for_status()
        return response.content
