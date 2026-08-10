import argparse
import re
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


def _fulltext_callback(available: dict[str, bytes | None] | None = None):
    """available maps pmcid -> xml bytes to return (None means keep 404-ing)."""
    availability = available if available is not None else {"PMC101": b"<article>v1</article>"}

    def _callback(request):
        pmcid = request.url.rsplit("/", 2)[-2]
        content = availability.get(pmcid)
        if content is not None:
            return (200, {}, content)
        return (404, {}, "")

    return _callback


def _register(search_records=None, fulltext_available=None):
    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_search_callback(search_records))
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


def _metadata_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc.parquet")


def _fulltext_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc_fulltext.parquet")


def _fulltext_attempts_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc_fulltext_attempts.parquet")


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
def test_full_run_writes_metadata_and_independent_fulltext_artifact(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    result = EuropePMCJob().run(_base_args(tmp_path))

    assert result.records_discovered == 3
    assert result.records_downloaded == 3
    assert result.records_failed == 0

    metadata_df = _metadata_df(tmp_path)
    assert set(metadata_df["source_record_id"]) == {"MED:100", "MED:101", "PMC:102"}
    # The metadata content manifest carries no full-text fields at all.
    assert "fulltext_downloaded" not in metadata_df.columns
    assert "fulltext_path" not in metadata_df.columns

    fulltext_df = _fulltext_df(tmp_path)
    assert len(fulltext_df) == 1  # only MED:101 is open access with a pmcid
    ft_row = fulltext_df.iloc[0]
    assert ft_row["source_record_id"] == "PMC101"
    assert ft_row["parent_record_id"] == "MED:101"
    assert ft_row["version"] == 1
    assert (tmp_path / "DATA" / "raw" / "europe_pmc_fulltext" / "PMC101" / "v1.xml").exists()

    report_text = (tmp_path / "reports" / "acquisition" / "europe_pmc.md").read_text()
    assert "Europe PMC (Job 02)" in report_text
    assert "independent artifact" in report_text.lower()


@responses.activate
def test_discovery_ledger_preserves_every_discovering_query(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    EuropePMCJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc_discovery.parquet")
    hits_101 = discovery_df[discovery_df["source_record_id"] == "MED:101"]
    assert sorted(hits_101["query_id"].tolist()) == ["Q_A", "Q_B"]


@responses.activate
def test_rerun_with_unchanged_metadata_and_fulltext_is_fully_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    EuropePMCJob().run(_base_args(tmp_path))
    second = EuropePMCJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 3
    assert len(_metadata_df(tmp_path)) == 3
    assert len(_fulltext_df(tmp_path)) == 1  # not duplicated on the unchanged rerun


# --- The three acceptance scenarios from the Phase 2 review ---

@responses.activate
def test_metadata_v1_unchanged_when_fulltext_initially_unavailable_then_later_succeeds(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register(fulltext_available={"PMC101": None})  # 404s on run 1

    first = EuropePMCJob().run(_base_args(tmp_path))
    assert first.records_downloaded == 3
    metadata_before = _metadata_df(tmp_path)
    row_101_before = metadata_before[metadata_before["source_record_id"] == "MED:101"].iloc[0]
    assert row_101_before["version"] == 1
    assert not _fulltext_df(tmp_path).query("parent_record_id == 'MED:101'").shape[0]  # no artifact yet

    responses.reset()
    _register(fulltext_available={"PMC101": b"<article>v1</article>"})  # now available
    second = EuropePMCJob().run(_base_args(tmp_path))

    # Metadata for MED:101 is unchanged (same run produced skipped_unchanged
    # for metadata, since only the search result itself, not the fulltext
    # outcome, determines metadata content).
    assert second.records_skipped_unchanged == 3
    metadata_after = _metadata_df(tmp_path)
    row_101_after = metadata_after[metadata_after["source_record_id"] == "MED:101"]
    assert len(row_101_after) == 1  # not duplicated
    assert row_101_after.iloc[0].equals(row_101_before)  # byte-for-byte unchanged

    fulltext_df = _fulltext_df(tmp_path)
    ft_row = fulltext_df[fulltext_df["parent_record_id"] == "MED:101"]
    assert len(ft_row) == 1
    assert ft_row.iloc[0]["version"] == 1

    attempts = _fulltext_attempts_df(tmp_path)
    pmc101_attempts = attempts[attempts["source_record_id"] == "PMC101"]
    assert sorted(pmc101_attempts["status"].tolist()) == ["failed", "success"]


@responses.activate
def test_fulltext_content_change_creates_v2_artifact_without_touching_v1(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register(fulltext_available={"PMC101": b"<article>original</article>"})

    EuropePMCJob().run(_base_args(tmp_path))
    v1_path = tmp_path / "DATA" / "raw" / "europe_pmc_fulltext" / "PMC101" / "v1.xml"
    assert v1_path.read_bytes() == b"<article>original</article>"

    responses.reset()
    _register(fulltext_available={"PMC101": b"<article>revised</article>"})
    EuropePMCJob().run(_base_args(tmp_path))

    # v1 file must still exist, byte-for-byte unchanged.
    assert v1_path.read_bytes() == b"<article>original</article>"
    v2_path = tmp_path / "DATA" / "raw" / "europe_pmc_fulltext" / "PMC101" / "v2.xml"
    assert v2_path.read_bytes() == b"<article>revised</article>"

    fulltext_df = _fulltext_df(tmp_path)
    versions = sorted(fulltext_df[fulltext_df["source_record_id"] == "PMC101"]["version"].tolist())
    assert versions == [1, 2]


@responses.activate
def test_fulltext_fetch_failure_never_touches_metadata_snapshot(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register(fulltext_available={"PMC101": None})  # always 404s

    EuropePMCJob().run(_base_args(tmp_path))
    metadata_before = _metadata_df(tmp_path)

    EuropePMCJob().run(_base_args(tmp_path))
    metadata_after = _metadata_df(tmp_path)

    pd.testing.assert_frame_equal(
        metadata_before.sort_values("source_record_id").reset_index(drop=True),
        metadata_after.sort_values("source_record_id").reset_index(drop=True),
    )
    assert len(_fulltext_df(tmp_path)) == 0  # never successfully materialized

    attempts = _fulltext_attempts_df(tmp_path)
    assert (attempts["status"] == "failed").all()
    assert len(attempts) == 2  # one failed attempt per run


# --- End acceptance scenarios ---


@responses.activate
def test_non_open_access_record_never_attempts_fulltext_fetch(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    call_log = []

    def _tracking_fulltext_callback(request):
        call_log.append(request.url)
        return (404, {}, "")

    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_search_callback())
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(EUROPEPMC_BASE)}/.+/fullTextXML"), callback=_tracking_fulltext_callback)

    EuropePMCJob().run(_base_args(tmp_path, limit=1))  # MED:100 only, isOpenAccess=N

    assert call_log == []


@responses.activate
def test_malformed_record_does_not_crash_run(tmp_path, monkeypatch):
    """Discovery already filters records with no usable source/id; this
    covers a record that reaches per-record processing with an unexpected
    shape some other way — must fail safely, not crash the run."""
    _setup(tmp_path, monkeypatch)

    def _bad_search_callback(request):
        qs = parse_qs(request.url.split("?", 1)[1])
        term = qs["query"][0]
        records = [{"id": "100", "source": "MED", "title": "ok"}] if term == "term-a" else []
        return (200, {}, __import__("json").dumps({"hitCount": len(records), "resultList": {"result": records}}))

    responses.add_callback(responses.GET, f"{EUROPEPMC_BASE}/search", callback=_bad_search_callback)

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
    assert len(_metadata_df(tmp_path)) == 0
    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "europe_pmc_attempts.parquet")
    assert (attempts_df["status"] == "failed").all()


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    result = EuropePMCJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    assert len(_metadata_df(tmp_path)) == 1


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
    assert len(_metadata_df(tmp_path)) == 0
