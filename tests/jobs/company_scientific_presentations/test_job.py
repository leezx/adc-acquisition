import argparse

import pandas as pd
import responses

from adc_acquisition import http_utils
from jobs.company_scientific_presentations.job import CompanyScientificPresentationsJob

ADCT_ONLY_YAML = """
companies:
  - company_id: adct
    canonical_name: ADC Therapeutics SA
    official_domain: adctherapeutics.example
    presentations_url: "https://www.adctmedical.example/congresses/"
    presentations_template: adctmedical_congress_listing
    active: true
"""

SUTRO_ONLY_YAML = """
companies:
  - company_id: sutro
    canonical_name: Sutro Biopharma, Inc.
    official_domain: sutrobio.example
    presentations_url: "https://www.sutrobio.example/news/presentations/"
    presentations_template: sutro_divi_blog
    active: true
"""

FULL_REGISTRY_YAML = """
companies:
  - company_id: adct
    canonical_name: ADC Therapeutics SA
    official_domain: adctherapeutics.example
    presentations_url: "https://www.adctmedical.example/congresses/"
    presentations_template: adctmedical_congress_listing
    active: true
  - company_id: sutro
    canonical_name: Sutro Biopharma, Inc.
    official_domain: sutrobio.example
    presentations_url: "https://www.sutrobio.example/news/presentations/"
    presentations_template: sutro_divi_blog
    active: true
  - company_id: no_presentations
    canonical_name: NoPresentations Inc.
    official_domain: nopres.example
    presentations_url: null
    active: true
  - company_id: inactive_co
    canonical_name: Inactive Co.
    official_domain: inactive.example
    presentations_url: "https://ir.inactive.example/presentations"
    presentations_template: sutro_divi_blog
    active: false
"""

UNKNOWN_TEMPLATE_YAML = """
companies:
  - company_id: gamma
    canonical_name: Gamma Biosciences, Inc.
    official_domain: gamma.example
    presentations_url: "https://www.gamma.example/science/"
    presentations_template: null
    active: true
"""


def _adctmedical_item(congress, year, title, pdf_url):
    return (
        f"<div class='pub_row  poster gamma {congress} year-{year}'><div class='pub_cont wp-block-columns'>"
        f"<div class='wp-block-column'><h5 class='has-blue-color'>Poster</h5></div>"
        f"<div class='wp-block-column'><h3 class='ltwt has-blue-color'><span>{congress}</span> {year}</h3>"
        f"<div class='pub_title'><p class='larger'>{title}</p></div></div>"
        f"<div class='wp-block-column'><a class='targetfile has-blue-color' href='{pdf_url}' target='_blank'>dl</a></div>"
        f"</div></div>"
    )


def _adctmedical_page(items):
    return "<html><body>" + "".join(items) + "</body></html>"


def _sutro_item(post_id, url, title, date="Aug 13, 2026"):
    return (
        f'<article id="post-{post_id}" class="et_pb_post post type-post status-publish hentry category-presentations">'
        f'<h2 class="entry-title"><a href="{url}">{title}</a></h2>'
        f'<p class="post-meta"><span class="published">{date}</span></p>'
        f"</article>"
    )


def _sutro_page(items):
    return "<html><body>" + "".join(items) + "</body></html>"


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None, company=None, refresh=False,
        output=str(tmp_path / "DATA"), registry_file=str(tmp_path / "registry.yaml"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch, registry_yaml=ADCT_ONLY_YAML):
    (tmp_path / "registry.yaml").write_text(registry_yaml)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)
    import jobs.company_scientific_presentations.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)


def _manifest_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "company_scientific_presentations.parquet")


def _attempts_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "company_scientific_presentations_attempts.parquet")


def _discovery_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "company_scientific_presentations_discovery.parquet")


ONE_ADCT_ITEM_PAGE = _adctmedical_page([
    _adctmedical_item("ASH", 2025, "Lonca Ph 2 Study", "https://www.adctmedical.example/wp-content/uploads/lonca.pdf"),
])
EMPTY_PAGE = "<html><body>no items here</body></html>"


@responses.activate
def test_single_page_template_fetches_exactly_once(tmp_path, monkeypatch):
    """The adctmedical_congress_listing template has NO pagination -- it
    must be fetched exactly once, never looped."""
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 1
    assert len(responses.calls) == 1


@responses.activate
def test_dry_run_does_not_materialize(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "company_scientific_presentations.parquet").exists()


@responses.activate
def test_full_run_writes_manifest_discovery_and_attempts_preserving_congress_not_a_fake_date(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")
    responses.add(
        responses.GET, "https://www.adctmedical.example/wp-content/uploads/lonca.pdf",
        body=b"%PDF-1.4 fake pdf bytes", content_type="application/pdf",
    )

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["company_id"] == "adct"
    assert df.iloc[0]["congress"] == "ASH 2025"
    assert df.iloc[0]["publication_or_release_date"] is None  # no false-precision date fabricated
    assert df.iloc[0]["raw_format"] == "pdf"
    assert df.iloc[0]["version"] == 1

    disc = _discovery_df(tmp_path)
    assert len(disc) == 1
    assert disc.iloc[0]["congress"] == "ASH 2025"

    attempts = _attempts_df(tmp_path)
    assert attempts.iloc[0]["status"] == "success"

    report_text = (tmp_path / "reports" / "acquisition" / "company_scientific_presentations.md").read_text()
    assert "Company Scientific Presentations" in report_text


@responses.activate
def test_wordpress_path_pagination_continues_across_pages(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml=SUTRO_ONLY_YAML)
    page1 = _sutro_page([_sutro_item(i, f"https://www.sutrobio.example/post-{i}/", f"Post {i}") for i in range(3)])
    page2 = _sutro_page([_sutro_item(i, f"https://www.sutrobio.example/post-{i}/", f"Post {i}") for i in range(3, 5)])
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=page1, content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/page/2/", body=page2, content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/page/3/", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 5


@responses.activate
def test_incremental_rerun_stops_early_for_single_page_template(tmp_path, monkeypatch):
    """Same early-stop discipline as Job 12: once an item is genuinely
    resolved, it never re-enters this run's scope on an ordinary run at
    all (0 discovered, not even fast-skipped) -- only --refresh re-walks
    it. Still just one HTTP call (the listing re-fetch; no PDF re-fetch)."""
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")
    responses.add(
        responses.GET, "https://www.adctmedical.example/wp-content/uploads/lonca.pdf",
        body=b"%PDF-1.4 fake pdf bytes", content_type="application/pdf",
    )
    CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert result.records_skipped_unchanged == 0
    assert len(responses.calls) == 1  # only the listing re-fetch -- no re-download of the PDF


@responses.activate
def test_off_presentations_domain_item_excluded(tmp_path, monkeypatch):
    """Anchored to presentations_url's OWN host, not official_domain --
    an item pointing off that host (e.g. a syndication mirror) is
    excluded, but the registered presentations_url's own domain
    (adctmedical.example, deliberately DIFFERENT from official_domain
    adctherapeutics.example in this fixture) is correctly accepted."""
    _setup(tmp_path, monkeypatch)
    mixed_page = _adctmedical_page([
        _adctmedical_item("ASH", 2025, "On Our Own Domain", "https://www.adctmedical.example/wp-content/uploads/ours.pdf"),
        _adctmedical_item("ASH", 2025, "Syndicated Copy", "https://someothersite.example/mirror.pdf"),
    ])
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=mixed_page, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 1


@responses.activate
def test_unchanged_content_skipped_on_rerun(tmp_path, monkeypatch):
    """Same early-stop discipline as Job 12: an already-resolved item
    never re-enters this run's scope at all on an ordinary rerun (the
    pagination walk sees it's already known and stops immediately)."""
    _setup(tmp_path, monkeypatch, registry_yaml=SUTRO_ONLY_YAML)
    page = _sutro_page([_sutro_item(1, "https://www.sutrobio.example/post-1/", "Post 1")])
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=page, content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/page/2/", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/post-1/", body=b"<html>unchanged</html>", content_type="text/html")
    CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=page, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert result.records_skipped_unchanged == 0


@responses.activate
def test_refresh_rediscovers_and_reverifies(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")
    responses.add(
        responses.GET, "https://www.adctmedical.example/wp-content/uploads/lonca.pdf",
        body=b"%PDF-1.4 v1", content_type="application/pdf",
    )
    CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")
    responses.add(
        responses.GET, "https://www.adctmedical.example/wp-content/uploads/lonca.pdf",
        body=b"%PDF-1.4 v2 changed", content_type="application/pdf",
    )

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, refresh=True))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert sorted(df["version"]) == [1, 2]


@responses.activate
def test_failed_fetch_is_retried_on_next_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://www.adctmedical.example/wp-content/uploads/lonca.pdf", status=500)
    result1 = CompanyScientificPresentationsJob().run(_base_args(tmp_path))
    assert result1.records_failed == 1
    assert _manifest_df(tmp_path).empty  # write_manifest always writes the file; a failure just contributes 0 rows

    responses.reset()
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")
    responses.add(
        responses.GET, "https://www.adctmedical.example/wp-content/uploads/lonca.pdf",
        body=b"%PDF-1.4 recovered", content_type="application/pdf",
    )
    result2 = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 1


@responses.activate
def test_since_until_never_excludes_undated_adct_items(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True, since="2099-01-01"))

    assert result.records_discovered == 1


@responses.activate
def test_limit_caps_materialization(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    page = _adctmedical_page([
        _adctmedical_item("ASH", 2025, "Item A", "https://www.adctmedical.example/wp-content/uploads/a.pdf"),
        _adctmedical_item("ASH", 2025, "Item B", "https://www.adctmedical.example/wp-content/uploads/b.pdf"),
    ])
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=page, content_type="text/html")
    responses.add(responses.GET, "https://www.adctmedical.example/wp-content/uploads/a.pdf", body=b"%PDF a", content_type="application/pdf")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, limit=1))

    assert result.records_discovered == 2
    assert result.records_downloaded == 1


@responses.activate
def test_unknown_template_company_still_attempts_and_records_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml=UNKNOWN_TEMPLATE_YAML)
    responses.add(responses.GET, "https://www.gamma.example/science/", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 0
    assert any("UNKNOWN_TEMPLATE" in n for n in result.notes)


@responses.activate
def test_first_page_parse_zero_flagged_as_discovery_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 0
    assert any("FIRST_PAGE_PARSE_ZERO" in n for n in result.notes)


@responses.activate
def test_discovery_failure_isolated_per_company(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml=FULL_REGISTRY_YAML)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", status=500)
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=_sutro_page([_sutro_item(1, "https://www.sutrobio.example/post-1/", "Post 1")]), content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/page/2/", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 1  # sutro's own discovery unaffected by adct's failure
    assert any("adct:HTTP_NON_200" in n for n in result.notes)


def test_empty_registry_raises_clear_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml="companies: []\n")
    try:
        CompanyScientificPresentationsJob().run(_base_args(tmp_path))
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "no active companies" in str(exc)


@responses.activate
def test_company_filter_selects_single_company(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml=FULL_REGISTRY_YAML)
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=_sutro_page([_sutro_item(1, "https://www.sutrobio.example/post-1/", "Post 1")]), content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/page/2/", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True, company="sutro"))

    assert result.queries_run == 1
    assert result.records_discovered == 1


SUTRO_DETAIL_WITH_ARTIFACT = (
    b"<html><body><article><h1>AACR 2026 Presentation</h1>"
    b'<p>Download, <a class="et_pb_button" href="https://www.sutrobio.example/wp-content/uploads/2026/04/'
    b'Sutro-AACR-2026-Poster-FINAL.pdf" target="_blank">Poster</a></p>'
    b'<p><a href="https://www.sutrobio.example/wp-content/uploads/2026/01/'
    b'Sutro-Biopharma-Visitors-Guide.pdf" title="VISITOR GUIDE">VISITOR GUIDE</a></p>'
    b"</article></body></html>"
)
SUTRO_DETAIL_NO_ARTIFACT = b"<html><body><article><h1>Sutro to Present at a Conference</h1><p>Details soon.</p></article></body></html>"
SUTRO_DETAIL_WITH_TWO_ARTIFACTS = (
    b"<html><body><article><h1>World ADC 2024 -- Presentations</h1>"
    b'<p><a href="https://www.sutrobio.example/wp-content/uploads/2024/11/Author-One.pdf">Poster 1</a></p>'
    b'<p><a href="https://www.sutrobio.example/wp-content/uploads/2024/11/Author-Two.pdf">Poster 2</a></p>'
    b"</article></body></html>"
)


SUTRO_ONE_ITEM_PAGE = _sutro_page([_sutro_item(1, "https://www.sutrobio.example/post-1/", "Post 1")])


def _sutro_setup_with_one_listing_item(tmp_path, monkeypatch, detail_body):
    _setup(tmp_path, monkeypatch, registry_yaml=SUTRO_ONLY_YAML)
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=SUTRO_ONE_ITEM_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/page/2/", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/post-1/", body=detail_body, content_type="text/html")


@responses.activate
def test_sutro_detail_with_one_artifact_materializes_pdf_child(tmp_path, monkeypatch):
    """The reviewer's required scenario: a Sutro HTML detail page that
    contains one presentation PDF -- the HTML parent must still succeed,
    the PDF must be materialized as a separate child with the correct
    parent_record_id, and the sitewide 'Visitors Guide' footer PDF must
    NOT be mistaken for the primary artifact."""
    _sutro_setup_with_one_listing_item(tmp_path, monkeypatch, SUTRO_DETAIL_WITH_ARTIFACT)
    responses.add(
        responses.GET, "https://www.sutrobio.example/wp-content/uploads/2026/04/Sutro-AACR-2026-Poster-FINAL.pdf",
        body=b"%PDF-1.4 poster bytes", content_type="application/pdf",
    )

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 2  # parent HTML + 1 artifact PDF child
    df = _manifest_df(tmp_path)
    assert len(df) == 2
    parent = df[df["source_record_type"] == "company_scientific_presentation"].iloc[0]
    child = df[df["source_record_type"] == "company_scientific_presentation_artifact"].iloc[0]
    assert pd.isna(parent["parent_record_id"])
    assert child["parent_record_id"] == parent["source_record_id"]
    assert child["url"] == "https://www.sutrobio.example/wp-content/uploads/2026/04/Sutro-AACR-2026-Poster-FINAL.pdf"
    assert "Visitors-Guide" not in child["url"]


@responses.activate
def test_sutro_detail_with_no_artifact_leaves_html_parent_as_sole_record(tmp_path, monkeypatch):
    """The reviewer's other required scenario: a Sutro HTML detail page
    with no primary artifact -- the HTML remains the successful
    acquisition artifact, and no child is fabricated."""
    _sutro_setup_with_one_listing_item(tmp_path, monkeypatch, SUTRO_DETAIL_NO_ARTIFACT)

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["source_record_type"] == "company_scientific_presentation"
    assert pd.isna(df.iloc[0]["parent_record_id"])


@responses.activate
def test_sutro_detail_with_multiple_artifacts_materializes_all_as_children(tmp_path, monkeypatch):
    _sutro_setup_with_one_listing_item(tmp_path, monkeypatch, SUTRO_DETAIL_WITH_TWO_ARTIFACTS)
    responses.add(
        responses.GET, "https://www.sutrobio.example/wp-content/uploads/2024/11/Author-One.pdf",
        body=b"%PDF-1.4 one", content_type="application/pdf",
    )
    responses.add(
        responses.GET, "https://www.sutrobio.example/wp-content/uploads/2024/11/Author-Two.pdf",
        body=b"%PDF-1.4 two", content_type="application/pdf",
    )

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 3  # parent HTML + 2 artifact PDF children
    df = _manifest_df(tmp_path)
    children = df[df["source_record_type"] == "company_scientific_presentation_artifact"]
    assert len(children) == 2
    assert set(children["parent_record_id"]) == {df[df["source_record_type"] == "company_scientific_presentation"].iloc[0]["source_record_id"]}


@responses.activate
def test_artifact_fetch_failure_does_not_erase_successful_html_parent(tmp_path, monkeypatch):
    _sutro_setup_with_one_listing_item(tmp_path, monkeypatch, SUTRO_DETAIL_WITH_ARTIFACT)
    responses.add(
        responses.GET, "https://www.sutrobio.example/wp-content/uploads/2026/04/Sutro-AACR-2026-Poster-FINAL.pdf",
        status=500,
    )

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1  # the HTML parent only
    assert result.records_failed == 1  # the artifact child only
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["source_record_type"] == "company_scientific_presentation"
    assert df.iloc[0]["download_status"] == "success"


@responses.activate
def test_off_domain_artifact_link_excluded(tmp_path, monkeypatch):
    detail_with_off_domain_pdf = (
        b"<html><body><article><h1>Presentation</h1>"
        b'<p><a href="https://someothersite.example/wp-content/uploads/2026/04/mirror.pdf">Poster</a></p>'
        b"</article></body></html>"
    )
    _sutro_setup_with_one_listing_item(tmp_path, monkeypatch, detail_with_off_domain_pdf)

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1  # the HTML parent only -- off-domain link never fetched
    df = _manifest_df(tmp_path)
    assert len(df) == 1


@responses.activate
def test_adct_single_page_template_never_attempts_artifact_extraction(tmp_path, monkeypatch):
    """adctmedical_congress_listing items are already direct PDFs and have
    no registered ARTIFACT_PARSERS entry -- the new artifact machinery
    must not touch this template at all."""
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")
    responses.add(
        responses.GET, "https://www.adctmedical.example/wp-content/uploads/lonca.pdf",
        body=b"%PDF-1.4 fake pdf bytes", content_type="application/pdf",
    )

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["source_record_type"] == "company_scientific_presentation"


@responses.activate
def test_artifact_already_resolved_fast_skipped_with_no_request_on_rerun(tmp_path, monkeypatch):
    """Once an artifact child is resolved, an ordinary (non-refresh)
    rerun must not re-fetch it -- same discipline as the parent's own
    fast-skip."""
    _sutro_setup_with_one_listing_item(tmp_path, monkeypatch, SUTRO_DETAIL_WITH_ARTIFACT)
    responses.add(
        responses.GET, "https://www.sutrobio.example/wp-content/uploads/2026/04/Sutro-AACR-2026-Poster-FINAL.pdf",
        body=b"%PDF-1.4 poster bytes", content_type="application/pdf",
    )
    CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=SUTRO_ONE_ITEM_PAGE, content_type="text/html")
    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    assert len(responses.calls) == 1  # only the listing re-fetch -- no re-request for the parent HTML or the child PDF


@responses.activate
def test_report_sutro_parent_count_dedupes_multi_version_records(tmp_path, monkeypatch):
    """A parent whose own detail-page content genuinely changes between
    runs gets a second version ROW in the manifest -- the report's Sutro
    parent count must dedupe by source_record_id, not count manifest
    rows, or a single presentation with 2 content versions would be
    double-counted as 2 presentations."""
    _sutro_setup_with_one_listing_item(tmp_path, monkeypatch, SUTRO_DETAIL_NO_ARTIFACT)
    CompanyScientificPresentationsJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=SUTRO_ONE_ITEM_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/post-1/", body=SUTRO_DETAIL_NO_ARTIFACT + b"<!-- changed -->", content_type="text/html")
    CompanyScientificPresentationsJob().run(_base_args(tmp_path, refresh=True))

    df = _manifest_df(tmp_path)
    assert sorted(df["version"]) == [1, 2]  # genuinely 2 content versions of the SAME presentation
    report_text = (tmp_path / "reports" / "acquisition" / "company_scientific_presentations.md").read_text()
    assert "1 Sutro presentation-category listing/detail records" in report_text


@responses.activate
def test_inactive_and_no_presentations_url_companies_excluded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml=FULL_REGISTRY_YAML)
    responses.add(responses.GET, "https://www.adctmedical.example/congresses/", body=ONE_ADCT_ITEM_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://www.sutrobio.example/news/presentations/", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyScientificPresentationsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.queries_run == 2  # adct + sutro only -- no_presentations and inactive_co excluded
