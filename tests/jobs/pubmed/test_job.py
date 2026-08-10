import argparse
from urllib.parse import parse_qs

import pandas as pd
import responses

from jobs.pubmed.client import EUTILS_BASE
from jobs.pubmed.job import PubMedJob

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

# Q_A discovers 100, 101; Q_B discovers 101, 102 -> 101 is a cross-query duplicate.
TERM_TO_IDS = {"term-a": ["100", "101"], "term-b": ["101", "102"]}


def _esearch_callback(request):
    qs = parse_qs(request.url.split("?", 1)[1])
    term = qs["term"][0]
    ids = TERM_TO_IDS.get(term, [])
    body = {"esearchresult": {"count": str(len(ids)), "retmax": "200", "retstart": "0", "idlist": ids}}
    return (200, {}, __import__("json").dumps(body))


def _article_xml(pmid: str) -> bytes:
    return (
        f"<PubmedArticle><MedlineCitation><PMID Version=\"1\">{pmid}</PMID>"
        f"<Article><ArticleTitle>Title {pmid}</ArticleTitle>"
        f"<Abstract><AbstractText>Abstract {pmid}</AbstractText></Abstract></Article>"
        f"</MedlineCitation></PubmedArticle>"
    ).encode("utf-8")


def _make_efetch_callback(missing_ids=frozenset(), malformed=False):
    def _callback(request):
        if malformed:
            return (200, {}, b"<PubmedArticleSet><Unclosed>")
        qs = parse_qs(request.body if isinstance(request.body, str) else request.body.decode())
        requested_ids = qs["id"][0].split(",")
        fragments = [
            _article_xml(pmid).decode() for pmid in requested_ids if pmid not in missing_ids
        ]
        body = "<PubmedArticleSet>" + "".join(fragments) + "</PubmedArticleSet>"
        return (200, {}, body)

    return _callback


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False,
        limit=None,
        resume=False,
        since=None,
        until=None,
        output=str(tmp_path / "DATA"),
        queries_file=str(tmp_path / "queries.yaml"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch):
    (tmp_path / "queries.yaml").write_text(QUERIES_YAML)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")

    result = PubMedJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 3  # unique: 100, 101, 102
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "pubmed.parquet").exists()


@responses.activate
def test_full_run_writes_manifest_raw_files_and_report(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())

    result = PubMedJob().run(_base_args(tmp_path))

    assert result.records_discovered == 3
    assert result.records_downloaded == 3
    assert result.records_failed == 0

    manifest_path = tmp_path / "DATA" / "manifests" / "pubmed.parquet"
    assert manifest_path.exists()
    df = pd.read_parquet(manifest_path)
    assert set(df["source_record_id"]) == {"100", "101", "102"}
    assert (df["download_status"] == "success").all()

    for pmid in ("100", "101", "102"):
        assert (tmp_path / "DATA" / "raw" / "pubmed" / pmid / "v1.xml").exists()

    report_path = tmp_path / "reports" / "acquisition" / "pubmed.md"
    assert report_path.exists()
    report_text = report_path.read_text()
    assert "PubMed (Job 01)" in report_text
    assert "1 PMIDs were discovered by more than one query" in report_text


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())

    result = PubMedJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    assert len(df) == 1


@responses.activate
def test_rerun_with_unchanged_content_skips_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())

    PubMedJob().run(_base_args(tmp_path))
    second = PubMedJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 3
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    assert len(df) == 3  # no duplicate rows from the second run
    assert (df["version"] == 1).all()


@responses.activate
def test_changed_content_bumps_version_without_overwriting_old_snapshot(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())
    PubMedJob().run(_base_args(tmp_path, limit=1))  # downloads PMID 100 as v1

    responses.reset()
    def _changed_callback(request):
        qs = parse_qs(request.body if isinstance(request.body, str) else request.body.decode())
        requested_ids = qs["id"][0].split(",")
        fragments = []
        for pmid in requested_ids:
            fragments.append(
                f"<PubmedArticle><MedlineCitation><PMID Version=\"1\">{pmid}</PMID>"
                f"<Article><ArticleTitle>CHANGED Title {pmid}</ArticleTitle></Article>"
                f"</MedlineCitation></PubmedArticle>"
            )
        return (200, {}, "<PubmedArticleSet>" + "".join(fragments) + "</PubmedArticleSet>")

    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_changed_callback)

    PubMedJob().run(_base_args(tmp_path, limit=1))

    assert (tmp_path / "DATA" / "raw" / "pubmed" / "100" / "v1.xml").exists()
    assert (tmp_path / "DATA" / "raw" / "pubmed" / "100" / "v2.xml").exists()
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    row100 = df[df["source_record_id"] == "100"]
    assert sorted(row100["version"].tolist()) == [1, 2]


@responses.activate
def test_missing_pmid_in_efetch_response_is_logged_as_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback(missing_ids={"101"}))

    result = PubMedJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    assert result.records_downloaded == 2
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    failed_row = df[df["source_record_id"] == "101"].iloc[0]
    assert failed_row["download_status"] == "failed"
    failures_log = (tmp_path / "DATA" / "logs" / "pubmed_failures.log").read_text()
    assert "pmid=101" in failures_log


@responses.activate
def test_malformed_efetch_response_fails_whole_batch_without_crashing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback(malformed=True))

    result = PubMedJob().run(_base_args(tmp_path))

    assert result.records_failed == 3
    assert result.records_downloaded == 0
    df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    assert (df["download_status"] == "failed").all()


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
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")

    result = PubMedJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    manifest_path = tmp_path / "DATA" / "manifests" / "pubmed.parquet"
    assert manifest_path.exists()
    assert len(pd.read_parquet(manifest_path)) == 0
