"""HTTP client for fetching pharma company pipeline pages (Job 11,
Prompt.md section 11).

No official API exists for these pages — Prompt.md explicitly frames this
job as "fundamentally different from database APIs" and instructs
starting from a curated `company_registry.yaml` rather than unrestricted
crawling. Fetches whatever bytes the server actually serves (HTML/PDF/
JSON) and lets the job layer version/hash-compare them; this client does
no parsing.

A descriptive User-Agent is sent on every request, same technique already
used for fda.gov's bot detection (jobs/fda/client.py) — but this is NOT a
universal fix: AbbVie's registered pipeline page is behind an active
Cloudflare JS challenge (HTTP 403, "Just a moment..." interstitial),
confirmed live 2026-08-14 that a descriptive User-Agent does NOT get past
it (unlike fda.gov's simpler UA-sniffing block, which this same technique
does resolve). This repo does not attempt to defeat that challenge —
Prompt.md explicitly prohibits CAPTCHA/bot-challenge bypassing and
"aggressive crawling" — so AbbVie's fetch attempts are simply recorded as
normal, logged `failed` attempts (see jobs/company_pipeline/job.py) until
AbbVie offers an alternative official machine-readable route.
"""

from __future__ import annotations

import requests

from adc_acquisition.http_utils import RetryingClient

RATE_LIMIT = 0.5  # req/s -- conservative default; no documented rate limit exists for any of these distinct company domains, and the curated set is small.
USER_AGENT = "adc-acquisition/0.1 (research data acquisition tool; https://github.com/leezx/adc-acquisition)"


class PipelineClient:
    def __init__(self, http_client: RetryingClient):
        self.http_client = http_client

    def fetch(self, url: str) -> requests.Response:
        """Raw response for a pipeline page URL -- caller inspects
        status_code/headers/content directly; no parsing here."""
        return self.http_client.get(url, headers={"User-Agent": USER_AGENT})
