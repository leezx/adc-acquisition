import argparse

import pandas as pd
import responses

from adc_acquisition import http_utils
from jobs.company_press_release.job import CompanyPressReleaseJob

ACME_ONLY_YAML = """
companies:
  - company_id: acme
    canonical_name: Acme Therapeutics, Inc.
    official_domain: acme.example
    press_release_url: "https://ir.acme.example/news"
    press_release_template: workiva_ir_newsroom
    active: true
"""

BETA_ONLY_YAML = """
companies:
  - company_id: beta
    canonical_name: Beta Biopharma, Inc.
    official_domain: beta.example
    press_release_url: "https://ir.beta.example/press-releases"
    press_release_template: q4_ir_media
    active: true
"""

FULL_REGISTRY_YAML = """
companies:
  - company_id: acme
    canonical_name: Acme Therapeutics, Inc.
    official_domain: acme.example
    press_release_url: "https://ir.acme.example/news"
    press_release_template: workiva_ir_newsroom
    active: true
  - company_id: beta
    canonical_name: Beta Biopharma, Inc.
    official_domain: beta.example
    press_release_url: "https://ir.beta.example/press-releases"
    press_release_template: q4_ir_media
    active: true
  - company_id: no_releases
    canonical_name: NoReleases Inc.
    official_domain: noreleases.example
    press_release_url: null
    active: true
  - company_id: inactive_co
    canonical_name: Inactive Co.
    official_domain: inactive.example
    press_release_url: "https://ir.inactive.example/news"
    press_release_template: workiva_ir_newsroom
    active: false
"""

UNKNOWN_TEMPLATE_YAML = """
companies:
  - company_id: gamma
    canonical_name: Gamma Biosciences, Inc.
    official_domain: gamma.example
    press_release_url: "https://ir.gamma.example/news"
    press_release_template: null
    active: true
"""


def _workiva_item(url, headline, date="Aug 13, 2026"):
    return (
        f'<li class="wd_item">\n<div class="wd_item_wrapper">\n'
        f'\t<div class="wd_date">{date}</div>\n'
        f'\t<div class="wd_title"><a href="{url}">{headline}</a></div>\n'
        f"</div>\n</li>"
    )


def _workiva_page(items):
    return "<html><body><ul>" + "".join(items) + "</ul></body></html>"


def _q4_item(url, headline, iso_date="2026-08-12T07:00:00"):
    return (
        '<article class="media">\n<div class="row">\n<div class="media-body col-md">\n'
        '<div class="date">\n<time datetime="'
        + iso_date
        + '">rendered</time>\n</div>\n'
        '<div class="media-heading">\n<a href="' + url + '">\n' + headline + "\n</a>\n</div>\n</div>\n</article>"
    )


def _q4_page(items):
    return "<html><body>" + "".join(items) + "</body></html>"


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None, company=None, refresh=False,
        output=str(tmp_path / "DATA"), registry_file=str(tmp_path / "registry.yaml"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch, registry_yaml=ACME_ONLY_YAML):
    (tmp_path / "registry.yaml").write_text(registry_yaml)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)
    import jobs.company_press_release.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)


def _manifest_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "company_press_release.parquet")


def _attempts_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "company_press_release_attempts.parquet")


def _discovery_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "company_press_release_discovery.parquet")


ONE_RELEASE_PAGE = _workiva_page([_workiva_item("https://ir.acme.example/2026-08-13-Acme-Reports-Results", "Acme Reports Results")])
EMPTY_PAGE = "<html><body>no items here</body></html>"


@responses.activate
def test_dry_run_does_not_materialize(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 1
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "company_press_release.parquet").exists()


@responses.activate
def test_full_run_writes_manifest_discovery_and_attempts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html><title>ignored</title>body</html>", content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["company_id"] == "acme"
    assert df.iloc[0]["title"] == "Acme Reports Results"
    assert df.iloc[0]["publication_or_release_date"] == "2026-08-13"
    assert df.iloc[0]["version"] == 1

    disc = _discovery_df(tmp_path)
    assert len(disc) == 1
    assert disc.iloc[0]["company_id"] == "acme"

    attempts = _attempts_df(tmp_path)
    assert attempts.iloc[0]["status"] == "success"

    report_text = (tmp_path / "reports" / "acquisition" / "company_press_release.md").read_text()
    assert "Company Press Releases (Job 12)" in report_text


@responses.activate
def test_pagination_continues_across_pages(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    page0 = _workiva_page([_workiva_item(f"https://ir.acme.example/release-{i}", f"Release {i}", date="Aug 10, 2026") for i in range(3)])
    page3 = _workiva_page([_workiva_item(f"https://ir.acme.example/release-{i}", f"Release {i}", date="Aug 5, 2026") for i in range(3, 5)])
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=page0, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=3", body=page3, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=5", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 5


@responses.activate
def test_incremental_rerun_stops_early_and_discovers_nothing_new(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    responses.reset()
    # If the job requested o=0 again, this fixture would be consumed --
    # asserting only 1 call happened proves the early-stop worked.
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert len(responses.calls) == 1  # only the one o=0 discovery request -- no detail refetch, no further pages


@responses.activate
def test_wraparound_pagination_stops_via_known_items_not_empty_page(tmp_path, monkeypatch):
    """Mirrors Sutro/Pfizer's live-verified behavior: requesting past the
    real end returns the SAME page again (clamp/wrap) instead of an empty
    page. The job must still stop, not loop until MAX_PAGES."""
    _setup(tmp_path, monkeypatch, registry_yaml=BETA_ONLY_YAML)
    page1_items = [_q4_item(f"https://ir.beta.example/detail/{i}", f"Beta Release {i}") for i in range(2)]
    page1 = _q4_page(page1_items)
    responses.add(responses.GET, "https://ir.beta.example/press-releases?page=1", body=page1, content_type="text/html")
    # page=2 wraps back to page 1's exact content instead of emptying out.
    responses.add(responses.GET, "https://ir.beta.example/press-releases?page=2", body=page1, content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 2
    # page=1 (discovery) + page=2 (wraps, detects nothing new, stops) = 2 calls, not a runaway loop.
    assert len(responses.calls) == 2


@responses.activate
def test_off_domain_listing_item_excluded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    mixed_page = _workiva_page([
        _workiva_item("https://ir.acme.example/2026-08-13-Acme-Owns-This", "Acme Owns This"),
        _workiva_item("https://businesswire.com/2026-08-13-Wire-Copy", "Wire Copy Of The Same Release"),
    ])
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=mixed_page, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=2", body=EMPTY_PAGE, content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path, dry_run=True))

    assert result.records_discovered == 1  # the businesswire.com item is excluded


@responses.activate
def test_unchanged_content_skipped_on_rerun(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>v1</html>", content_type="text/html")
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    result = CompanyPressReleaseJob().run(_base_args(tmp_path))

    # already-known this run (no new discovery), so nothing to materialize --
    # it was already resolved from run 1 and never re-enters scope.
    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["version"] == 1


@responses.activate
def test_refresh_rediscovers_and_reverifies_with_changed_content(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>v1</html>", content_type="text/html")
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>v2 CORRECTED</html>", content_type="text/html")
    result = CompanyPressReleaseJob().run(_base_args(tmp_path, refresh=True))

    assert result.records_discovered == 1  # --refresh disables the early-stop, rediscovers it
    assert result.records_downloaded == 1  # content genuinely changed -> new version, not skipped_unchanged
    df = _manifest_df(tmp_path)
    versions = sorted(df["version"])
    assert versions == [1, 2]


@responses.activate
def test_refresh_skips_unchanged_content_with_no_request(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>v1</html>", content_type="text/html")
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>v1</html>", content_type="text/html")
    result = CompanyPressReleaseJob().run(_base_args(tmp_path, refresh=True))

    assert result.records_discovered == 1  # rediscovered (refresh disables early-stop)
    assert result.records_downloaded == 0
    assert result.records_skipped_unchanged == 1  # unchanged content, already resolved -> genuine no-op
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["version"] == 1


@responses.activate
def test_failed_fetch_is_retried_on_next_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    for _ in range(5):
        responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", status=500)
    result1 = CompanyPressReleaseJob().run(_base_args(tmp_path))
    assert result1.records_failed == 1

    responses.reset()
    # A failed release is NOT "known" for the early-stop's purposes (only
    # a genuinely RESOLVED release is -- see
    # _known_resolved_urls_by_company's docstring), so discovery keeps
    # walking past page 0 exactly as it did on the very first run, and the
    # release re-enters hits_by_id to be retried.
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")
    result2 = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result2.records_discovered == 1  # re-entered scope WITHOUT --refresh, unlike a resolved release
    assert result2.records_downloaded == 1


@responses.activate
def test_stale_ledger_recovers_without_bumping_version(tmp_path, monkeypatch):
    """Reproduces the same crash-recovery invariant Job 10 (EPO)'s round-1
    review required: a --refresh run writes raw v1 (checkpoint durable)
    but the manifest/attempts ledger flush never happens (simulated by
    deleting them after the fact) -- the NEXT run must recover the
    missing row without bumping the version or re-trusting a stale
    resolved status."""
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    # Simulate the crash: checkpoint (raw_records namespace) already
    # durable, but manifest+attempts ledger flush never happened.
    (tmp_path / "DATA" / "manifests" / "company_press_release.parquet").unlink()
    (tmp_path / "DATA" / "manifests" / "company_press_release_attempts.parquet").unlink()

    responses.reset()
    # --refresh so discovery re-walks (otherwise the already-known URL
    # would never re-enter scope at all, per the early-stop rule).
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")
    result = CompanyPressReleaseJob().run(_base_args(tmp_path, refresh=True))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["version"] == 1
    attempts = _attempts_df(tmp_path)
    assert attempts.iloc[0]["status"] == "success"


@responses.activate
def test_since_until_filters_materialization_not_discovery(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    page = _workiva_page([
        _workiva_item("https://ir.acme.example/release-new", "New Release", date="Aug 13, 2026"),
        _workiva_item("https://ir.acme.example/release-old", "Old Release", date="Jan 5, 2020"),
    ])
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=page, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=2", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/release-new", body=b"<html>new</html>", content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path, since="2025-01-01"))

    assert result.records_discovered == 2  # discovery finds both regardless of --since
    assert result.records_downloaded == 1  # only the in-range one is materialized
    df = _manifest_df(tmp_path)
    assert set(df["title"]) == {"New Release"}


@responses.activate
def test_limit_prioritizes_fresh_over_backlog(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    for _ in range(5):
        responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", status=500)
    CompanyPressReleaseJob().run(_base_args(tmp_path))  # acme's one release fails -> backlog

    responses.reset()
    two_item_page = _workiva_page([
        _workiva_item("https://ir.acme.example/2026-08-13-Acme-Reports-Results", "Acme Reports Results"),
        _workiva_item("https://ir.acme.example/release-fresh", "Fresh Release", date="Aug 14, 2026"),
    ])
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=two_item_page, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=2", body=EMPTY_PAGE, content_type="text/html")
    for _ in range(5):
        responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", status=500)
    responses.add(responses.GET, "https://ir.acme.example/release-fresh", body=b"<html>fresh</html>", content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert set(df["title"]) == {"Fresh Release"}  # fresh got the single slot, not acme's backlog retry


@responses.activate
def test_unknown_template_company_still_attempts_and_records_failure(tmp_path, monkeypatch):
    """Mirrors the live-verified Zymeworks case: a registered
    press_release_url with no known press_release_template (page
    currently unreachable/never observed) must still attempt a fetch so
    failures are recorded normally, and must not crash the run. Round-1
    fix: this must now be a STRUCTURED discovery failure (visible in
    result.notes), not just a log line -- a listing failure looking
    identical to "0 new releases found" is exactly what round-1 review
    flagged."""
    _setup(tmp_path, monkeypatch, registry_yaml=UNKNOWN_TEMPLATE_YAML)
    responses.add(responses.GET, "https://ir.gamma.example/news", status=500)

    result = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert result.records_failed == 0  # not a materialization attempt -- no attempts-ledger row, just a logged failure
    assert any("gamma" in n and "HTTP_NON_200" in n for n in result.notes)


@responses.activate
def test_discovery_failure_isolated_per_company(tmp_path, monkeypatch):
    """Round-1 fix: one company's listing fetch failing entirely must
    NOT abort other companies' discovery or block materializing whatever
    they successfully found, and must be reported as a structured,
    per-company discovery failure -- not silently look like "no new
    releases this run"."""
    _setup(tmp_path, monkeypatch, registry_yaml=FULL_REGISTRY_YAML)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")
    responses.add(responses.GET, "https://ir.beta.example/press-releases?page=1", status=500)

    result = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1  # acme's release still materialized despite beta's discovery failure
    df = _manifest_df(tmp_path)
    assert set(df["company_id"]) == {"acme"}
    assert any("beta" in n and "HTTP_NON_200" in n for n in result.notes)


@responses.activate
def test_first_page_parse_zero_flagged_as_discovery_failure(tmp_path, monkeypatch):
    """Round-1 fix: a KNOWN template's first page parsing to ZERO items
    (e.g. the site changed its markup) must be flagged as a discovery
    failure, not silently treated as "0 new releases this run" -- the
    exact silent-failure risk round-1 review flagged."""
    _setup(tmp_path, monkeypatch)
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=0",
        body="<html><body>totally different markup, no wd_item here at all</body></html>",
        content_type="text/html",
    )

    result = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert any("FIRST_PAGE_PARSE_ZERO" in n for n in result.notes)


@responses.activate
def test_manifest_discovery_attempts_query_provenance_consistent(tmp_path, monkeypatch):
    """Round-1 fix: the manifest's query_text must match the discovery
    and attempts ledgers' query_text for the SAME query_id (the company's
    listing query) -- it must not silently substitute the release's own
    detail-page URL, which is already preserved verbatim in the
    manifest's own `url` field."""
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    manifest = _manifest_df(tmp_path)
    disc = _discovery_df(tmp_path)
    attempts = _attempts_df(tmp_path)

    assert manifest.iloc[0]["query_id"] == disc.iloc[0]["query_id"] == attempts.iloc[0]["query_id"] == "PRESSRELEASE_LISTING_ACME"
    assert manifest.iloc[0]["query_text"] == disc.iloc[0]["query_text"] == attempts.iloc[0]["query_text"] == "https://ir.acme.example/news"
    assert manifest.iloc[0]["url"] == "https://ir.acme.example/2026-08-13-Acme-Reports-Results"


@responses.activate
def test_backlog_release_behind_resolved_page_still_retried_without_refresh(tmp_path, monkeypatch):
    """Reproduces round-1's blocker #1 exactly: an old FAILED backlog
    release ends up sitting BEHIND a page containing only genuinely
    resolved releases -- an ordinary run's live pagination early-stops at
    that resolved page and never reaches the backlog release's own page,
    yet it must still be retried this run (reconstructed directly from
    the discovery ledger's own stored headline/date, not re-discovered
    via pagination)."""
    _setup(tmp_path, monkeypatch)

    # Run 1 (week 1): only release-1 exists; its materialization fails.
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=0",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-1", "Release 1", date="Aug 1, 2026")]),
        content_type="text/html",
    )
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/release-1", status=500)
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    # Run 2 (week 2): release-2 published (newer, ahead of release-1);
    # release-2 materializes successfully, release-1 still fails.
    responses.reset()
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=0",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-2", "Release 2", date="Aug 8, 2026")]),
        content_type="text/html",
    )
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=1",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-1", "Release 1", date="Aug 1, 2026")]),
        content_type="text/html",
    )
    responses.add(responses.GET, "https://ir.acme.example/news?o=2", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/release-2", body=b"<html>r2</html>", content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/release-1", status=500)
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    # Run 3 (week 3): release-3 published (newest); release-2 is now
    # RESOLVED and sits alone on its own page ahead of release-1 (still
    # unresolved). An ordinary run's live pagination early-stops at o=1
    # (release-2, fully resolved) and never reaches o=2 (release-1) --
    # o=2 is deliberately NOT registered with `responses` below, so this
    # test would fail with a connection error if the job tried to fetch
    # it, proving the early-stop behaved as designed.
    responses.reset()
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=0",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-3", "Release 3", date="Aug 15, 2026")]),
        content_type="text/html",
    )
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=1",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-2", "Release 2", date="Aug 8, 2026")]),
        content_type="text/html",
    )
    responses.add(responses.GET, "https://ir.acme.example/release-3", body=b"<html>r3</html>", content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/release-1", body=b"<html>r1 finally fixed</html>", content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 2  # release-3 (fresh) AND release-1 (backlog, resurrected)
    df = _manifest_df(tmp_path)
    assert set(df["title"]) == {"Release 1", "Release 2", "Release 3"}


@responses.activate
def test_limit_omitted_release_still_retried_after_being_pushed_behind_resolved_page(tmp_path, monkeypatch):
    """Reproduces round-1's blocker #1 scenario B: a release discovered
    but never attempted at all due to --limit truncation (no
    attempts-ledger row whatsoever, not even a failure) must still be
    retried on a LATER ordinary run, even after new releases push it
    behind an otherwise-fully-resolved page.

    NOTE: `--limit` truncation picks fresh_ids in source_record_id-sorted
    (hash) order, NOT listing/date order -- verified directly that
    "release-b"'s hash sorts before "release-a"'s for company_id=acme, so
    release-b is the one materialized under limit=1 here, not release-a."""
    _setup(tmp_path, monkeypatch)

    # Run 1: release-a and release-b both discovered; --limit=1 lets only
    # release-b materialize (hash-sort order, see docstring). release-a
    # is discovered but never attempted at all this run.
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=0",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-a", "Release A", date="Aug 5, 2026")]),
        content_type="text/html",
    )
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=1",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-b", "Release B", date="Aug 1, 2026")]),
        content_type="text/html",
    )
    responses.add(responses.GET, "https://ir.acme.example/news?o=2", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/release-b", body=b"<html>b</html>", content_type="text/html")
    result1 = CompanyPressReleaseJob().run(_base_args(tmp_path, limit=1))
    assert result1.records_downloaded == 1
    df1 = _manifest_df(tmp_path)
    assert set(df1["title"]) == {"Release B"}

    # Run 2: release-new is published (newest); release-b is now fully
    # resolved and sits alone on its own page ahead of release-a -- an
    # ordinary run's live pagination early-stops there and never reaches
    # release-a's page (deliberately NOT registered with `responses`
    # below).
    responses.reset()
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=0",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-new", "Release New", date="Aug 10, 2026")]),
        content_type="text/html",
    )
    responses.add(
        responses.GET, "https://ir.acme.example/news?o=1",
        body=_workiva_page([_workiva_item("https://ir.acme.example/release-b", "Release B", date="Aug 1, 2026")]),
        content_type="text/html",
    )
    responses.add(responses.GET, "https://ir.acme.example/release-new", body=b"<html>new</html>", content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/release-a", body=b"<html>a finally</html>", content_type="text/html")

    result2 = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 2  # release-new (fresh) AND release-a (never-attempted backlog, resurrected)
    df2 = _manifest_df(tmp_path)
    assert set(df2["title"]) == {"Release A", "Release B", "Release New"}


@responses.activate
def test_query_id_deterministic_and_stable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")
    CompanyPressReleaseJob().run(_base_args(tmp_path))

    disc = _discovery_df(tmp_path)
    attempts = _attempts_df(tmp_path)
    assert disc.iloc[0]["query_id"] == "PRESSRELEASE_LISTING_ACME"
    assert attempts.iloc[0]["query_id"] == "PRESSRELEASE_LISTING_ACME"


@responses.activate
def test_empty_registry_raises_clear_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml="companies: []")

    try:
        CompanyPressReleaseJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised


@responses.activate
def test_company_filter_selects_single_company(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml=FULL_REGISTRY_YAML)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")

    result = CompanyPressReleaseJob().run(_base_args(tmp_path, company="acme"))

    assert result.queries_run == 1
    df = _manifest_df(tmp_path)
    assert set(df["company_id"]) == {"acme"}


@responses.activate
def test_inactive_and_no_release_url_companies_excluded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml=FULL_REGISTRY_YAML)
    responses.add(responses.GET, "https://ir.acme.example/news?o=0", body=ONE_RELEASE_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/news?o=1", body=EMPTY_PAGE, content_type="text/html")
    responses.add(responses.GET, "https://ir.acme.example/2026-08-13-Acme-Reports-Results", body=b"<html>body</html>", content_type="text/html")
    responses.add(responses.GET, "https://ir.beta.example/press-releases?page=1", body=_q4_page([]), content_type="text/html")
    # inactive_co's URL deliberately NOT registered with `responses` -- if
    # the job tried to fetch it, this test would fail with a ConnectionError.

    result = CompanyPressReleaseJob().run(_base_args(tmp_path))

    assert result.queries_run == 2  # acme + beta only; no_releases and inactive_co excluded
