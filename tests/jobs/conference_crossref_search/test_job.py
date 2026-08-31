import argparse
import json
import re
from urllib.parse import parse_qs, urlparse

import pandas as pd
import responses

from jobs.conference_crossref_search.client import CROSSREF_BASE
from jobs.conference_crossref_search.job import ConferenceCrossrefSearchJob

CONFIG_YAML = """
conferences:
  - conference_id: FAKE_A
    query_id_prefix: CONFERENCE_CROSSREF_FAKE_A
    query_version: 1
    container_title: "Fake Journal A"
    issn: ["1111-1111"]
    signature_type: volume_issue_map
    signature_value:
      - "1:S1"
      - "1:S2"
    active: true
    purpose: test
  - conference_id: FAKE_B
    query_id_prefix: CONFERENCE_CROSSREF_FAKE_B
    query_version: 1
    container_title: "Fake Journal B"
    issn: ["2222-2222"]
    signature_type: doi_suffix_contains
    signature_value: "confb"
    active: true
    purpose: test

adc_query_terms:
  - "term1"
  - "term2"
"""

CONFIG_YAML_ONE_TERM = CONFIG_YAML.replace('  - "term2"\n', "")

CONFIG_YAML_INACTIVE = CONFIG_YAML.replace("active: true", "active: false")

CONFIG_YAML_NO_TERMS = """
conferences:
  - conference_id: FAKE_A
    query_id_prefix: CONFERENCE_CROSSREF_FAKE_A
    query_version: 1
    container_title: "Fake Journal A"
    issn: ["1111-1111"]
    signature_type: volume_issue_map
    signature_value:
      - "1:S1"
      - "1:S2"
    active: true
    purpose: test

adc_query_terms: []
"""


def _item(doi, title, issue=None, page=None, container_title="Fake Journal", published_year=2026, volume=None):
    msg = {"DOI": doi, "title": [title], "container-title": [container_title], "publisher": "Pub",
           "published": {"date-parts": [[published_year, 5]]}}
    if issue is not None:
        msg["issue"] = issue
    if page is not None:
        msg["page"] = page
    if volume is not None:
        msg["volume"] = volume
    return msg


A1 = _item("10.9/a1", "A1 term1", issue="S1", page="10-11", volume="1")
A2_REJECTED = _item("10.9/a2", "A2 rejected", issue="7", page="1-2", volume="1")
A3 = _item("10.9/a3", "A3 term2 only", issue="S2", page="20-21", volume="1")
B1_CONFB = _item("10.9/confb-1", "B1 confb", issue="9_Supplement", page="5-5")
B2_REJECTED = _item("10.9/other-2", "B2 not confb", issue="9_Supplement", page="6-6")


def _register_search(fixtures, extra_fixtures=None):
    """fixtures: dict[(filter_str, term, cursor)] -> list[item dicts]"""
    all_fixtures = dict(fixtures)
    if extra_fixtures:
        all_fixtures.update(extra_fixtures)

    def _callback(request):
        qs = parse_qs(urlparse(request.url).query)
        filter_str = qs.get("filter", [""])[0]
        term = qs.get("query.bibliographic", [""])[0]
        cursor = qs.get("cursor", ["*"])[0]
        key = (filter_str, term, cursor)
        items = all_fixtures.get(key, [])
        next_cursor = None
        if isinstance(items, tuple):
            items, next_cursor = items
        body = json.dumps({"message": {"items": items, "total-results": len(items), "next-cursor": next_cursor}})
        return (200, {}, body)

    responses.add_callback(responses.GET, re.compile(rf"{re.escape(CROSSREF_BASE)}/works.*"), callback=_callback)


BASE_FIXTURES = {
    ("issn:1111-1111", "term1", "*"): [A1, A2_REJECTED],
    ("issn:1111-1111", "term2", "*"): [A1, A3],
    ("issn:2222-2222", "term1", "*"): [B1_CONFB, B2_REJECTED],
    ("issn:2222-2222", "term2", "*"): [],
}


def _base_args(tmp_path, config_text=CONFIG_YAML, **overrides):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_text)
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), config_file=str(config_path), mailto=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _manifest_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_crossref_search.parquet")


def _discovery_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_crossref_search_discovery.parquet")


@responses.activate
def test_basic_materialization_and_signature_filtering(tmp_path):
    _register_search(BASE_FIXTURES)
    result = ConferenceCrossrefSearchJob().run(_base_args(tmp_path))
    manifest = _manifest_df(tmp_path)
    assert sorted(manifest["source_record_id"]) == ["10.9/a1", "10.9/a3", "10.9/confb-1"]
    assert result.records_downloaded == 3
    assert "10.9/a2" not in manifest["source_record_id"].values
    assert "10.9/other-2" not in manifest["source_record_id"].values


@responses.activate
def test_signature_rejected_items_never_appear_in_discovery_ledger(tmp_path):
    _register_search(BASE_FIXTURES)
    ConferenceCrossrefSearchJob().run(_base_args(tmp_path))
    discovery = _discovery_df(tmp_path)
    assert "10.9/a2" not in discovery["source_record_id"].values
    assert "10.9/other-2" not in discovery["source_record_id"].values


@responses.activate
def test_same_doi_found_by_two_terms_keeps_both_discovery_observations_but_one_manifest_row(tmp_path):
    _register_search(BASE_FIXTURES)
    ConferenceCrossrefSearchJob().run(_base_args(tmp_path))
    manifest = _manifest_df(tmp_path)
    discovery = _discovery_df(tmp_path)
    assert (manifest["source_record_id"] == "10.9/a1").sum() == 1
    a1_discoveries = discovery[discovery["source_record_id"] == "10.9/a1"]
    assert len(a1_discoveries) == 2
    query_ids = set(a1_discoveries["query_id"])
    assert len(query_ids) == 2
    assert all(qid.startswith("CONFERENCE_CROSSREF_FAKE_A_") for qid in query_ids)
    assert set(a1_discoveries["query_text"]) == {
        'query.bibliographic="term1" issn=1111-1111 from-pub-date=none until-pub-date=none',
        'query.bibliographic="term2" issn=1111-1111 from-pub-date=none until-pub-date=none',
    }


@responses.activate
def test_conference_and_attribution_fields_populated(tmp_path):
    _register_search(BASE_FIXTURES)
    ConferenceCrossrefSearchJob().run(_base_args(tmp_path))
    manifest = _manifest_df(tmp_path)
    row = manifest[manifest["source_record_id"] == "10.9/confb-1"].iloc[0]
    assert row["conference"] == "FAKE_B"
    assert "doi_suffix_contains" in row["conference_attribution_evidence"]
    assert row["conference_year"] == "2026"


@responses.activate
def test_idempotent_second_run_all_skipped_unchanged(tmp_path):
    _register_search(BASE_FIXTURES)
    args = _base_args(tmp_path)
    ConferenceCrossrefSearchJob().run(args)
    result2 = ConferenceCrossrefSearchJob().run(args)
    assert result2.records_downloaded == 0
    assert result2.records_skipped_unchanged == 3
    manifest = _manifest_df(tmp_path)
    assert len(manifest) == 3  # no duplicate version rows


@responses.activate
def test_content_change_bumps_version(tmp_path):
    # Single-term config: avoids term2's own (unchanged-A1) fixture silently
    # overwriting term1's changed A1 in message_by_doi within the same run,
    # which is a test-fixture concern, not something this asserts about job.py.
    fixtures = {
        ("issn:1111-1111", "term1", "*"): [A1],
        ("issn:2222-2222", "term1", "*"): [B1_CONFB],
    }
    _register_search(fixtures)
    args = _base_args(tmp_path, config_text=CONFIG_YAML_ONE_TERM)
    ConferenceCrossrefSearchJob().run(args)

    responses.reset()
    changed_a1 = dict(A1)
    changed_a1["title"] = ["A1 TITLE CHANGED"]
    fixtures2 = dict(fixtures)
    fixtures2[("issn:1111-1111", "term1", "*")] = [changed_a1]
    _register_search(fixtures2)
    ConferenceCrossrefSearchJob().run(args)

    manifest = _manifest_df(tmp_path)
    a1_rows = manifest[manifest["source_record_id"] == "10.9/a1"].sort_values("version")
    assert list(a1_rows["version"]) == [1, 2]
    assert a1_rows.iloc[-1]["title"] == "A1 TITLE CHANGED"


@responses.activate
def test_volatile_relevance_score_change_alone_does_not_bump_version(tmp_path):
    """Crossref's own `score` field is a per-QUERY relevance ranking, not a
    property of the record -- live-verified to change between two
    identical repeated /works? searches for the same DOI. It must never
    leak into content_hash the way export_file_date/export_filename were
    excluded for WHO ICTRP/China CDE."""
    fixtures = {
        ("issn:1111-1111", "term1", "*"): [{**A1, "score": 4.8008943}],
        ("issn:2222-2222", "term1", "*"): [B1_CONFB],
    }
    _register_search(fixtures)
    args = _base_args(tmp_path, config_text=CONFIG_YAML_ONE_TERM)
    ConferenceCrossrefSearchJob().run(args)

    responses.reset()
    fixtures2 = dict(fixtures)
    fixtures2[("issn:1111-1111", "term1", "*")] = [{**A1, "score": 4.8030787}]
    _register_search(fixtures2)
    result2 = ConferenceCrossrefSearchJob().run(args)

    assert result2.records_skipped_unchanged == 2
    assert result2.records_downloaded == 0
    manifest = _manifest_df(tmp_path)
    assert list(manifest[manifest["source_record_id"] == "10.9/a1"]["version"]) == [1]


@responses.activate
def test_dry_run_does_not_materialize(tmp_path):
    _register_search(BASE_FIXTURES)
    result = ConferenceCrossrefSearchJob().run(_base_args(tmp_path, dry_run=True))
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "conference_crossref_search.parquet").exists()
    assert result.records_discovered == 3


@responses.activate
def test_limit_caps_materialized_records(tmp_path):
    _register_search(BASE_FIXTURES)
    result = ConferenceCrossrefSearchJob().run(_base_args(tmp_path, limit=1))
    assert result.records_downloaded == 1


@responses.activate
def test_since_and_until_are_sent_as_date_filters(tmp_path):
    fixtures = {
        ("issn:1111-1111,from-pub-date:2026-01-01,until-pub-date:2026-12-31", "term1", "*"): [A1],
        ("issn:1111-1111,from-pub-date:2026-01-01,until-pub-date:2026-12-31", "term2", "*"): [],
        ("issn:2222-2222,from-pub-date:2026-01-01,until-pub-date:2026-12-31", "term1", "*"): [],
        ("issn:2222-2222,from-pub-date:2026-01-01,until-pub-date:2026-12-31", "term2", "*"): [],
    }
    _register_search(fixtures)
    result = ConferenceCrossrefSearchJob().run(
        _base_args(tmp_path, since="2026-01-01", until="2026-12-31")
    )
    assert result.records_downloaded == 1


@responses.activate
def test_different_since_windows_produce_distinguishable_query_provenance(tmp_path):
    """Reviewer-flagged (round-1): --since/--until are real, live filters,
    so two runs of the same conference/term with different date windows
    are materially different queries and must never collide in the
    discovery ledger's query_id/query_text."""
    args_2022 = _base_args(tmp_path, config_text=CONFIG_YAML_ONE_TERM, since="2022-01-01")
    fixtures_2022 = {
        ("issn:1111-1111,from-pub-date:2022-01-01", "term1", "*"): [A1],
        ("issn:2222-2222,from-pub-date:2022-01-01", "term1", "*"): [],
    }
    _register_search(fixtures_2022)
    ConferenceCrossrefSearchJob().run(args_2022)

    responses.reset()
    args_2024 = _base_args(tmp_path, config_text=CONFIG_YAML_ONE_TERM, since="2024-01-01")
    fixtures_2024 = {
        ("issn:1111-1111,from-pub-date:2024-01-01", "term1", "*"): [A1],
        ("issn:2222-2222,from-pub-date:2024-01-01", "term1", "*"): [],
    }
    _register_search(fixtures_2024)
    ConferenceCrossrefSearchJob().run(args_2024)

    discovery = _discovery_df(tmp_path)
    a1 = discovery[discovery["source_record_id"] == "10.9/a1"]
    assert len(a1) == 2
    assert a1["query_id"].nunique() == 2
    texts = set(a1["query_text"])
    assert any("from-pub-date=2022-01-01" in t for t in texts)
    assert any("from-pub-date=2024-01-01" in t for t in texts)

    # Same effective query re-run with the SAME date window must reuse the
    # same query_id (deterministic, not a fresh id every run).
    responses.reset()
    _register_search(fixtures_2022)
    ConferenceCrossrefSearchJob().run(args_2022)
    discovery2 = _discovery_df(tmp_path)
    a1_2022_ids = discovery2[
        (discovery2["source_record_id"] == "10.9/a1")
        & (discovery2["query_text"].str.contains("from-pub-date=2022-01-01"))
    ]["query_id"].unique()
    assert len(a1_2022_ids) == 1


@responses.activate
def test_no_active_conferences_raises(tmp_path):
    import pytest
    _register_search(BASE_FIXTURES)
    with pytest.raises(RuntimeError, match="no active conferences"):
        ConferenceCrossrefSearchJob().run(_base_args(tmp_path, config_text=CONFIG_YAML_INACTIVE))


@responses.activate
def test_no_query_terms_raises(tmp_path):
    import pytest
    _register_search(BASE_FIXTURES)
    with pytest.raises(RuntimeError, match="no adc_query_terms"):
        ConferenceCrossrefSearchJob().run(_base_args(tmp_path, config_text=CONFIG_YAML_NO_TERMS))


@responses.activate
def test_pagination_follows_next_cursor_across_pages(tmp_path):
    page1 = ([A1], "cursor-page-2")
    page2 = [A3]
    fixtures = {
        ("issn:1111-1111", "term1", "*"): page1,
        ("issn:1111-1111", "term1", "cursor-page-2"): page2,
        ("issn:1111-1111", "term2", "*"): [],
        ("issn:2222-2222", "term1", "*"): [],
        ("issn:2222-2222", "term2", "*"): [],
    }
    _register_search(fixtures)
    result = ConferenceCrossrefSearchJob().run(_base_args(tmp_path, config_text=CONFIG_YAML_ONE_TERM))
    manifest = _manifest_df(tmp_path)
    assert sorted(manifest["source_record_id"]) == ["10.9/a1", "10.9/a3"]


@responses.activate
def test_page_fetch_failure_is_disclosed_and_job_continues(tmp_path, monkeypatch):
    from adc_acquisition import http_utils
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)

    def _callback(request):
        qs = parse_qs(urlparse(request.url).query)
        filter_str = qs.get("filter", [""])[0]
        if filter_str.startswith("issn:1111-1111"):
            return (500, {}, "")
        term = qs.get("query.bibliographic", [""])[0]
        cursor = qs.get("cursor", ["*"])[0]
        items = BASE_FIXTURES.get((filter_str, term, cursor), [])
        body = json.dumps({"message": {"items": items, "total-results": len(items), "next-cursor": None}})
        return (200, {}, body)

    responses.add_callback(responses.GET, re.compile(rf"{re.escape(CROSSREF_BASE)}/works.*"), callback=_callback)

    result = ConferenceCrossrefSearchJob().run(_base_args(tmp_path, config_text=CONFIG_YAML_ONE_TERM))
    assert any("page fetch failed" in note for note in result.notes)
    manifest = _manifest_df(tmp_path)
    # FAKE_A/term1 (issn:1111-1111) failed after retries; FAKE_B/term1 (issn:2222-2222) still succeeds.
    assert "10.9/confb-1" in manifest["source_record_id"].values
    assert "10.9/a1" not in manifest["source_record_id"].values
