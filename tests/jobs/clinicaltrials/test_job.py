import argparse
import json as json_module
from urllib.parse import parse_qs

import pandas as pd
import responses

from jobs.clinicaltrials.client import CTGOV_BASE
from jobs.clinicaltrials.job import ClinicalTrialsJob

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


def _study(nct_id, title="Title"):
    return {"protocolSection": {"identificationModule": {"nctId": nct_id, "briefTitle": title}}}


STUDY_100 = _study("NCT100")
STUDY_101 = _study("NCT101")
STUDY_102 = _study("NCT102")

# Q_A discovers 100, 101; Q_B discovers 101, 102 -> NCT101 is a cross-query duplicate.
TERM_TO_STUDIES = {"term-a": [STUDY_100, STUDY_101], "term-b": [STUDY_101, STUDY_102]}


def _search_callback(term_to_studies=None):
    studies_by_term = term_to_studies if term_to_studies is not None else TERM_TO_STUDIES

    def _callback(request):
        qs = parse_qs(request.url.split("?", 1)[1])
        term = qs.get("query.term", [None])[0]
        studies = studies_by_term.get(term, [])
        return (200, {}, json_module.dumps({"studies": studies, "totalCount": len(studies)}))

    return _callback


def _register(term_to_studies=None):
    responses.add_callback(responses.GET, f"{CTGOV_BASE}/studies", callback=_search_callback(term_to_studies))


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), queries_file=str(tmp_path / "queries.yaml"), intervention=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch):
    (tmp_path / "queries.yaml").write_text(QUERIES_YAML)
    monkeypatch.chdir(tmp_path)
    # Production uses a deliberately conservative 0.7 req/s (no officially
    # published rate limit); that's a real time.sleep() even against mocked
    # HTTP, so tests would otherwise take ~1.4s per request for no reason.
    import jobs.clinicaltrials.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)


def _metadata_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "clinicaltrials.parquet")


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    result = ClinicalTrialsJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 3
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "clinicaltrials.parquet").exists()


@responses.activate
def test_full_run_writes_manifest_and_raw_files(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    result = ClinicalTrialsJob().run(_base_args(tmp_path))

    assert result.records_discovered == 3
    assert result.records_downloaded == 3
    assert result.records_failed == 0

    df = _metadata_df(tmp_path)
    assert set(df["source_record_id"]) == {"NCT100", "NCT101", "NCT102"}
    for nct_id in ("NCT100", "NCT101", "NCT102"):
        assert (tmp_path / "DATA" / "raw" / "clinicaltrials" / nct_id / "v1.json").exists()

    report_text = (tmp_path / "reports" / "acquisition" / "clinicaltrials.md").read_text()
    assert "ClinicalTrials.gov (Job 03)" in report_text


@responses.activate
def test_discovery_ledger_preserves_every_discovering_query(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    ClinicalTrialsJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "clinicaltrials_discovery.parquet")
    hits_101 = discovery_df[discovery_df["source_record_id"] == "NCT101"]
    assert sorted(hits_101["query_id"].tolist()) == ["Q_A", "Q_B"]
    hits_100 = discovery_df[discovery_df["source_record_id"] == "NCT100"]
    assert hits_100["query_id"].tolist() == ["Q_A"]


@responses.activate
def test_rerun_with_unchanged_content_skips_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    ClinicalTrialsJob().run(_base_args(tmp_path))
    second = ClinicalTrialsJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 3
    df = _metadata_df(tmp_path)
    assert len(df) == 3
    assert (df["version"] == 1).all()


@responses.activate
def test_changed_content_bumps_version_without_overwriting_old_snapshot(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()
    ClinicalTrialsJob().run(_base_args(tmp_path, limit=1))  # NCT100 -> v1

    responses.reset()
    _register({"term-a": [_study("NCT100", title="CHANGED Title"), STUDY_101], "term-b": [STUDY_101, STUDY_102]})
    ClinicalTrialsJob().run(_base_args(tmp_path, limit=1))

    assert (tmp_path / "DATA" / "raw" / "clinicaltrials" / "NCT100" / "v1.json").exists()
    assert (tmp_path / "DATA" / "raw" / "clinicaltrials" / "NCT100" / "v2.json").exists()
    df = _metadata_df(tmp_path)
    row100 = df[df["source_record_id"] == "NCT100"]
    assert sorted(row100["version"].tolist()) == [1, 2]


@responses.activate
def test_failed_attempt_never_occupies_content_version_slot(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def _bad_search_callback(request):
        qs = parse_qs(request.url.split("?", 1)[1])
        term = qs.get("query.term", [None])[0]
        studies = [STUDY_100] if term == "term-a" else []
        return (200, {}, json_module.dumps({"studies": studies}))

    responses.add_callback(responses.GET, f"{CTGOV_BASE}/studies", callback=_bad_search_callback)

    import jobs.clinicaltrials.job as job_module

    original = job_module.parse_study

    def _boom(raw_result):
        ident = (raw_result.get("protocolSection") or {}).get("identificationModule") or {}
        if ident.get("nctId") == "NCT100":
            raise TypeError("simulated malformed record")
        return original(raw_result)

    monkeypatch.setattr(job_module, "parse_study", _boom)

    result = ClinicalTrialsJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    assert result.records_downloaded == 0
    df = _metadata_df(tmp_path)
    assert len(df) == 0
    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "clinicaltrials_attempts.parquet")
    assert (attempts_df["status"] == "failed").all()
    failures_log = (tmp_path / "DATA" / "logs" / "clinicaltrials_failures.log").read_text()
    assert "NCT100" in failures_log


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()

    result = ClinicalTrialsJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    assert len(_metadata_df(tmp_path)) == 1


@responses.activate
def test_since_and_until_add_last_update_date_filter(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen_urls = []

    def _callback(request):
        seen_urls.append(request.url)
        return (200, {}, json_module.dumps({"studies": []}))

    responses.add_callback(responses.GET, f"{CTGOV_BASE}/studies", callback=_callback)

    ClinicalTrialsJob().run(_base_args(tmp_path, since="2024-01-01", until="2024-12-31"))

    assert all("filter.advanced=" in u for u in seen_urls)


@responses.activate
def test_resume_uses_checkpoint_last_success_max_date(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register()
    ClinicalTrialsJob().run(_base_args(tmp_path))

    seen_urls = []

    def _callback(request):
        seen_urls.append(request.url)
        return (200, {}, json_module.dumps({"studies": []}))

    responses.reset()
    responses.add_callback(responses.GET, f"{CTGOV_BASE}/studies", callback=_callback)

    ClinicalTrialsJob().run(_base_args(tmp_path, resume=True))

    assert all("filter.advanced=" in u for u in seen_urls)


@responses.activate
def test_intervention_lookup_uses_query_intr_and_ignores_query_registry(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def _callback(request):
        qs = parse_qs(request.url.split("?", 1)[1])
        assert "query.intr" in qs
        assert "query.term" not in qs
        return (200, {}, json_module.dumps({"studies": [STUDY_100]}))

    responses.add_callback(responses.GET, f"{CTGOV_BASE}/studies", callback=_callback)

    result = ClinicalTrialsJob().run(_base_args(tmp_path, intervention="trastuzumab deruxtecan"))

    assert result.queries_run == 1
    assert result.records_downloaded == 1


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
    _register()

    result = ClinicalTrialsJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert len(_metadata_df(tmp_path)) == 0
