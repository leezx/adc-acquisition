"""Press-release LISTING page parsers (Job 12, Prompt.md section 12).

No official API exists for any of these IR newsrooms — same
"fundamentally different from database APIs" framing Prompt.md gives
company pipeline pages (section 11). Live-verified 2026-08-17 that the
registered companies' listing pages fall into a small number of REUSED
third-party IR-platform templates, not one bespoke parser per company:

- "workiva_ir_newsroom": `<li class="wd_item"><div class="wd_item_wrapper">
  <div class="wd_date">DATE</div><div class="wd_title"><a href="URL">
  HEADLINE</a></div>` — confirmed byte-identical between ADC Therapeutics
  and AbbVie. Date text varies between abbreviated ("Aug 13, 2026") and
  full ("August 11, 2026") month names across the two sites, both handled.
- "q4_ir_media": `<article class="media">...<time datetime="ISO">...
  <a href="URL">HEADLINE</a>` (Sutro Biopharma) — the datetime attribute
  is already ISO 8601, no ambiguous-format parsing needed.
- "pfizer_drupal_newsroom": Pfizer's own Drupal template, relative
  `href="/news/..."` links and a `MM.DD.YYYY` date string — the only
  template requiring `urljoin` against the listing page's own URL.

Deliberately regex-based rather than a full HTML-parsing dependency: each
template's listing markup was captured directly from a live fetch and is
machine-generated (IR platform vendor templates), so the structure is
highly regular — verified by count-matching against the live page before
being written here. If a future template proves too irregular for this
approach, promoting to a proper HTML parser is the right fix, not a more
elaborate regex.

Deliberately NOT parsing each release's own detail-page body text —
Prompt.md's job description asks for headline/release date/company/URL/
raw HTML preserved, which the LISTING page itself already provides
cleanly (no need to re-derive title/date from the detail page's own,
often noisier, HTML `<title>`); the detail page's raw bytes are preserved
verbatim as the acquisition evidence, same "acquisition only, no content
extraction" principle as jobs/company_pipeline/parser.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

_WORKIVA_ITEM_RE = re.compile(
    r'<li class="wd_item">\s*<div class="wd_item_wrapper">\s*'
    r'<div class="wd_date">(?P<date>[^<]*)</div>\s*'
    r'<div class="wd_title"><a href="(?P<url>[^"]+)"[^>]*>(?P<headline>.*?)</a></div>',
    re.DOTALL,
)

_Q4_ITEM_RE = re.compile(
    r'<article class="media">\s*<div class="row">\s*<div class="media-body col-md">\s*'
    r'<div class="date">\s*<time datetime="(?P<date>[^"]+)">[^<]*</time>\s*</div>\s*'
    r'<div class="media-heading">\s*<a href="(?P<url>[^"]+)">\s*(?P<headline>.*?)\s*</a>',
    re.DOTALL,
)

_PFIZER_ITEM_RE = re.compile(
    r'<p class="date">\s*(?P<date>[0-9.]+)\s*</p></div>'
    r'<div class="cell small-12 medium-12 lmedium-10"><h5><a href="(?P<url>[^"]+)"[^>]*>(?P<headline>.*?)</a></h5>',
    re.DOTALL,
)

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ReleaseListingItem:
    url: str
    headline: str
    release_date: str | None  # ISO YYYY-MM-DD, or None if unparseable


def _clean_headline(raw: str) -> str:
    import html as _html

    text = _TAG_RE.sub("", raw)
    return " ".join(_html.unescape(text).split())


def _parse_workiva_date(text: str) -> str | None:
    text = text.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_workiva_ir_newsroom_listing(content_bytes: bytes, base_url: str) -> list[ReleaseListingItem]:
    text = content_bytes.decode("utf-8", errors="replace")
    items = []
    for m in _WORKIVA_ITEM_RE.finditer(text):
        items.append(
            ReleaseListingItem(
                url=m.group("url"),
                headline=_clean_headline(m.group("headline")),
                release_date=_parse_workiva_date(m.group("date")),
            )
        )
    return items


def parse_q4_ir_media_listing(content_bytes: bytes, base_url: str) -> list[ReleaseListingItem]:
    text = content_bytes.decode("utf-8", errors="replace")
    items = []
    for m in _Q4_ITEM_RE.finditer(text):
        raw_date = m.group("date").strip()
        try:
            release_date = datetime.fromisoformat(raw_date).date().isoformat()
        except ValueError:
            release_date = None
        items.append(
            ReleaseListingItem(
                url=m.group("url"),
                headline=_clean_headline(m.group("headline")),
                release_date=release_date,
            )
        )
    return items


def parse_pfizer_drupal_newsroom_listing(content_bytes: bytes, base_url: str) -> list[ReleaseListingItem]:
    text = content_bytes.decode("utf-8", errors="replace")
    items = []
    for m in _PFIZER_ITEM_RE.finditer(text):
        raw_date = m.group("date").strip()
        try:
            release_date = datetime.strptime(raw_date, "%m.%d.%Y").date().isoformat()
        except ValueError:
            release_date = None
        items.append(
            ReleaseListingItem(
                url=urljoin(base_url, m.group("url")),
                headline=_clean_headline(m.group("headline")),
                release_date=release_date,
            )
        )
    return items


TEMPLATE_PARSERS = {
    "workiva_ir_newsroom": parse_workiva_ir_newsroom_listing,
    "q4_ir_media": parse_q4_ir_media_listing,
    "pfizer_drupal_newsroom": parse_pfizer_drupal_newsroom_listing,
}

# Pagination scheme per template, live-verified 2026-08-17:
# - "workiva_ir_newsroom": offset-based `?o=N`, genuinely returns 0 items
#   past the real end (ADC Therapeutics/AbbVie both confirmed).
# - "q4_ir_media": 1-indexed `?page=N`; requesting past the real end
#   CLAMPS/wraps to repeat an already-seen page rather than emptying out
#   (Sutro confirmed: page=24 returned the same first item as page=1).
# - "pfizer_drupal_newsroom": 0-indexed `?page=N`; also clamps rather than
#   emptying past the real end (confirmed at page=50/100).
# Because 2 of 3 templates clamp/wrap instead of emptying, the job's own
# stop condition is "this page contributed zero NOT-already-known items"
# (see jobs/company_press_release/job.py), not "this page was empty" —
# that single rule correctly handles both behaviors uniformly.
PAGINATION_CONFIGS = {
    "workiva_ir_newsroom": {"param": "o", "start": 0, "step_mode": "item_count"},
    "q4_ir_media": {"param": "page", "start": 1, "step_mode": "fixed", "step": 1},
    "pfizer_drupal_newsroom": {"param": "page", "start": 0, "step_mode": "fixed", "step": 1},
}
