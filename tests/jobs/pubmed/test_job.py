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
def test_missing_pmid_in_efetch_response_is_logged_as_failure_not_in_content_manifest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback(missing_ids={"101"}))

    result = PubMedJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    assert result.records_downloaded == 2

    content_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    # A failed attempt must never occupy a content-version slot.
    assert "101" not in set(content_df["source_record_id"])

    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed_attempts.parquet")
    failed_attempt = attempts_df[attempts_df["source_record_id"] == "101"].iloc[0]
    assert failed_attempt["status"] == "failed"
    assert failed_attempt["error"] == "missing_from_batch_response"
    assert pd.isna(failed_attempt["version"])

    failures_log = (tmp_path / "DATA" / "logs" / "pubmed_failures.log").read_text()
    assert "pmid=101" in failures_log


@responses.activate
def test_failure_after_prior_success_does_not_touch_existing_content_snapshot(tmp_path, monkeypatch):
    """success v1 -> later fetch failure -> success v1 must remain completely
    unchanged, and the failure must still be independently auditable."""
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())
    PubMedJob().run(_base_args(tmp_path, limit=1))  # PMID 100 -> success v1

    before_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    before_row = before_df[before_df["source_record_id"] == "100"].iloc[0]

    responses.reset()
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback(missing_ids={"100"}))
    result = PubMedJob().run(_base_args(tmp_path, limit=1))

    assert result.records_failed == 1
    assert result.records_downloaded == 0

    after_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    after_rows = after_df[after_df["source_record_id"] == "100"]
    assert len(after_rows) == 1  # still exactly one content snapshot, not replaced
    after_row = after_rows.iloc[0]
    assert after_row["version"] == before_row["version"] == 1
    assert after_row["content_hash"] == before_row["content_hash"]
    assert after_row["download_status"] == "success"

    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed_attempts.parquet")
    pmid_100_attempts = attempts_df[attempts_df["source_record_id"] == "100"]
    assert sorted(pmid_100_attempts["status"].tolist()) == ["failed", "success"]


@responses.activate
def test_success_after_prior_failure_still_starts_at_version_one(tmp_path, monkeypatch):
    """first attempt failed -> later succeeds -> success is content v1 (not
    v2), and the earlier failure remains auditable in the attempts ledger."""
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback(missing_ids={"100"}))
    first = PubMedJob().run(_base_args(tmp_path, limit=1))
    assert first.records_failed == 1
    assert first.records_downloaded == 0

    content_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    assert "100" not in set(content_df["source_record_id"])

    responses.reset()
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())
    second = PubMedJob().run(_base_args(tmp_path, limit=1))
    assert second.records_downloaded == 1

    content_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    row100 = content_df[content_df["source_record_id"] == "100"]
    assert len(row100) == 1
    assert row100.iloc[0]["version"] == 1

    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed_attempts.parquet")
    pmid_100_attempts = attempts_df[attempts_df["source_record_id"] == "100"]
    assert sorted(pmid_100_attempts["status"].tolist()) == ["failed", "success"]


@responses.activate
def test_discovery_ledger_preserves_every_discovering_query(tmp_path, monkeypatch):
    """A PMID hit by multiple queries must keep every discovery path, not
    just the first — the manifest's single query_id field is not enough."""
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())

    PubMedJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed_discovery.parquet")
    pmid_101_hits = discovery_df[discovery_df["source_record_id"] == "101"]
    assert sorted(pmid_101_hits["query_id"].tolist()) == ["Q_A", "Q_B"]
    assert set(pmid_101_hits["query_version"]) == {1}
    assert all(pmid_101_hits["query_text"].isin(["term-a", "term-b"]))

    # PMID 100 was only discovered by Q_A.
    pmid_100_hits = discovery_df[discovery_df["source_record_id"] == "100"]
    assert pmid_100_hits["query_id"].tolist() == ["Q_A"]


@responses.activate
def test_discovery_ledger_is_append_only_across_runs(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())

    PubMedJob().run(_base_args(tmp_path))
    PubMedJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed_discovery.parquet")
    # 2 runs x (Q_A: 100,101 + Q_B: 101,102) = 8 discovery events, not deduped.
    assert len(discovery_df) == 8
    assert discovery_df["run_id"].nunique() == 2


@responses.activate
def test_malformed_efetch_response_fails_whole_batch_without_crashing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback(malformed=True))

    result = PubMedJob().run(_base_args(tmp_path))

    assert result.records_failed == 3
    assert result.records_downloaded == 0
    content_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed.parquet")
    assert len(content_df) == 0  # no content was ever materialized

    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "pubmed_attempts.parquet")
    assert len(attempts_df) == 3
    assert (attempts_df["status"] == "failed").all()


def _esearch_callback_huge_count(request):
    """Simulates a query whose TRUE hit count (10,100) exceeds NCBI's own
    hard 9,999-record ESearch retstart ceiling -- live-verified 2026-09-01:
    a real request at retstart=10000 returns HTTP 200 with a malformed
    JSON error body ("'retstart' cannot be larger than 9998..."). This
    callback returns a well-formed page for any retstart actually
    requested (job.py must never request retstart > 9998 at all)."""
    import json

    qs = parse_qs(request.url.split("?", 1)[1])
    retstart = int(qs["retstart"][0])
    retmax = int(qs["retmax"][0])
    true_count = 10100
    ids = [str(i) for i in range(retstart, min(retstart + retmax, true_count))]
    body = {"esearchresult": {"count": str(true_count), "retmax": str(retmax), "retstart": str(retstart), "idlist": ids}}
    return (200, {}, json.dumps(body))


@responses.activate
def test_esearch_never_requests_retstart_past_ncbi_ceiling(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "queries.yaml").write_text(
        """
queries:
  - query_id: Q_HUGE
    query_version: 1
    query_text: "huge-query"
    purpose: test
    active: true
"""
    )
    responses.add_callback(
        responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback_huge_count, content_type="application/json",
    )
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())

    result = PubMedJob().run(_base_args(tmp_path, dry_run=True))

    esearch_calls = [c for c in responses.calls if "esearch.fcgi" in c.request.url]
    max_retstart_requested = max(int(parse_qs(c.request.url.split("?", 1)[1])["retstart"][0]) for c in esearch_calls)
    assert max_retstart_requested <= 9998

    assert any("retstart ceiling" in n for n in result.notes)
    assert any("Q_HUGE" in n and "10100" in n for n in result.notes)
    # Truncated, but never crashed -- some records were still discovered.
    assert result.records_discovered > 0


@responses.activate
def test_report_surfaces_retstart_ceiling_truncation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "queries.yaml").write_text(
        """
queries:
  - query_id: Q_HUGE
    query_version: 1
    query_text: "huge-query"
    purpose: test
    active: true
"""
    )
    responses.add_callback(
        responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback_huge_count, content_type="application/json",
    )
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())

    PubMedJob().run(_base_args(tmp_path))

    report_text = (tmp_path / "reports" / "acquisition" / "pubmed.md").read_text()
    assert "retstart ceiling" in report_text
    assert "Q_HUGE" in report_text


@responses.activate
def test_normal_sized_query_under_ceiling_is_unaffected(tmp_path, monkeypatch):
    """Regression guard: the ceiling check must never trigger for a query
    whose count never approaches it -- confirms no behavior change for
    every normal-sized query in this repo's real config."""
    _setup(tmp_path, monkeypatch)
    responses.add_callback(responses.GET, f"{EUTILS_BASE}/esearch.fcgi", callback=_esearch_callback, content_type="application/json")
    responses.add_callback(responses.POST, f"{EUTILS_BASE}/efetch.fcgi", callback=_make_efetch_callback())

    result = PubMedJob().run(_base_args(tmp_path))

    assert not any("retstart ceiling" in n for n in result.notes)
    assert result.records_discovered == 3


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
