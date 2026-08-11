import argparse
import json as json_module
import re

import pandas as pd
import responses

from jobs.sec.client import SEC_ARCHIVES_BASE, SEC_DATA_BASE
from jobs.sec.job import SECJob

REGISTRY_YAML = """
companies:
  - company_id: company_a
    canonical_name: Company A Inc.
    cik: "0000001000"
    aliases: []
    tickers: []
    active: true
    notes: null
  - company_id: company_b
    canonical_name: Company B Inc.
    cik: "0000002000"
    aliases: []
    tickers: []
    active: true
    notes: null
  - company_id: company_c_inactive
    canonical_name: Company C Inc.
    cik: "0000003000"
    aliases: []
    tickers: []
    active: false
    notes: null
"""


def _recent(accession_numbers, forms, filing_dates, primary_documents, items=None):
    n = len(accession_numbers)
    return {
        "accessionNumber": accession_numbers,
        "form": forms,
        "filingDate": filing_dates,
        "reportDate": filing_dates,
        "primaryDocument": primary_documents,
        "items": items or [""] * n,
        "fileNumber": ["001-00000"] * n,
        "filmNumber": ["12345"] * n,
    }


ACC_A1 = "0000001000-20-000001"
ACC_A2 = "0000001000-20-000002"
ACC_B1 = "0000002000-20-000001"

RECENT_A = _recent([ACC_A1, ACC_A2], ["8-K", "10-Q"], ["2020-01-01", "2020-04-01"], ["a1.htm", "a2.htm"])
RECENT_B = _recent([ACC_B1], ["10-K"], ["2020-03-01"], ["b1.htm"])


def _acc_no_dashes(accession_number):
    return accession_number.replace("-", "")


def _register_sec(
    submissions_by_cik=None,
    documents=None,
    filing_indexes=None,
    submission_pages=None,
):
    submissions_by_cik = submissions_by_cik or {"0000001000": RECENT_A, "0000002000": RECENT_B}
    documents = documents if documents is not None else {}
    filing_indexes = filing_indexes if filing_indexes is not None else {}
    submission_pages = submission_pages or {}

    def _submissions_callback(request):
        m = re.search(r"CIK(\d{10})\.json", request.url)
        cik = m.group(1)
        recent = submissions_by_cik.get(cik, {"accessionNumber": []})
        return (200, {}, json_module.dumps({"filings": {"recent": recent, "files": []}}))

    def _page_callback(request):
        file_name = request.url.rsplit("/", 1)[-1]
        recent = submission_pages.get(file_name, {"accessionNumber": []})
        return (200, {}, json_module.dumps(recent))

    def _index_callback(request):
        m = re.search(rf"{re.escape(SEC_ARCHIVES_BASE)}/(\d+)/(\d+)/index\.json", request.url)
        cik_no_zeros, acc_no_dashes = m.group(1), m.group(2)
        names = filing_indexes.get((cik_no_zeros, acc_no_dashes), [])
        return (200, {}, json_module.dumps({"directory": {"item": [{"name": n} for n in names]}}))

    def _document_callback(request):
        m = re.search(rf"{re.escape(SEC_ARCHIVES_BASE)}/(\d+)/(\d+)/(.+)$", request.url)
        cik_no_zeros, acc_no_dashes, filename = m.group(1), m.group(2), m.group(3)
        content = documents.get((cik_no_zeros, acc_no_dashes, filename))
        if content is None:
            return (404, {}, "")
        return (200, {}, content)

    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_DATA_BASE)}/submissions/CIK\d{{10}}\.json"), callback=_submissions_callback)
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_DATA_BASE)}/submissions/(?!CIK\d{{10}}\.json).+"), callback=_page_callback)
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_ARCHIVES_BASE)}/\d+/\d+/index\.json"), callback=_index_callback)
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_ARCHIVES_BASE)}/\d+/\d+/(?!index\.json).+"), callback=_document_callback)


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), registry_file=str(tmp_path / "registry.yaml"), company=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch):
    (tmp_path / "registry.yaml").write_text(REGISTRY_YAML)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "test@example.com")
    # Rate limit is a real time.sleep() against mocked HTTP otherwise.
    import jobs.sec.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)


def _metadata_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec.parquet")


def _default_documents():
    return {
        ("1000", _acc_no_dashes(ACC_A1), "a1.htm"): b"<html>A filing 1</html>",
        ("1000", _acc_no_dashes(ACC_A2), "a2.htm"): b"<html>A filing 2</html>",
        ("2000", _acc_no_dashes(ACC_B1), "b1.htm"): b"<html>B filing 1</html>",
    }


@responses.activate
def test_missing_sec_contact_email_raises(tmp_path, monkeypatch):
    (tmp_path / "registry.yaml").write_text(REGISTRY_YAML)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    # load_dotenv() walks up from jobs/sec/job.py's location (not cwd), so
    # it would otherwise find this real repo's .env and reintroduce the var.
    import jobs.sec.job as job_module
    monkeypatch.setattr(job_module, "load_dotenv", lambda: None)
    try:
        SECJob().run(_base_args(tmp_path))
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "SEC_CONTACT_EMAIL" in str(exc)


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec()

    result = SECJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 3  # 2 from company A, 1 from company B
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "sec.parquet").exists()


@responses.activate
def test_only_active_companies_are_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec()

    result = SECJob().run(_base_args(tmp_path, dry_run=True))

    assert result.queries_run == 2  # company_c_inactive excluded


@responses.activate
def test_full_run_writes_filings_and_exhibits(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    documents = _default_documents()
    documents[("1000", _acc_no_dashes(ACC_A1), "a1-ex.htm")] = b"<html>exhibit</html>"
    _register_sec(
        documents=documents,
        filing_indexes={("1000", _acc_no_dashes(ACC_A1)): ["a1.htm", "a1-ex.htm", "0000001000-20-000001-index.htm"]},
    )

    result = SECJob().run(_base_args(tmp_path))

    assert result.records_discovered == 3
    assert result.records_downloaded == 3
    assert result.records_failed == 0

    df = _metadata_df(tmp_path)
    assert set(df["source_record_id"]) == {"0000001000-20-000001", "0000001000-20-000002", "0000002000-20-000001"}

    exhibits_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits.parquet")
    assert len(exhibits_df) == 1
    assert exhibits_df.iloc[0]["source_record_id"] == "0000001000-20-000001:a1-ex.htm"
    assert exhibits_df.iloc[0]["parent_record_id"] == "0000001000-20-000001"

    report_text = (tmp_path / "reports" / "acquisition" / "sec.md").read_text()
    assert "SEC EDGAR (Job 05)" in report_text


@responses.activate
def test_discovery_ledger_records_company_provenance(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec()

    SECJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_discovery.parquet")
    assert set(discovery_df["source_record_id"]) == {
        "0000001000-20-000001", "0000001000-20-000002", "0000002000-20-000001",
    }
    assert discovery_df[discovery_df["source_record_id"] == "0000002000-20-000001"]["query_id"].iloc[0] == "SEC_FILINGS_COMPANY_B"


@responses.activate
def test_rerun_with_unchanged_content_skips_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec(documents=_default_documents())

    SECJob().run(_base_args(tmp_path))
    second = SECJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 3
    df = _metadata_df(tmp_path)
    assert len(df) == 3
    assert (df["version"] == 1).all()


@responses.activate
def test_missing_primary_document_is_a_failed_attempt_not_a_crash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    recent_a = _recent(["0000001000-20-000001"], ["8-K"], ["2020-01-01"], [""])  # empty primaryDocument
    _register_sec(submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}})

    result = SECJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    assert result.records_downloaded == 0
    content_df = _metadata_df(tmp_path)
    assert len(content_df) == 0
    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_attempts.parquet")
    assert attempts_df.iloc[0]["error"] == "no_primary_document"


@responses.activate
def test_document_404_is_a_failed_attempt_not_a_crash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec(documents={})  # every document 404s

    result = SECJob().run(_base_args(tmp_path))

    assert result.records_failed == 3
    assert result.records_downloaded == 0
    assert len(_metadata_df(tmp_path)) == 0


@responses.activate
def test_exhibit_fetch_failure_never_touches_filing_snapshot(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    documents = _default_documents()  # exhibit "a1-ex.htm" deliberately absent -> 404s
    _register_sec(
        documents=documents,
        filing_indexes={("1000", _acc_no_dashes(ACC_A1)): ["a1.htm", "a1-ex.htm"]},
    )

    result = SECJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 3  # filing itself still succeeds
    filing_df = _metadata_df(tmp_path)
    assert len(filing_df) == 3

    exhibit_attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits_attempts.parquet")
    failed = exhibit_attempts[exhibit_attempts["source_record_id"] == "0000001000-20-000001:a1-ex.htm"]
    assert failed.iloc[0]["status"] == "failed"
    exhibits_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits.parquet")
    assert len(exhibits_df) == 0  # never materialized


@responses.activate
def test_exhibit_content_change_creates_v2_without_touching_v1(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    documents = _default_documents()
    documents[("1000", _acc_no_dashes(ACC_A1), "a1-ex.htm")] = b"original exhibit"
    _register_sec(documents=documents, filing_indexes={("1000", _acc_no_dashes(ACC_A1)): ["a1.htm", "a1-ex.htm"]})

    SECJob().run(_base_args(tmp_path))
    v1_path = next((tmp_path / "DATA" / "raw" / "sec" / "0000001000-20-000001" / "exhibits").glob("v1_*"))
    assert v1_path.read_bytes() == b"original exhibit"

    responses.reset()
    documents[("1000", _acc_no_dashes(ACC_A1), "a1-ex.htm")] = b"revised exhibit"
    _register_sec(documents=documents, filing_indexes={("1000", _acc_no_dashes(ACC_A1)): ["a1.htm", "a1-ex.htm"]})
    SECJob().run(_base_args(tmp_path))

    assert v1_path.read_bytes() == b"original exhibit"
    v2_path = next((tmp_path / "DATA" / "raw" / "sec" / "0000001000-20-000001" / "exhibits").glob("v2_*"))
    assert v2_path.read_bytes() == b"revised exhibit"

    exhibits_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits.parquet")
    versions = sorted(exhibits_df[exhibits_df["parent_record_id"] == "0000001000-20-000001"]["version"].tolist())
    assert versions == [1, 2]


@responses.activate
def test_company_filter_restricts_to_one_company(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec()

    result = SECJob().run(_base_args(tmp_path, dry_run=True, company="company_b"))

    assert result.queries_run == 1
    assert result.records_discovered == 1


@responses.activate
def test_pagination_follows_files_list_for_older_filings(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    older_page = _recent(["0000001000-15-000001"], ["10-K"], ["2015-01-01"], ["old.htm"])

    def _submissions_callback(request):
        return (200, {}, json_module.dumps({
            "filings": {
                "recent": RECENT_A,
                "files": [{"name": "CIK0000001000-submissions-001.json"}],
            }
        }))

    responses.add_callback(
        responses.GET,
        re.compile(rf"{re.escape(SEC_DATA_BASE)}/submissions/CIK0000001000\.json"),
        callback=_submissions_callback,
    )
    responses.add(
        responses.GET,
        f"{SEC_DATA_BASE}/submissions/CIK0000001000-submissions-001.json",
        json=older_page,
    )
    responses.add_callback(
        responses.GET,
        re.compile(rf"{re.escape(SEC_DATA_BASE)}/submissions/CIK0000002000\.json"),
        callback=lambda r: (200, {}, json_module.dumps({"filings": {"recent": RECENT_B, "files": []}})),
    )
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_ARCHIVES_BASE)}/\d+/\d+/index\.json"), callback=lambda r: (200, {}, json_module.dumps({"directory": {"item": []}})))

    result = SECJob().run(_base_args(tmp_path, dry_run=True, company="company_a"))

    assert result.records_discovered == 3  # 2 recent + 1 from the older page


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec(documents=_default_documents())

    result = SECJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    assert len(_metadata_df(tmp_path)) == 1


@responses.activate
def test_empty_result_set_produces_empty_manifest_without_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec(submissions_by_cik={"0000001000": {"accessionNumber": []}, "0000002000": {"accessionNumber": []}})

    result = SECJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert len(_metadata_df(tmp_path)) == 0
