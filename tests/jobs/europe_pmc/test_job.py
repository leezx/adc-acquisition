import argparse
from urllib.parse import parse_qs

import pandas as pd
import responses

from jobs.europe_pmc.client import EUROPEPMC_BASE
from jobs.europe_pmc.job import EuropePMCJob

QUERIES_YAML = """
queries:
  - query_id: Q_A
    query_version: 1
    query_text: "term-a"
    purpose: test query a
    active: true
  - query_id: Q_B
    query_version: 1
    query_text: "term-b"
    purpose: test query b
    active: true
  - query_id: Q_INACTIVE
    query_version: 1
    query_text: "term-c"
    purpose: should not run
    active: false
"""

RECORD_100 = {"id": "100", "source": "MED", "title": "Title 100", "isOpenAccess": "N"}
RECORD_101 = {"id": "101", "source": "MED", "title": "Title 101", "isOpenAccess": "Y", "pmcid": "PMC101"}
RECORD_102 = {"id": "102", "source": "PMC", "title": "Title 102", "isOpenAccess": "N"}

# Q_A discovers 100, 101; Q_B discovers 101, 102 -> MED:101 is a cross-query duplicate.
TERM_TO_RECORDS = {"term-a": [RECORD_100, RECORD_101], "term-b": [RECORD_101, RECORD_102]}


def _search_callback(term_to_records=None):
    records_by_term = term_to_records if term_to_records is not None else TERM_TO_RECORDS

    def _callback(request):
        qs = parse_qs(request.url.split("?", 1)[1])
        term = qs["query"][0]
        records = records_by_term.get(term, [])
        body = {"hitCount": len(records), "resultList": {"result": records}}
        return (200, {}, __import__("json").dumps(body))

    return _callback


def _fulltext_callback(available_pmcids=frozenset({"PMC101"})):
    def _callback(request):
        pmcid = request.url.rsplit("/", 2)[-2]
        if pmcid in available_pmcids:
            return (200, {}, f"<article>{pmcid}</article>")
        return (404, {}, "")

    return _callback


def _register(search_records=None, fulltext_available=frozenset({"PMC101"})):
    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_search_callback(search_records))
    import re
    responses.add_callback(
        responses.GET,
        re.compile(rf"{re.escape(EUROPEPMC_BASE)}/.+/fullTextXML"),
        callback=_fulltext_callback(fulltext_available),
    )


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), queries_file=str(tmp_path / "queries.yaml"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch):
    (tmp_path / "queries.yaml").write_text(QUERIES_YAML)
    monkeypatch.chdir(tmp_path)


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    result = EuropePMCJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 3  # unique: MED:100, MED:101, PMC:102
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "europe_pmc.parquet").exists()


@responses.activate
def test_full_run_writes_manifest_and_fetches_open_access_fulltext(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    result = EuropePMCJob().run(_base_args(tmp_path))

    assert result.records_discovered == 3
    assert result.records_downloaded == 3
    assert result.records_failed == 0

    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc.parquet")
    assert set(df["source_record_id"]) == {"MED:100", "MED:101", "PMC:102"}

    row_101 = df[df["source_record_id"] == "MED:101"].iloc[0]
    assert row_101["is_open_access"] is True or row_101["is_open_access"] == True  # noqa: E712
    assert row_101["fulltext_downloaded"] is True or row_101["fulltext_downloaded"] == True  # noqa: E712
    assert (tmp_path / "DATA" / "raw" / "europe_pmc" / "MED_101" / "v1_fulltext.xml").exists()

    row_100 = df[df["source_record_id"] == "MED:100"].iloc[0]
    assert not row_100["fulltext_downloaded"]
    assert not (tmp_path / "DATA" / "raw" / "europe_pmc" / "MED_100" / "v1_fulltext.xml").exists()

    report_path = tmp_path / "reports" / "acquisition" / "europe_pmc.md"
    assert report_path.exists()
    assert "Europe PMC (Job 02)" in report_path.read_text()


@responses.activate
def test_discovery_ledger_preserves_every_discovering_query(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    EuropePMCJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc_discovery.parquet")
    hits_101 = discovery_df[discovery_df["source_record_id"] == "MED:101"]
    assert sorted(hits_101["query_id"].tolist()) == ["Q_A", "Q_B"]

    hits_100 = discovery_df[discovery_df["source_record_id"] == "MED:100"]
    assert hits_100["query_id"].tolist() == ["Q_A"]


@responses.activate
def test_rerun_with_unchanged_metadata_skips_rewrite_but_content_manifest_stable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    EuropePMCJob().run(_base_args(tmp_path))
    second = EuropePMCJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 3
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc.parquet")
    assert len(df) == 3
    assert (df["version"] == 1).all()


@responses.activate
def test_fulltext_fetch_retried_on_later_run_after_earlier_failure(tmp_path, monkeypatch):
    """A record is open access but fullTextXML 404s on run 1 (e.g. Europe
    PMC's own metadata was briefly ahead of the full-text pipeline). Run 2,
    without --limit or content changes, must still retry the full-text
    fetch rather than treating it as permanently failed."""
    _setup(tmp_path, monkeypatch)
    _register(fulltext_available=frozenset())  # nothing available yet

    first = EuropePMCJob().run(_base_args(tmp_path))
    assert first.records_downloaded == 3
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc.parquet")
    assert not df[df["source_record_id"] == "MED:101"].iloc[0]["fulltext_downloaded"]

    responses.reset()
    _register(fulltext_available=frozenset({"PMC101"}))  # now available
    second = EuropePMCJob().run(_base_args(tmp_path))

    assert second.records_skipped_unchanged == 3  # metadata itself unchanged
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc.parquet")
    row_101 = df[df["source_record_id"] == "MED:101"]
    assert len(row_101) == 1  # updated in place, not a new version
    assert row_101.iloc[0]["version"] == 1
    assert row_101.iloc[0]["fulltext_downloaded"]


@responses.activate
def test_non_open_access_record_never_attempts_fulltext_fetch(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    call_log = []

    def _tracking_fulltext_callback(request):
        call_log.append(request.url)
        return (404, {}, "")

    import re
    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_search_callback())
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(EUROPEPMC_BASE)}/.+/fullTextXML"), callback=_tracking_fulltext_callback)

    EuropePMCJob().run(_base_args(tmp_path, limit=1))  # MED:100 only, isOpenAccess=N

    assert call_log == []


@responses.activate
def test_malformed_record_missing_source_after_discovery_does_not_crash_run(tmp_path, monkeypatch):
    """Simulates a record that reaches per-record processing with no usable
    source/id (defensive path — discovery itself already filters these, but
    the per-record guard must still fail safely, not crash the run)."""
    _setup(tmp_path, monkeypatch)

    def _bad_search_callback(request):
        qs = parse_qs(request.url.split("?", 1)[1])
        term = qs["query"][0]
        if term == "term-a":
            records = [{"id": "100", "source": "MED", "title": "ok"}]
        else:
            records = []
        return (200, {}, __import__("json").dumps({"hitCount": len(records), "resultList": {"result": records}}))

    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_bad_search_callback)

    # Monkeypatch parse_search_result to simulate an unexpected malformed
    # shape slipping through for this one record.
    import jobs.europe_pmc.job as job_module

    original = job_module.parse_search_result

    def _boom(raw_result):
        if raw_result.get("id") == "100":
            raise TypeError("simulated malformed journalInfo")
        return original(raw_result)

    monkeypatch.setattr(job_module, "parse_search_result", _boom)

    result = EuropePMCJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    assert result.records_downloaded == 0
    content_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc.parquet")
    assert len(content_df) == 0
    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc_attempts.parquet")
    assert (attempts_df["status"] == "failed").all()


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    result = EuropePMCJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc.parquet")
    assert len(df) == 1


@responses.activate
def test_since_and_until_add_first_pdate_filter_to_query(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen_queries = []

    def _callback(request):
        qs = parse_qs(request.url.split("?", 1)[1])
        seen_queries.append(qs["query"][0])
        return (200, {}, __import__("json").dumps({"hitCount": 0, "resultList": {"result": []}}))

    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_callback)

    EuropePMCJob().run(_base_args(tmp_path, since="2024-01-01", until="2024-12-31"))

    assert all("FIRST_PDATE:[2024-01-01 TO 2024-12-31]" in q for q in seen_queries)


@responses.activate
def test_resume_uses_checkpoint_last_success_max_date_as_since(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()
    EuropePMCJob().run(_base_args(tmp_path))  # establishes last_success_max_date in checkpoint

    seen_queries = []

    def _callback(request):
        qs = parse_qs(request.url.split("?", 1)[1])
        seen_queries.append(qs["query"][0])
        return (200, {}, __import__("json").dumps({"hitCount": 0, "resultList": {"result": []}}))

    responses.reset()
    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_callback)

    EuropePMCJob().run(_base_args(tmp_path, resume=True))

    assert all("FIRST_PDATE:[" in q for q in seen_queries)


@responses.activate
def test_empty_result_set_produces_empty_manifest_without_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "queries.yaml").write_text(
        """
queries:
  - query_id: Q_EMPTY
    query_version: 1
    query_text: "nothing-matches"
    purpose: test
    active: true
"""
    )
    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_search_callback())

    result = EuropePMCJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    manifest_path = tmp_path / "DATA" / "manifests" / "europe_pmc.parquet"
    assert manifest_path.exists()
    assert len(pd.read_parquet(manifest_path)) == 0
