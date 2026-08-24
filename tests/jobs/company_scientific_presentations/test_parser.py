from jobs.company_scientific_presentations.parser import (
    page_url,
    parse_adctmedical_congress_listing,
    parse_sutro_divi_blog_listing,
)

ADCTMEDICAL_SAMPLE = b"""
<div class='pub_row  poster loncastuximab-tesirine ASH year-2025'><div class='pub_cont wp-block-columns'>
<div class='wp-block-column'><h5 class='has-blue-color'>Poster</h5></div>
<div class='wp-block-column'><h3 class='ltwt has-blue-color'><span>ASH</span> 2025</h3>
<div class='pub_title'><p class='larger'>Lonca Ph 2 Study in r/r WM <span class='author'> | S. Sarosiek</span></p></div></div>
<div class='wp-block-column'><a class='targetfile has-blue-color' href='https://www.adctmedical.com/wp-content/uploads/2025/12/lonca.pdf' target='_blank'>dl</a></div>
</div></div>
"""

SUTRO_SAMPLE = b"""
<article id="post-17825" class="et_pb_post post type-post status-publish hentry category-presentations">
<h2 class="entry-title"><a href="https://www.sutrobio.com/aacr-2026/">AACR Annual Meeting 2026 &#8211; Presentation</a></h2>
<p class="post-meta"><span class="published">Apr 21, 2026</span></p>
</article>
<article id="post-3163" class="post-3163 page type-page status-publish hentry">
<h1>Not a real presentation entry -- the static page wrapper itself</h1>
</article>
"""


def test_parse_adctmedical_congress_listing_extracts_congress_and_pdf_url():
    items = parse_adctmedical_congress_listing(ADCTMEDICAL_SAMPLE, "https://www.adctmedical.com/congresses/")
    assert len(items) == 1
    item = items[0]
    assert item.congress == "ASH 2025"
    assert item.presentation_date is None
    assert item.url == "https://www.adctmedical.com/wp-content/uploads/2025/12/lonca.pdf"
    assert "Lonca Ph 2 Study" in item.title


def test_parse_sutro_divi_blog_listing_ignores_static_page_wrapper():
    """The always-present static page-type article (post-3163) must never
    be mistaken for a real presentation entry -- it lacks the entry-title
    structure real posts have."""
    items = parse_sutro_divi_blog_listing(SUTRO_SAMPLE, "https://www.sutrobio.com/news/presentations/")
    assert len(items) == 1
    item = items[0]
    assert item.url == "https://www.sutrobio.com/aacr-2026/"
    assert item.presentation_date == "2026-04-21"
    assert item.congress is None
    assert "AACR Annual Meeting 2026" in item.title


def test_parse_sutro_divi_blog_listing_returns_empty_for_no_matches():
    assert parse_sutro_divi_blog_listing(b"<html><body>nothing here</body></html>", "https://x.example/") == []


def test_page_url_single_vs_paginated():
    assert page_url("https://www.sutrobio.com/news/presentations/", "sutro_divi_blog", 1) == "https://www.sutrobio.com/news/presentations/"
    assert page_url("https://www.sutrobio.com/news/presentations/", "sutro_divi_blog", 2) == "https://www.sutrobio.com/news/presentations/page/2/"
    assert page_url("https://www.sutrobio.com/news/presentations", "sutro_divi_blog", 3) == "https://www.sutrobio.com/news/presentations/page/3/"
