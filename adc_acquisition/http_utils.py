"""HTTP client shared by all acquisition jobs: rate limiting + retry w/ backoff.

Every source job must respect rate limits and back off on transient failures
(Prompt.md section 4). This module centralizes that so individual jobs don't
each reimplement it slightly differently.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class RetryConfig:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0


class RateLimiter:
    """Simple minimum-interval limiter — good enough for a single process
    talking to one external API sequentially."""

    def __init__(self, requests_per_second: float):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._min_interval = 1.0 / requests_per_second
        self._last_call_at: float | None = None

    def wait(self) -> None:
        if self._last_call_at is not None:
            elapsed = time.monotonic() - self._last_call_at
            remaining = self._min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_call_at = time.monotonic()


class RetryingClient:
    """A requests.Session wrapper with exponential backoff on retriable
    failures and a shared rate limiter."""

    def __init__(
        self,
        rate_limiter: RateLimiter,
        retry_config: RetryConfig | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.rate_limiter = rate_limiter
        self.retry_config = retry_config or RetryConfig()
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._request_with_retry("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self._request_with_retry("POST", url, **kwargs)

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        attempt = 0
        while True:
            attempt += 1
            self.rate_limiter.wait()
            try:
                response = self.session.request(
                    method, url, timeout=self.timeout_seconds, **kwargs
                )
            except requests.RequestException as exc:
                if attempt >= self.retry_config.max_attempts:
                    logger.error("giving up on %s %s after %d attempts: %s", method, url, attempt, exc)
                    raise
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "network error on %s %s (attempt %d/%d): %s — retrying in %.1fs",
                    method, url, attempt, self.retry_config.max_attempts, exc, delay,
                )
                time.sleep(delay)
                continue

            if response.status_code in RETRIABLE_STATUS_CODES:
                if attempt >= self.retry_config.max_attempts:
                    logger.error(
                        "giving up on %s %s after %d attempts: HTTP %d",
                        method, url, attempt, response.status_code,
                    )
                    return response
                delay = self._backoff_delay(attempt, response=response)
                logger.warning(
                    "retriable HTTP %d on %s %s (attempt %d/%d) — retrying in %.1fs",
                    response.status_code, method, url, attempt,
                    self.retry_config.max_attempts, delay,
                )
                time.sleep(delay)
                continue

            return response

    def _backoff_delay(self, attempt: int, response: requests.Response | None = None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return min(float(retry_after), self.retry_config.max_delay_seconds)
                except ValueError:
                    pass
        delay = self.retry_config.base_delay_seconds * (2 ** (attempt - 1))
        return min(delay, self.retry_config.max_delay_seconds)
