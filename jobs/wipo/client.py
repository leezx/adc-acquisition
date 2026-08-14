"""WIPO (Job 08) uses the shared EPO OPS client, filtered to WO-prefixed
PCT publications via its own CQL queries (configs/wipo_queries.yaml).

The OPS API surface, auth, and rate-limit behavior are source-agnostic —
identical for WO and EP prefixes — so the actual client implementation
lives in adc_acquisition/ops_client.py, shared with Job 10 (EPO). This
module re-exports it under the name this job's tests/job.py already import
from, so nothing else needs to change.

See adc_acquisition/ops_client.py's module docstring for the full
legal/technical rationale (WIPO PATENTSCOPE has no public API and its
Terms of Use forbid automation) and live-verified endpoint/throttling
details.
"""

from __future__ import annotations

from adc_acquisition.ops_client import (  # noqa: F401
    BIBLIO_RATE_LIMIT,
    MAX_RANGE_SPAN,
    MAX_TOTAL_RESULTS,
    OPS_AUTH_URL,
    OPS_BASE,
    OPS_SEARCH_URL,
    SEARCH_RATE_LIMIT,
    SEARCH_THROTTLE_BACKOFF_SECONDS,
    SEARCH_THROTTLE_MAX_ATTEMPTS,
    TOKEN_REFRESH_MARGIN_SECONDS,
    OPSAuthError,
    OPSClient,
    OPSThrottleError,
)
