"""Re-exported from adc_acquisition.html_utils for backward compatibility
-- moved there when Job 12 (company press releases) confirmed it needed
the identical generic page-metadata helpers. See that module's docstring
for the full rationale (same pattern as jobs/wipo/parser.py's move to
adc_acquisition/ops_parser.py)."""

from __future__ import annotations

from adc_acquisition.html_utils import extract_html_title, infer_raw_format

__all__ = ["extract_html_title", "infer_raw_format"]
