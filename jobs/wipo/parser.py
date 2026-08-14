"""WIPO (Job 08) uses the shared, source-agnostic EPO OPS response parser
(adc_acquisition/ops_parser.py), shared with Job 10 (EPO) — the response
schema is identical for WO- and EP-prefixed publications (verified live
2026-08-14). This module re-exports it under the name this job's
tests/job.py already import from, so nothing else needs to change.
"""

from __future__ import annotations

from adc_acquisition.ops_parser import (  # noqa: F401
    ParsedPublication,
    SearchHit,
    parse_biblio_response,
    parse_search_response,
)
