import argparse
import re
from urllib.parse import parse_qs, urlparse

import pandas as pd
import responses

from jobs.uspto.client import USPTO_API_BASE, SEARCH_URL
from jobs.uspto.job import USPTOJob

QUERIES_YAML = """
queries:
  - query_id: USPTO_TEST_PHRASE
    query_version: 1
    query_text: '"antibody-drug conjugate"'
    purpose: test
    active: true
"""

TWO_QUERY_YAML = """
queries:
  - query_id: USPTO_TEST_A
    query_version: 1
    query_text: 'alpha'
    purpose: test
    active: true
  - query_id: USPTO_TEST_B
    query_version: 3
    query_text: 'beta'
    purpose: test
    active: true
"""


def _application(app_id, title="A Title", status="Patented Case"):
    return {
        "applicationNumberText": app_id,
        "applicationMetaData": {
            "inventionTitle": title,
            "filingDate": "2020-01-01",
            "earliestPublicationDate": "2020-06-01",
            "earliestPublicationNumber": f"US{app_id}A1",
            "applicationStatusDescriptionText": status,
            "applicantBag": [{"applicantNameText": "Acme Pharma"}],
            "inventorBag": [{"inventorNameText": "Jane Doe"}],
            "cpcClassificationBag": ["A61K 47/54"],
        },
        "assignmentBag": [],
        "foreignPriorityBag": [],
    }


def _document_bag(doc_id="DOC1", url=None):
    return [
        {
            "documentIdentifier": doc_id,
            "documentCode": "SPEC",
            "documentCodeDescriptionText": "Specification",
            "officialDate": "2020-01-05T00:00:00.000-0400",
            "downloadOptionBag": [{"mimeTypeIdentifier": "PDF", "downloadUrl": url or f"https://api.uspto.gov/api/v1/download/applications/{doc_id}.pdf"}],
        }
    ]


def _register_uspto(query_to_ids: dict, applications: dict | None = None, documents: dict | None = None, doc_bytes: dict | None = None):
    """Single dispatcher callback for every USPTO_API_BASE-prefixed URL,
    routing by PATH (not a bag of overlapping regexes) -- avoids the exact
    collision that broke this harness once: `.../applications/search` also
    matches a naive `.../applications/[^/]+$` pattern, since `request.url`
    includes the query string and a regex `$`-anchor doesn't stop at '?'."""
    applications = applications or {}
    documents = documents or {}
    doc_bytes = doc_bytes or {}
    import json as _json

    def _dispatch(request):
        path = urlparse(request.url).path
        if path == "/api/v1/patent/applications/search":
            qs = parse_qs(urlparse(request.url).query)
            q = qs.get("q", [""])[0]
            offset = int(qs.get("offset", ["0"])[0])
            ids = query_to_ids.get(q, [])
            page = ids[offset : offset + 100]
            return (200, {}, _json.dumps({"count": len(ids), "patentFileWrapperDataBag": [{"applicationNumberText": i} for i in page]}))

        if path.endswith("/documents"):
            app_id = path.rsplit("/documents", 1)[0].rsplit("/", 1)[-1]
            docs = documents.get(app_id)
            if docs is None:
                return (200, {}, '{"count": 0, "documentBag": []}')
            return (200, {}, _json.dumps({"count": len(docs), "documentBag": docs}))

        app_id = path.rsplit("/", 1)[-1]
        record = applications.get(app_id)
        if record is None:
            return (404, {}, '{"code": "404"}')
        return (200, {}, _json.dumps({"count": 1, "patentFileWrapperDataBag": [record]}))

    responses.add_callback(
        responses.GET, re.compile(rf"{re.escape(USPTO_API_BASE)}(/.*)?$"), callback=_dispatch
    )

    def _download_callback(request):
        content = doc_bytes.get(request.url)
        if content is None:
            return (404, {}, "")
        return (200, {}, content)

    responses.add_callback(responses.GET, re.compile(r"https://api\.uspto\.gov/api/v1/download/.*"), callback=_download_callback)


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), queries_file=str(tmp_path / "queries.yaml"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch, queries_yaml=QUERIES_YAML):
    (tmp_path / "queries.yaml").write_text(queries_yaml)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USPTO_API_KEY", "test-key")
    import jobs.uspto.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)


def _manifest_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto.parquet")


def _attempts_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_attempts.parquet")


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': ["111"]})

    result = USPTOJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 1
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "uspto.parquet").exists()


@responses.activate
def test_full_run_writes_manifest_discovery_attempts_and_documents(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    app = _application("111", title="ADC Patent")
    doc_url = "https://api.uspto.gov/api/v1/download/applications/DOC1.pdf"
    _register_uspto(
        {'"antibody-drug conjugate"': ["111"]},
        applications={"111": app},
        documents={"111": _document_bag("DOC1", doc_url)},
        doc_bytes={doc_url: b"%PDF specification text"},
    )

    result = USPTOJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["source_record_id"] == "111"
    assert df.iloc[0]["title"] == "ADC Patent"
    assert df.iloc[0]["applicants"] == ["Acme Pharma"]

    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_documents.parquet")
    assert len(docs_df) == 1
    assert docs_df.iloc[0]["source_record_id"] == "111:DOC1"
    assert docs_df.iloc[0]["parent_record_id"] == "111"
    assert docs_df.iloc[0]["document_code"] == "SPEC"

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_discovery.parquet")
    assert discovery_df.iloc[0]["source_record_id"] == "111"
    assert discovery_df.iloc[0]["query_id"] == "USPTO_TEST_PHRASE"

    report_text = (tmp_path / "reports" / "acquisition" / "uspto.md").read_text()
    assert "USPTO (Job 09)" in report_text


@responses.activate
def test_rerun_with_unchanged_content_skips_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    app = _application("111")
    doc_url = "https://api.uspto.gov/api/v1/download/applications/DOC1.pdf"
    _register_uspto(
        {'"antibody-drug conjugate"': ["111"]},
        applications={"111": app},
        documents={"111": _document_bag("DOC1", doc_url)},
        doc_bytes={doc_url: b"%PDF specification text"},
    )
    USPTOJob().run(_base_args(tmp_path))
    second = USPTOJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 1
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert (df["version"] == 1).all()

    doc_attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_documents_attempts.parquet")
    latest_doc_status = doc_attempts.sort_values("attempted_at").iloc[-1]["status"]
    assert latest_doc_status == "skipped_unchanged"


@responses.activate
def test_document_skip_is_identity_based_not_hash_based(tmp_path, monkeypatch):
    """Live-verified finding: USPTO's document download endpoints
    dynamically re-render bytes on every request (different bytes each
    fetch of the SAME documentIdentifier), so hash comparison can never
    detect "unchanged" -- documents must be skipped based on
    documentIdentifier already having a successful attempt, not on a
    content hash match. This test simulates that dynamic-rendering
    behavior directly: the second fetch would return DIFFERENT bytes if
    it were ever attempted, and asserts it is not attempted at all."""
    _setup(tmp_path, monkeypatch)
    app = _application("111")
    doc_url = "https://api.uspto.gov/api/v1/download/applications/DOC1.pdf"
    _register_uspto(
        {'"antibody-drug conjugate"': ["111"]},
        applications={"111": app},
        documents={"111": _document_bag("DOC1", doc_url)},
        doc_bytes={doc_url: b"%PDF rendering number one"},
    )
    USPTOJob().run(_base_args(tmp_path))

    responses.calls.reset()
    _register_uspto(
        {'"antibody-drug conjugate"': ["111"]},
        applications={"111": app},
        documents={"111": _document_bag("DOC1", doc_url)},
        doc_bytes={doc_url: b"%PDF a completely different rendering"},  # simulates USPTO's dynamic re-render
    )
    USPTOJob().run(_base_args(tmp_path))

    download_calls = [c for c in responses.calls if "/download/" in c.request.url]
    assert download_calls == []  # no HTTP request at all -- identity-based skip, not hash-based

    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_documents.parquet")
    assert len(docs_df) == 1  # still just the one version from the original fetch
    assert docs_df.iloc[0]["version"] == 1


@responses.activate
def test_document_third_consecutive_run_still_skips_without_fetch(tmp_path, monkeypatch):
    """Self-caught regression, identical bug class to Job 08/WIPO's round-1
    fix: _resolved_document_keys() must treat a "skipped_unchanged"
    most-recent-attempt as resolved too, or a document falls back to
    "unresolved" and gets needlessly refetched on the THIRD run (the
    second run's attempt row is skipped_unchanged, not success)."""
    _setup(tmp_path, monkeypatch)
    app = _application("111")
    doc_url = "https://api.uspto.gov/api/v1/download/applications/DOC1.pdf"
    _register_uspto(
        {'"antibody-drug conjugate"': ["111"]},
        applications={"111": app},
        documents={"111": _document_bag("DOC1", doc_url)},
        doc_bytes={doc_url: b"%PDF specification text"},
    )
    USPTOJob().run(_base_args(tmp_path))  # run 1: success
    USPTOJob().run(_base_args(tmp_path))  # run 2: skipped_unchanged (fast path)

    responses.calls.reset()
    USPTOJob().run(_base_args(tmp_path))  # run 3: must still skip, not re-fetch

    download_calls = [c for c in responses.calls if "/download/" in c.request.url]
    assert download_calls == []


@responses.activate
def test_documents_still_attempted_when_primary_application_fetch_fails(tmp_path, monkeypatch):
    """Round-1 self-caught bug: document acquisition was nested inside the
    primary application's own success path, so a failed (or unchanged)
    primary fetch silently suppressed document acquisition entirely. Same
    principle as SEC's exhibits: a primary-record outcome must never gate
    the secondary artifact's own independent attempt."""
    _setup(tmp_path, monkeypatch)
    doc_url = "https://api.uspto.gov/api/v1/download/applications/DOC1.pdf"
    # No application registered for "111" -> get_application() 404s, but
    # documents ARE registered and must still be fetched.
    _register_uspto(
        {'"antibody-drug conjugate"': ["111"]},
        documents={"111": _document_bag("DOC1", doc_url)},
        doc_bytes={doc_url: b"%PDF specification text"},
    )

    result = USPTOJob().run(_base_args(tmp_path))

    assert result.records_failed == 1  # the primary application fetch itself failed
    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_documents.parquet")
    assert len(docs_df) == 1  # but its document was still discovered and downloaded
    assert docs_df.iloc[0]["parent_record_id"] == "111"


@responses.activate
def test_changed_application_content_creates_new_version(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': ["111"]}, applications={"111": _application("111", status="Docketed New Case")})
    USPTOJob().run(_base_args(tmp_path))

    responses.reset()
    _register_uspto({'"antibody-drug conjugate"': ["111"]}, applications={"111": _application("111", status="Patented Case")})
    USPTOJob().run(_base_args(tmp_path))

    df = _manifest_df(tmp_path)
    versions = sorted(df.loc[df["source_record_id"] == "111", "version"])
    assert versions == [1, 2]


@responses.activate
def test_failed_application_retried_on_next_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': ["111"]})  # no application registered -> 404

    result1 = USPTOJob().run(_base_args(tmp_path))
    assert result1.records_failed == 1

    responses.reset()
    _register_uspto({'"antibody-drug conjugate"': ["111"]}, applications={"111": _application("111")})
    result2 = USPTOJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 1  # retried despite no --resume flag, since it's unresolved


@responses.activate
def test_limit_prioritizes_fresh_over_backlog(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, queries_yaml=TWO_QUERY_YAML)
    _register_uspto({"alpha": ["old_failed"], "beta": []})
    USPTOJob().run(_base_args(tmp_path))  # old_failed fails (no application registered)

    responses.reset()
    _register_uspto(
        {"alpha": ["old_failed", "new_fresh"], "beta": []},
        applications={"new_fresh": _application("new_fresh")},
    )
    result = USPTOJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert "new_fresh" in set(df["source_record_id"])  # fresh got the single --limit slot
    assert "old_failed" not in set(df["source_record_id"])  # backlog didn't starve it out


@responses.activate
def test_since_until_apply_as_server_side_date_filter(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    query_with_date = '"antibody-drug conjugate" AND applicationMetaData.filingDate:[2020-01-01 TO 2020-12-31]'
    _register_uspto({query_with_date: ["111"]}, applications={"111": _application("111")})

    result = USPTOJob().run(_base_args(tmp_path, since="2020-01-01", until="2020-12-31"))

    assert result.records_discovered == 1
    search_calls = [c for c in responses.calls if c.request.url.startswith(SEARCH_URL)]
    assert query_with_date in search_calls[0].request.params["q"]


@responses.activate
def test_query_version_from_registry_propagates_not_hardcoded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, queries_yaml=TWO_QUERY_YAML)
    _register_uspto({"alpha": [], "beta": ["111"]}, applications={"111": _application("111")})

    USPTOJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_discovery.parquet")
    row = discovery_df[discovery_df["query_id"] == "USPTO_TEST_B"].iloc[0]
    assert row["query_version"] == 3


@responses.activate
def test_multiple_queries_each_get_their_own_discovery_row(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, queries_yaml=TWO_QUERY_YAML)
    _register_uspto({"alpha": ["111"], "beta": ["111"]}, applications={"111": _application("111")})

    USPTOJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_discovery.parquet")
    matching = discovery_df[discovery_df["source_record_id"] == "111"]
    assert len(matching) == 2
    assert set(matching["query_id"]) == {"USPTO_TEST_A", "USPTO_TEST_B"}
    assert len(_manifest_df(tmp_path)) == 1


@responses.activate
def test_raw_json_persisted_before_parser_crash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': ["111"]}, applications={"111": _application("111")})

    import jobs.uspto.job as job_module

    def _boom(_raw):
        raise RuntimeError("simulated parser bug")

    monkeypatch.setattr(job_module, "parse_application", _boom)

    try:
        USPTOJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    raw_path = tmp_path / "DATA" / "raw" / "uspto" / "111" / "v1.json"
    assert raw_path.exists()

    attempts = _attempts_df(tmp_path)
    row = attempts[attempts["source_record_id"] == "111"].iloc[0]
    assert row["status"] == "parse_failed"
    assert row["version"] == 1


@responses.activate
def test_documents_processed_independently_of_application_document_list_failure(tmp_path, monkeypatch):
    """A document-listing failure for one application must not crash the
    whole run or block that application's own successful materialization."""
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': ["111"]}, applications={"111": _application("111")})
    # documents dict has no entry for "111" -> _documents_callback returns empty documentBag, not an error

    result = USPTOJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_documents.parquet")
    assert len(docs_df) == 0


@responses.activate
def test_empty_result_set_produces_empty_manifest_without_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': []})

    result = USPTOJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0


@responses.activate
def test_parse_failure_self_heals_without_new_version_when_content_unchanged(tmp_path, monkeypatch):
    """P0 acceptance test A (round-1 review): raw acquisition state
    (RAW_NAMESPACE) and "already fully materialized" are different facts.
    A parse_failed most-recent-attempt with UNCHANGED bytes must not be
    treated as resolved -- it must be reparsed using the SAME raw file (no
    new version) once the parser bug is fixed, not permanently stuck."""
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': ["111"]}, applications={"111": _application("111")})

    import jobs.uspto.job as job_module
    from jobs.uspto.parser import parse_application as real_parse_application

    def _boom(raw):
        raise RuntimeError("simulated parser bug")

    monkeypatch.setattr(job_module, "parse_application", _boom)
    try:
        USPTOJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    attempts = _attempts_df(tmp_path)
    assert attempts[attempts["source_record_id"] == "111"].iloc[-1]["status"] == "parse_failed"
    assert len(_manifest_df(tmp_path)) == 0  # no successful materialization yet

    monkeypatch.setattr(job_module, "parse_application", real_parse_application)
    responses.reset()
    _register_uspto({'"antibody-drug conjugate"': ["111"]}, applications={"111": _application("111")})  # SAME bytes

    result = USPTOJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1  # reparsed successfully, not classified skipped_unchanged
    df = _manifest_df(tmp_path)
    versions = sorted(df.loc[df["source_record_id"] == "111", "version"])
    assert versions == [1]  # same raw bytes reused -- no spurious v2 created


@responses.activate
def test_uncaught_crash_after_raw_durable_self_heals_next_run(tmp_path, monkeypatch):
    """P0 acceptance test B (round-1 review): an uncaught exception
    (not just a caught parser error) anywhere downstream of the raw write
    must not leave the NEXT run believing this application is already
    fully materialized -- unchanged bytes with no successful/
    skipped_unchanged attempt on record must be re-normalized."""
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': ["111"]}, applications={"111": _application("111")})

    import jobs.uspto.job as job_module
    real_new_manifest_row = job_module.new_manifest_row

    def _boom(*args, **kwargs):
        if kwargs.get("source_record_type") == "uspto_application":
            raise RuntimeError("simulated uncaught crash after raw write")
        return real_new_manifest_row(*args, **kwargs)

    monkeypatch.setattr(job_module, "new_manifest_row", _boom)
    try:
        USPTOJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    raw_path = tmp_path / "DATA" / "raw" / "uspto" / "111" / "v1.json"
    assert raw_path.exists()
    assert not (tmp_path / "DATA" / "manifests" / "uspto_attempts.parquet").exists()

    monkeypatch.setattr(job_module, "new_manifest_row", real_new_manifest_row)
    result = USPTOJob().run(_base_args(tmp_path))  # same bytes, no crash this time

    assert result.records_downloaded == 1  # re-normalized, NOT skipped_unchanged
    df = _manifest_df(tmp_path)
    versions = sorted(df.loc[df["source_record_id"] == "111", "version"])
    assert versions == [1]  # same raw file reused, no new version


@responses.activate
def test_limit_reverify_does_not_starve_fresh_ids_forever(tmp_path, monkeypatch):
    """P0 acceptance test (round-1 review): fresh_ids previously excluded
    only `failed`, so an already-successful application was wrongly
    treated as "fresh" too. Under a small --limit that meant the same
    already-successful id would be re-verified every run while a
    genuinely fresh id discovered later could be starved out forever."""
    _setup(tmp_path, monkeypatch)
    _register_uspto({'"antibody-drug conjugate"': ["100"]}, applications={"100": _application("100")})
    USPTOJob().run(_base_args(tmp_path, limit=1))  # "100" succeeds -- now a "reverify" candidate

    responses.reset()
    _register_uspto(
        {'"antibody-drug conjugate"': ["100", "200"]},
        applications={"100": _application("100"), "200": _application("200")},
    )
    result = USPTOJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert "200" in set(df["source_record_id"])  # the genuinely fresh id got the single slot
    assert (df.loc[df["source_record_id"] == "200", "version"] == 1).all()


@responses.activate
def test_document_raw_checkpoint_survives_uncaught_crash_before_ledger_flush(tmp_path, monkeypatch):
    """P0 acceptance test (round-1 review), documents variant: a
    DOCUMENT_NAMESPACE checkpoint entry is saved to disk immediately after
    a document's raw write, but the documents manifest/attempts ledger is
    only flushed once, at the end of run(). An uncaught exception between
    those two points must not cause the NEXT run to re-download this
    document -- USPTO's /download bytes are not reproducible across
    requests, so a re-download would silently overwrite the already-
    durable raw file with different bytes."""
    _setup(tmp_path, monkeypatch)
    app = _application("111")
    doc_url = "https://api.uspto.gov/api/v1/download/applications/DOC1.pdf"
    _register_uspto(
        {'"antibody-drug conjugate"': ["111"]},
        applications={"111": app},
        documents={"111": _document_bag("DOC1", doc_url)},
        doc_bytes={doc_url: b"%PDF rendering one"},
    )

    import jobs.uspto.job as job_module
    real_new_manifest_row = job_module.new_manifest_row

    def _boom(*args, **kwargs):
        if kwargs.get("source_record_type") == "uspto_document":
            raise RuntimeError("simulated uncaught crash after checkpoint save")
        return real_new_manifest_row(*args, **kwargs)

    monkeypatch.setattr(job_module, "new_manifest_row", _boom)
    try:
        USPTOJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    # The document ledger was never flushed (crash happened before
    # end-of-run write), but the raw file + checkpoint ARE durable.
    assert not (tmp_path / "DATA" / "manifests" / "uspto_documents.parquet").exists()
    raw_doc_path = tmp_path / "DATA" / "raw" / "uspto" / "111" / "documents" / "v1_DOC1.pdf"
    assert raw_doc_path.exists()
    assert raw_doc_path.read_bytes() == b"%PDF rendering one"

    monkeypatch.setattr(job_module, "new_manifest_row", real_new_manifest_row)
    responses.calls.reset()
    _register_uspto(
        {'"antibody-drug conjugate"': ["111"]},
        applications={"111": app},
        documents={"111": _document_bag("DOC1", doc_url)},
        doc_bytes={doc_url: b"%PDF a DIFFERENT rendering -- would overwrite if refetched"},
    )

    USPTOJob().run(_base_args(tmp_path))

    download_calls = [c for c in responses.calls if "/download/" in c.request.url]
    assert download_calls == []  # reconstructed from checkpoint, not re-downloaded
    assert raw_doc_path.read_bytes() == b"%PDF rendering one"  # untouched

    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "uspto_documents.parquet")
    assert len(docs_df) == 1
    assert docs_df.iloc[0]["version"] == 1
