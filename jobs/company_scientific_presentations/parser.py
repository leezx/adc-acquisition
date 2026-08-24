"""Scientific-presentation LISTING page parsers (BREADTH_PLAN.md Phase 5
Part 7).

Distinct from jobs/company_press_release/parser.py's press-release
templates: a company's IR newsroom announces corporate news, but its
ACTUAL scientific congress presentations/posters (AACR/ASCO/ESMO/ASH/etc.)
often live on a separate page entirely -- confirmed live 2026-08-24 (see
configs/company_registry.yaml's presentations_url/presentations_template
comment for which companies were checked and why only two are registered
so far).

Same deliberately-regex-based approach as Job 12's parser, for the same
reason: each template's listing markup was captured directly from a live
fetch and is machine-generated (WordPress/CMS templates), highly regular,
verified by count-matching against the live page before being written
here.

- "adctmedical_congress_listing" (ADC Therapeutics, adctmedical.com):
  `<div class='pub_row ...'>` blocks. NO separate HTML detail page --
  each block links DIRECTLY to a PDF poster/slide-deck file. NO per-item
  date finer than the congress year (e.g. "ASH 2025") -- preserved as a
  distinct `congress` field, never fabricated into a false-precision
  date.
- "sutro_divi_blog" (Sutro Biopharma, sutrobio.com): a Divi-theme
  (Elegant Themes) WordPress blog loop, `<article id="post-N" ...>`
  items. Each item's own URL is an HTML detail page (not a direct PDF).

Deliberately NOT following each Sutro item one hop deeper to find an
embedded PDF within its detail page -- same "acquisition preserves raw
evidence, it does not chase every embedded asset" principle already
established for Job 12's press-release detail pages.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass
from datetime import datetime

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(raw: str) -> str:
    text = _TAG_RE.sub("", raw)
    return " ".join(html_module.unescape(text).split())


@dataclass(frozen=True)
class PresentationListingItem:
    url: str
    title: str
    presentation_date: str | None  # ISO YYYY-MM-DD, or None if unknown/unparseable
    congress: str | None = None  # e.g. "ASH 2025" -- only populated where the source has no finer date


_ADCTMEDICAL_ITEM_RE = re.compile(
    r"<h3 class='ltwt has-blue-color'><span>(?P<congress>[^<]+)</span>\s*(?P<year>\d{4})</h3>.*?"
    r"<p class='larger'>(?P<title>.*?)</p>.*?"
    r"<a class='targetfile[^']*' href='(?P<url>[^']+)'",
    re.DOTALL,
)


def parse_adctmedical_congress_listing(content_bytes: bytes, base_url: str) -> list[PresentationListingItem]:
    text = content_bytes.decode("utf-8", errors="replace")
    items = []
    for m in _ADCTMEDICAL_ITEM_RE.finditer(text):
        items.append(
            PresentationListingItem(
                url=m.group("url"),
                title=_clean_text(m.group("title")),
                presentation_date=None,
                congress=f"{m.group('congress').strip()} {m.group('year')}",
            )
        )
    return items


_SUTRO_DIVI_ITEM_RE = re.compile(
    r'<article id="post-\d+"[^>]*>.*?'
    r'<h2 class="entry-title">\s*<a href="(?P<url>[^"]+)">(?P<title>.*?)</a>\s*</h2>.*?'
    r'<p class="post-meta"><span class="published">(?P<date>[^<]*)</span></p>',
    re.DOTALL,
)


def _parse_divi_date(text: str) -> str | None:
    text = text.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_sutro_divi_blog_listing(content_bytes: bytes, base_url: str) -> list[PresentationListingItem]:
    text = content_bytes.decode("utf-8", errors="replace")
    items = []
    for m in _SUTRO_DIVI_ITEM_RE.finditer(text):
        items.append(
            PresentationListingItem(
                url=m.group("url"),
                title=_clean_text(m.group("title")),
                presentation_date=_parse_divi_date(m.group("date")),
            )
        )
    return items


TEMPLATE_PARSERS = {
    "adctmedical_congress_listing": parse_adctmedical_congress_listing,
    "sutro_divi_blog": parse_sutro_divi_blog_listing,
}

# Pagination scheme per template, live-verified 2026-08-24:
# - "adctmedical_congress_listing": "single_page" -- all ~115 entries load
#   on the one page (confirmed live: no pagination controls exist), so
#   the job fetches it exactly once and never increments a cursor.
# - "sutro_divi_blog": standard WordPress path-based pagination, page 1
#   is the base URL itself, page N (N>=2) is `{base_url}page/N/` -- NOT a
#   query-string parameter like any of Job 12's three templates.
#   Confirmed live that pages past the real end parse to zero items (a
#   static always-present "page"-type post never matches the entry-title
#   pattern), so the job's "stop when this page contributes zero
#   NOT-already-known items" rule (same as Job 12) is a genuine empty-page
#   stop here, not a clamp/wraparound.
PAGINATION_CONFIGS = {
    "adctmedical_congress_listing": {"mode": "single_page"},
    "sutro_divi_blog": {"mode": "wordpress_path", "start": 1},
}


def page_url(base_url: str, template: str, page_num: int) -> str:
    """page_num is 1-indexed. Only meaningful for templates whose
    PAGINATION_CONFIGS mode is "wordpress_path" -- callers must not paginate
    a "single_page" template at all."""
    if page_num <= 1:
        return base_url
    return base_url.rstrip("/") + f"/page/{page_num}/"
