import argparse
import json as json_module
import re
from urllib.parse import parse_qsl, urlparse

import pandas as pd
import responses

from jobs.fda.client import DRUG_LABEL_URL, DRUGSFDA_URL
from jobs.fda.job import FDAJob

QUERIES_YAML = """
queries:
  - query_id: FDA_LABEL_MOA_001
    query_version: 1
    query_text: 'mechanism_of_action:"antibody-drug conjugate"'
    purpose: test moa query
    active: true
  - query_id: FDA_LABEL_DESC_001
    query_version: 1
    query_text: 'description:"antibody-drug conjugate"'
    purpose: test description query
    active: true
"""

MOA_QUERY = 'mechanism_of_action:"antibody-drug conjugate"'
DESC_QUERY = 'description:"antibody-drug conjugate"'

DOC_URL_A1 = "https://www.accessdata.fda.gov/drugsatfda_docs/label/2011/125388s000lbl.pdf"
DOC_URL_A2 = "https://www.accessdata.fda.gov/drugsatfda_docs/appletter/2011/125388s000ltr.pdf"


def _label_hit(application_number):
    return {"openfda": {"application_number": [application_number]}}


def _submission(sub_type, number, status_date, docs=None):
    entry = {
        "submission_type": sub_type,
        "submission_number": number,
        "submission_status": "AP",
        "submission_status_date": status_date,
        "submission_class_code": "EFFICACY",
        "submission_class_code_description": "Efficacy",
    }
    if docs is not None:
        entry["application_docs"] = docs
    return entry


def _drugsfda_record(application_number, submissions):
    return {"application_number": application_number, "sponsor_name": "TEST SPONSOR", "submissions": submissions}


def _register_fda(label_results=None, drugsfda_records=None, documents=None):
    label_results = label_results if label_results is not None else {}
    drugsfda_records = drugsfda_records if drugsfda_records is not None else {}
    documents = documents if documents is not None else {}

    def _label_callback(request):
        params = dict(parse_qsl(urlparse(request.url).query))
        results = label_results.get(params.get("search", ""), [])
        if not results:
            return (404, {}, json_module.dumps({"error": {"code": "NOT_FOUND"}}))
        return (200, {}, json_module.dumps({"results": results}))

    def _drugsfda_callback(request):
        params = dict(parse_qsl(urlparse(request.url).query))
        m = re.search(r'application_number:"([^"]+)"', params.get("search", ""))
        app = m.group(1) if m else None
        record = drugsfda_records.get(app)
        if record is None:
            return (404, {}, json_module.dumps({"error": {"code": "NOT_FOUND"}}))
        return (200, {}, json_module.dumps({"results": [record]}))

    def _document_callback(request):
        content = documents.get(request.url)
        if content is None:
            return (404, {}, "")
        return (200, {}, content)

    responses.add_callback(responses.GET, DRUG_LABEL_URL, callback=_label_callback)
    responses.add_callback(responses.GET, DRUGSFDA_URL, callback=_drugsfda_callback)
    responses.add_callback(responses.GET, re.compile(r"https://www\.accessdata\.fda\.gov/.*"), callback=_document_callback)


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
    monkeypatch.delenv("FDA_API_KEY", raising=False)
    import jobs.fda.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)


def _metadata_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "fda.parquet")


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: [_label_hit("BLA2")]},
        drugsfda_records={
            "BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "2020-01-01".replace("-", ""))]),
            "BLA2": _drugsfda_record("BLA2", [_submission("ORIG", "1", "20200101")]),
        },
    )

    result = FDAJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 2
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "fda.parquet").exists()


@responses.activate
def test_full_run_writes_submissions_and_documents(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    docs = [
        {"id": "d1", "url": DOC_URL_A1, "date": "20110819", "type": "Label"},
        {"id": "d2", "url": DOC_URL_A2, "date": "20110819", "type": "Letter"},
    ]
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20110819", docs=docs)])},
        documents={DOC_URL_A1: b"%PDF label", DOC_URL_A2: b"%PDF letter"},
    )

    result = FDAJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert result.records_downloaded == 1
    df = _metadata_df(tmp_path)
    assert df.iloc[0]["source_record_id"] == "BLA1_ORIG1"
    assert df.iloc[0]["application_number"] == "BLA1"

    documents_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "fda_documents.parquet")
    assert len(documents_df) == 2
    assert set(documents_df["source_record_id"]) == {"BLA1_ORIG1:d1", "BLA1_ORIG1:d2"}
    assert set(documents_df["parent_record_id"]) == {"BLA1_ORIG1"}
    assert set(documents_df["doc_type"]) == {"Label", "Letter"}

    report_text = (tmp_path / "reports" / "acquisition" / "fda.md").read_text()
    assert "FDA (Job 06)" in report_text


@responses.activate
def test_submission_with_no_docs_materializes_with_empty_document_set(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("SUPPL", "5", "20200101")])},
    )

    result = FDAJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    assert result.records_failed == 0
    documents_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "fda_documents.parquet")
    assert len(documents_df) == 0


@responses.activate
def test_document_404_is_a_failed_attempt_not_a_crash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    docs = [{"id": "d1", "url": DOC_URL_A1, "date": "20110819", "type": "Label"}]
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20110819", docs=docs)])},
        documents={},  # doc URL 404s
    )

    result = FDAJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1  # the submission itself always succeeds
    documents_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "fda_documents.parquet")
    assert len(documents_df) == 0
    doc_attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "fda_documents_attempts.parquet")
    assert doc_attempts.iloc[0]["status"] == "failed"


@responses.activate
def test_application_discovered_but_drugsfda_lookup_404_is_not_a_crash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_fda(label_results={MOA_QUERY: [_label_hit("BLA-GHOST")], DESC_QUERY: []}, drugsfda_records={})

    result = FDAJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert len(_metadata_df(tmp_path)) == 0


@responses.activate
def test_discovery_ledger_records_query_provenance(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: [_label_hit("BLA1")]},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20200101")])},
    )

    result = FDAJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "fda_discovery.parquet")
    assert set(discovery_df["query_id"]) == {"FDA_LABEL_MOA_001", "FDA_LABEL_DESC_001"}
    assert len(discovery_df) == 2  # one submission, discovered by both queries
    assert result.notes and "matched more than one discovery query" in result.notes[-1]


@responses.activate
def test_since_until_filters_by_submission_status_date(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    subs = [
        _submission("ORIG", "1", "20190601"),
        _submission("SUPPL", "1", "20220601"),
        _submission("SUPPL", "2", "20250601"),
    ]
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", subs)},
    )

    result = FDAJob().run(_base_args(tmp_path, dry_run=True, since="2022-01-01", until="2024-12-31"))

    assert result.records_discovered == 1


@responses.activate
def test_rerun_with_unchanged_content_skips_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20200101")])},
    )

    FDAJob().run(_base_args(tmp_path))
    second = FDAJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 1
    df = _metadata_df(tmp_path)
    assert len(df) == 1
    assert (df["version"] == 1).all()


@responses.activate
def test_new_document_added_to_existing_submission_creates_v2(tmp_path, monkeypatch):
    """A submission's content_hash includes its docs list, so a doc being
    added later (without submission_number changing) must version the
    submission row -- not silently leave it at v1 forever."""
    _setup(tmp_path, monkeypatch)
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20200101")])},
    )
    FDAJob().run(_base_args(tmp_path))

    responses.reset()
    docs = [{"id": "d1", "url": DOC_URL_A1, "date": "20200102", "type": "Label"}]
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20200101", docs=docs)])},
        documents={DOC_URL_A1: b"%PDF label"},
    )
    FDAJob().run(_base_args(tmp_path))

    df = _metadata_df(tmp_path)
    versions = sorted(df[df["source_record_id"] == "BLA1_ORIG1"]["version"].tolist())
    assert versions == [1, 2]


@responses.activate
def test_document_fetch_failure_never_touches_submission_snapshot(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    docs = [{"id": "d1", "url": DOC_URL_A1, "date": "20200101", "type": "Label"}]
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20200101", docs=docs)])},
        documents={},  # doc always 404s
    )

    result = FDAJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _metadata_df(tmp_path)
    assert len(df) == 1


@responses.activate
def test_document_content_change_creates_v2_without_touching_v1(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    docs = [{"id": "d1", "url": DOC_URL_A1, "date": "20200101", "type": "Label"}]
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20200101", docs=docs)])},
        documents={DOC_URL_A1: b"original label"},
    )
    FDAJob().run(_base_args(tmp_path))
    v1_path = next((tmp_path / "DATA" / "raw" / "fda" / "BLA1_ORIG1" / "documents").glob("v1_*"))
    assert v1_path.read_bytes() == b"original label"

    responses.reset()
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20200101", docs=docs)])},
        documents={DOC_URL_A1: b"revised label"},
    )
    FDAJob().run(_base_args(tmp_path))

    assert v1_path.read_bytes() == b"original label"
    v2_path = next((tmp_path / "DATA" / "raw" / "fda" / "BLA1_ORIG1" / "documents").glob("v2_*"))
    assert v2_path.read_bytes() == b"revised label"


@responses.activate
def test_resume_retries_unresolved_old_document_failure(tmp_path, monkeypatch):
    """Applying SEC Job 05's post-review --resume design proactively: the
    cursor advances unconditionally, but an unresolved document failure
    from before the cursor must still be retried, and self-heal once it
    resolves."""
    _setup(tmp_path, monkeypatch)
    OLD = "BLA1_ORIG1"
    docs = [{"id": "d1", "url": DOC_URL_A1, "date": "20190101", "type": "Label"}]
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20190601", docs=docs)])},
        documents={},  # doc 404s
    )
    result1 = FDAJob().run(_base_args(tmp_path, until="2020-01-01"))
    assert result1.records_downloaded == 1
    doc_attempts1 = pd.read_parquet(tmp_path / "DATA" / "manifests" / "fda_documents_attempts.parquet")
    assert doc_attempts1[doc_attempts1["parent_record_id"] == OLD].iloc[0]["status"] == "failed"

    responses.reset()
    # Second run: nothing new discovered/in-range, but the doc now resolves.
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20190601", docs=docs)])},
        documents={DOC_URL_A1: b"%PDF now available"},
    )
    result2 = FDAJob().run(_base_args(tmp_path, resume=True))

    documents_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "fda_documents.parquet")
    assert len(documents_df) == 1
    assert documents_df.iloc[0]["parent_record_id"] == OLD
    assert result2.records_skipped_unchanged == 1  # OLD's submission row, re-attempted but unchanged


@responses.activate
def test_resume_fresh_submissions_not_starved_by_backlog_retries(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    old_subs = [_submission("SUPPL", str(i), "20100101", docs=[{"id": f"d{i}", "url": f"https://www.accessdata.fda.gov/x/{i}.pdf", "date": "20100101", "type": "Label"}]) for i in range(25)]
    new_sub = _submission("SUPPL", "999", "20250601")
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", old_subs)},
        documents={},  # all docs 404
    )
    result1 = FDAJob().run(_base_args(tmp_path, until="2010-12-31", limit=30))
    assert result1.records_downloaded == 25

    responses.reset()
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", old_subs + [new_sub])},
        documents={},
    )
    result2 = FDAJob().run(_base_args(tmp_path, resume=True, limit=20))

    df = _metadata_df(tmp_path)
    assert "BLA1_SUPPL999" in set(df["source_record_id"])  # must not be starved out


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_fda(
        label_results={MOA_QUERY: [_label_hit("BLA1")], DESC_QUERY: []},
        drugsfda_records={"BLA1": _drugsfda_record("BLA1", [_submission("ORIG", "1", "20200101"), _submission("SUPPL", "1", "20210101")])},
    )

    result = FDAJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    assert len(_metadata_df(tmp_path)) == 1


@responses.activate
def test_empty_result_set_produces_empty_manifest_without_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_fda(label_results={}, drugsfda_records={})

    result = FDAJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert len(_metadata_df(tmp_path)) == 0
