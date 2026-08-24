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

ROUND-1 FIX: a Sutro detail page's own HTML is frequently just a wrapper
("Sutro presented at AACR... View presentation here.") -- unlike Job 12's
press-release detail pages, where the HTML itself IS the primary
evidence. The actual target/payload/linker/platform/preclinical content
lives in an embedded presentation/poster PDF, so this module also
extracts that PDF (`parse_sutro_detail_page_artifacts`), materialized by
the job as a CHILD record of the HTML parent -- one hop only, no further
recursion, on-domain only, HTML parent is always kept regardless of
whether an artifact was found. See `jobs/company_scientific_presentations
/job.py`'s module docstring for the full materialization design.

Live-verified against all 189 already-downloaded Sutro detail pages
(2026-08-24): the WordPress standard per-post-dated media-library path
(`/wp-content/uploads/YYYY/MM/*.pdf`) is a reliable, narrow signal for a
genuine on-page artifact -- of 112 distinct such URLs found across all
189 pages, only ONE (a "Visitors Guide" PDF in the sitewide footer)
recurs across many pages and is not a genuine per-presentation artifact;
every other URL is unique to its own page. That one is excluded by name
(`_SUTRO_VISITOR_GUIDE_MARKER`), the same "one known, named, static,
non-entry element" exclusion discipline this module's listing parser
already uses for the always-present `post-3163` page wrapper.
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

# The one known, named, static, sitewide asset that is never a genuine
# per-presentation artifact -- confirmed live 2026-08-24 to appear
# identically on all 189 Sutro detail pages (a footer widget link), the
# only URL of the 112 distinct matches across all pages that repeats.
_SUTRO_VISITOR_GUIDE_MARKER = "Visitors-Guide"

# WordPress's own per-post-dated media-library upload path -- confirmed
# live 2026-08-24 to be a reliable, narrow signal for a genuine embedded
# presentation/poster PDF on a Sutro detail page (see module docstring).
_SUTRO_DETAIL_ARTIFACT_RE = re.compile(r'href="(?P<url>[^"]*/wp-content/uploads/\d{4}/\d{2}/[^"]+\.pdf)"')


def parse_sutro_detail_page_artifacts(content_bytes: bytes, page_url: str) -> list[str]:
    """Extract the primary presentation/poster PDF artifact URL(s) embedded
    in a Sutro detail page -- one hop only, no further recursion. A page
    may legitimately bundle several distinct artifacts (e.g. a multi-
    author conference wrap-up post links one poster PDF per author), so
    this returns all matches, deduplicated, in document order."""
    text = content_bytes.decode("utf-8", errors="replace")
    seen: list[str] = []
    for m in _SUTRO_DETAIL_ARTIFACT_RE.finditer(text):
        url = html_module.unescape(m.group("url"))
        if _SUTRO_VISITOR_GUIDE_MARKER in url:
            continue
        if url not in seen:
            seen.append(url)
    return seen


ARTIFACT_PARSERS = {
    "sutro_divi_blog": parse_sutro_detail_page_artifacts,
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
