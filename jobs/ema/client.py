"""EMA client: bulk medicines list, EPAR page, document retrieval.

EMA (unlike FDA/SEC) has no public REST API for this — it publishes a
single bulk XLSX ("Download medicine data",
https://www.ema.europa.eu/en/medicines/download-medicine-data) covering
every EMA-authorised medicine, refreshed periodically, plus a static HTML
"EPAR" page per medicine listing its actual documents (product
information, assessment reports, ...) as plain PDF links. Verified live
on 2026-08-12 — this is real static HTML/XLSX, no JS rendering or
scraping-detection issues observed (unlike fda.gov's bot block — see
jobs/fda/client.py).

No documented rate limit found for ema.europa.eu. Verified live on
2026-08-12: at 2 req/s, a sustained run of a few hundred document
fetches started getting HTTP 429s (with a Retry-After of 0, which
defeats normal backoff) partway through — ema.europa.eu enforces some
kind of burst/session limit tighter than its per-request pacing alone.
0.5 req/s avoided this in the same live run.
"""

from __future__ import annotations

from adc_acquisition.http_utils import RetryingClient

EMA_MEDICINES_XLSX_URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines-report_en.xlsx"
RATE_LIMIT = 0.5  # req/s; see module docstring — verified live, 2 req/s triggered 429s.
USER_AGENT = "adc-acquisition/0.1 (research data acquisition tool; https://github.com/leezx/adc-acquisition)"


class EMAClient:
    def __init__(self, http_client: RetryingClient):
        self.http_client = http_client

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT}

    def fetch_medicines_xlsx(self) -> bytes:
        response = self.http_client.get(EMA_MEDICINES_XLSX_URL, headers=self._headers())
        response.raise_for_status()
        return response.content

    def fetch_epar_page(self, url: str) -> str:
        response = self.http_client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.text

    def fetch_document(self, url: str) -> bytes:
        response = self.http_client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.content
