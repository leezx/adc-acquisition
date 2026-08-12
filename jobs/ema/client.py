"""EMA client: bulk medicines/documents JSON feeds, document retrieval.

EMA has no public REST API for this, but explicitly publishes bulk JSON
exports intended for automated systems
(https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format,
verified live 2026-08-12) — one covering every EMA-authorised medicine,
one covering every EPAR document across every medicine (20,099 records
live), each with stable per-record identifiers (ema_product_number;
document `id`) and first_published/last_updated dates. This supersedes
scraping the rendered per-medicine EPAR HTML page: the documents feed is
already the authoritative, structured enumeration of every document,
independent of any single medicine's own page.

No documented rate limit found for ema.europa.eu; verified live that
sustained per-medicine-page + per-document request volume can trigger a
cumulative session-level throttle (HTTP 429) — using the bulk JSON feeds
instead of per-medicine page scraping avoids most of that traffic
entirely, since discovery no longer needs one request per medicine.
"""

from __future__ import annotations

from adc_acquisition.http_utils import RetryingClient

EMA_MEDICINES_JSON_URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json"
EMA_EPAR_DOCUMENTS_JSON_URL = "https://www.ema.europa.eu/en/documents/report/documents-output-epar_documents_json-report_en.json"
RATE_LIMIT = 1.0  # req/s; no official published limit. Document PDF fetches are now the only per-record traffic.
USER_AGENT = "adc-acquisition/0.1 (research data acquisition tool; https://github.com/leezx/adc-acquisition)"


class EMAClient:
    def __init__(self, http_client: RetryingClient):
        self.http_client = http_client

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT}

    def fetch_medicines_json(self) -> bytes:
        response = self.http_client.get(EMA_MEDICINES_JSON_URL, headers=self._headers())
        response.raise_for_status()
        return response.content

    def fetch_epar_documents_json(self) -> bytes:
        response = self.http_client.get(EMA_EPAR_DOCUMENTS_JSON_URL, headers=self._headers())
        response.raise_for_status()
        return response.content

    def fetch_document(self, url: str) -> bytes:
        response = self.http_client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.content
