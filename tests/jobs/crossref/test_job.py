import argparse
import re

import pandas as pd
import responses

from adc_acquisition.manifest import COMMON_FIELDS
from jobs.crossref.client import CROSSREF_BASE
from jobs.crossref.job import CrossrefJob

SOURCES_YAML = """
reconciliation_sources:
  - source_id: pubmed
    manifest_path: {pubmed_path}
    query_id: CROSSREF_RECONCILE_PUBMED
    query_version: 1
    purpose: test
    active: true
  - source_id: europe_pmc
    manifest_path: {epmc_path}
    query_id: CROSSREF_RECONCILE_EUROPE_PMC
    query_version: 1
    purpose: test
    active: true
"""


def _write_manifest(path, rows):
    columns = COMMON_FIELDS + ["doi"]
    df = pd.DataFrame(rows, columns=columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def _base_manifest_row(source_record_id, doi):
    row = {c: None for c in COMMON_FIELDS}
    row.update(source="pubmed", source_record_id=source_record_id, version=1, doi=doi)
    return row


def _setup(tmp_path, monkeypatch, pubmed_dois=("10.1/aaa", "10.1/bbb"), epmc_dois=("10.1/bbb", "10.1/ccc")):
    monkeypatch.chdir(tmp_path)
    pubmed_path = tmp_path / "DATA" / "manifests" / "pubmed.parquet"
    epmc_path = tmp_path / "DATA" / "manifests" / "europe_pmc.parquet"
    _write_manifest(pubmed_path, [_base_manifest_row(f"PMID{i}", doi) for i, doi in enumerate(pubmed_dois)] + [_base_manifest_row("PMID_NODOI", None)])
    _write_manifest(epmc_path, [_base_manifest_row(f"EPMC{i}", doi) for i, doi in enumerate(epmc_dois)])
    (tmp_path / "sources.yaml").write_text(SOURCES_YAML.format(pubmed_path=pubmed_path, epmc_path=epmc_path))


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), sources_file=str(tmp_path / "sources.yaml"), doi=None, mailto=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _work_response(doi, title="Title"):
    return {"message": {"DOI": doi, "title": [title]}}


def _register_crossref(dois_to_messages):
    def _callback(request):
        doi = request.url.split("/works/")[-1].split("?")[0]
        import urllib.parse
        doi = urllib.parse.unquote(doi)
        if doi in dois_to_messages:
            return (200, {}, __import__("json").dumps(_work_response(doi, dois_to_messages[doi])))
        return (404, {}, "")

    responses.add_callback(responses.GET, re.compile(rf"{re.escape(CROSSREF_BASE)}/works/.+"), callback=_callback)


def _metadata_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "crossref.parquet")


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    result = CrossrefJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 3  # unique: aaa, bbb, ccc (bbb shared by both sources)
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "crossref.parquet").exists()


@responses.activate
def test_full_run_reconciles_dois_from_both_sources(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_crossref({"10.1/aaa": "A", "10.1/bbb": "B", "10.1/ccc": "C"})

    result = CrossrefJob().run(_base_args(tmp_path))

    assert result.records_discovered == 3
    assert result.records_downloaded == 3
    assert result.records_failed == 0

    df = _metadata_df(tmp_path)
    assert set(df["source_record_id"]) == {"10.1/aaa", "10.1/bbb", "10.1/ccc"}

    report_text = (tmp_path / "reports" / "acquisition" / "crossref.md").read_text()
    assert "Crossref (Job 04)" in report_text


@responses.activate
def test_doi_shared_by_both_sources_is_recorded_as_duplicate_in_discovery_ledger(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_crossref({"10.1/aaa": "A", "10.1/bbb": "B", "10.1/ccc": "C"})

    CrossrefJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "crossref_discovery.parquet")
    hits_bbb = discovery_df[discovery_df["source_record_id"] == "10.1/bbb"]
    assert sorted(hits_bbb["query_id"].tolist()) == ["CROSSREF_RECONCILE_EUROPE_PMC", "CROSSREF_RECONCILE_PUBMED"]


@responses.activate
def test_missing_upstream_manifest_is_skipped_not_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pubmed_path = tmp_path / "DATA" / "manifests" / "pubmed.parquet"
    missing_path = tmp_path / "DATA" / "manifests" / "does_not_exist.parquet"
    _write_manifest(pubmed_path, [_base_manifest_row("PMID0", "10.1/aaa")])
    (tmp_path / "sources.yaml").write_text(
        f"""
reconciliation_sources:
  - source_id: pubmed
    manifest_path: {pubmed_path}
    query_id: CROSSREF_RECONCILE_PUBMED
    query_version: 1
    purpose: test
    active: true
  - source_id: never_run_yet
    manifest_path: {missing_path}
    query_id: CROSSREF_RECONCILE_NEVER_RUN
    query_version: 1
    purpose: test
    active: true
"""
    )
    _register_crossref({"10.1/aaa": "A"})

    result = CrossrefJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert result.records_downloaded == 1


@responses.activate
def test_rerun_with_unchanged_content_skips_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_crossref({"10.1/aaa": "A", "10.1/bbb": "B", "10.1/ccc": "C"})

    CrossrefJob().run(_base_args(tmp_path))
    second = CrossrefJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 3
    df = _metadata_df(tmp_path)
    assert len(df) == 3
    assert (df["version"] == 1).all()


@responses.activate
def test_doi_not_found_in_crossref_is_a_distinct_failed_attempt_not_in_content_manifest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, pubmed_dois=("10.1/aaa", "10.1/missing"), epmc_dois=())
    _register_crossref({"10.1/aaa": "A"})  # 10.1/missing will 404

    result = CrossrefJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    assert result.records_downloaded == 1
    content_df = _metadata_df(tmp_path)
    assert "10.1/missing" not in set(content_df["source_record_id"])

    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "crossref_attempts.parquet")
    failed = attempts_df[attempts_df["source_record_id"] == "10.1/missing"].iloc[0]
    assert failed["status"] == "failed"
    assert failed["http_status"] == 404
    assert failed["error"] == "not_found_in_crossref"


@responses.activate
def test_doi_ad_hoc_lookup_gets_deterministic_asset_specific_query_id(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, pubmed_dois=(), epmc_dois=())
    _register_crossref({"10.1/adhoc-a": "A", "10.1/adhoc-b": "B"})

    CrossrefJob().run(_base_args(tmp_path, doi="10.1/adhoc-a"))
    CrossrefJob().run(_base_args(tmp_path, doi="10.1/adhoc-b"))
    CrossrefJob().run(_base_args(tmp_path, doi="10.1/adhoc-a"))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "crossref_discovery.parquet")
    id_a = discovery_df[discovery_df["source_record_id"] == "10.1/adhoc-a"]["query_id"].unique().tolist()
    id_b = discovery_df[discovery_df["source_record_id"] == "10.1/adhoc-b"]["query_id"].unique().tolist()
    assert len(id_a) == 1
    assert len(id_b) == 1
    assert id_a != id_b


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_crossref({"10.1/aaa": "A", "10.1/bbb": "B", "10.1/ccc": "C"})

    result = CrossrefJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    assert len(_metadata_df(tmp_path)) == 1


@responses.activate
def test_since_until_and_resume_are_noted_as_not_applicable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, pubmed_dois=(), epmc_dois=())
    _register_crossref({})

    result = CrossrefJob().run(_base_args(tmp_path, doi="10.1/x", since="2024-01-01"))
    assert any("not applicable" in n for n in result.notes)

    result2 = CrossrefJob().run(_base_args(tmp_path, doi="10.1/x", resume=True))
    assert any("no-op" in n for n in result2.notes)


def test_no_active_sources_and_no_doi_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sources.yaml").write_text("reconciliation_sources: []\n")
    try:
        CrossrefJob().run(_base_args(tmp_path))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
