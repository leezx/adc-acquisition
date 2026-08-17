"""Shared HTTP client for fetching raw web page/document snapshots from
sources with no official API (Job 11 company pipeline pages, Job 12
company press releases, Prompt.md sections 11-12) — both explicitly
framed by Prompt.md as "fundamentally different from database APIs."
Whatever bytes the server actually serves (HTML/PDF/JSON) are returned
as-is; no parsing happens here, that's the caller's job. Moved out of
jobs/company_pipeline/client.py when Job 12 confirmed it needed the
identical generic fetch-raw-bytes client (jobs/company_pipeline/client.py
is now a thin re-export shim, same pattern as adc_acquisition/ops_client.py's
move out of jobs/wipo/client.py).

A descriptive User-Agent is sent on every request, same technique that
resolved fda.gov's simple UA-sniffing bot detection (jobs/fda/client.py)
— confirmed NOT a universal fix: AbbVie's pipeline page is behind an
active Cloudflare JS challenge that this User-Agent does not get past
(see jobs/company_pipeline/job.py's module docstring); this repo does not
attempt to defeat that challenge (Prompt.md prohibits CAPTCHA/bot-
challenge bypassing), so such failures are simply recorded as normal
logged `failed` attempts.
"""

from __future__ import annotations

import requests

from adc_acquisition.http_utils import RetryingClient

DEFAULT_RATE_LIMIT = 0.5  # req/s -- conservative default; no documented rate limit exists for these company-specific domains, and the curated set is small.
USER_AGENT = "adc-acquisition/0.1 (research data acquisition tool; https://github.com/leezx/adc-acquisition)"


class WebSnapshotClient:
    def __init__(self, http_client: RetryingClient):
        self.http_client = http_client

    def fetch(self, url: str) -> requests.Response:
        """Raw response for any page/document URL -- caller inspects
        status_code/headers/content directly; no parsing here."""
        return self.http_client.get(url, headers={"User-Agent": USER_AGENT})
