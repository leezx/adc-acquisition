"""Minimal, deliberately shallow HTML/content-type helpers shared by
sources with no official API of their own (Job 11 company pipeline pages,
Job 12 company press releases, Prompt.md sections 11-12) — moved out of
jobs/company_pipeline/parser.py when Job 12 confirmed it needed the
identical generic helpers (jobs/company_pipeline/parser.py is now a thin
re-export shim, same pattern as adc_acquisition/ops_client.py's move out
of jobs/wipo/client.py).

Deliberately NOT parsing individual page content out of these pages
(drug names, phases, indications, press-release body text) — that is
downstream knowledge extraction (Prompt.md section 1: acquisition
preserves raw evidence, it does not decide what a page means).
"""

from __future__ import annotations

import html
import re

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def extract_html_title(content_bytes: bytes) -> str | None:
    try:
        text = content_bytes.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - title extraction is a convenience, never worth failing the whole fetch over
        return None
    match = _TITLE_RE.search(text)
    if not match:
        return None
    title = html.unescape(match.group(1)).strip()
    return " ".join(title.split()) or None


def infer_raw_format(content_type: str | None, url: str) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct == "application/pdf":
            return "pdf"
        if ct in ("text/html", "application/xhtml+xml"):
            return "html"
        if ct == "application/json":
            return "json"
    lowered = url.lower()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith(".json"):
        return "json"
    return "html"
