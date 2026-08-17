"""Minimal page-level metadata extraction for company pipeline snapshots
(Job 11). Deliberately NOT parsing individual pipeline program entries out
of the page (drug names, phases, indications) — that is downstream
knowledge extraction (Prompt.md section 1: acquisition preserves raw
evidence, it does not decide what a page means; section 30: "pipeline
presence" is not to be assumed by the acquisition layer as meaningful on
its own). The only thing extracted here is the page's own <title> tag,
when present, purely as a manifest `title` field convenience — not a
claim about which programs the page lists.
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
