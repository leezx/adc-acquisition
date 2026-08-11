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
    ciks: ["0000001000"]
    aliases: []
    tickers: []
    active: true
    notes: null
  - company_id: company_b
    canonical_name: Company B Inc.
    ciks: ["0000002000"]
    aliases: []
    tickers: []
    active: true
    notes: null
  - company_id: company_c_inactive
    canonical_name: Company C Inc.
    ciks: ["0000003000"]
    aliases: []
    tickers: []
    active: false
    notes: null
"""

REGISTRY_YAML_MULTI_CIK = """
companies:
  - company_id: company_a
    canonical_name: Company A Inc.
    ciks: ["0000001000", "0000004000"]
    aliases: []
    tickers: []
    active: true
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


def _index_page_html(entries):
    """entries: list of (filename, doc_type, description) -- mirrors the
    real `{accession}-index.htm` "Document Format Files" table (see
    tests/jobs/sec/test_parser.py for a live-fetched sample)."""
    rows = "\n".join(
        f'<tr><td scope="row">{i + 1}</td><td scope="row">{description}</td>'
        f'<td scope="row"><a href="/Archives/edgar/data/x/y/{filename}">{filename}</a></td>'
        f'<td scope="row">{doc_type}</td><td scope="row">100</td></tr>'
        for i, (filename, doc_type, description) in enumerate(entries)
    )
    return f'<div><p>Document Format Files</p><table class="tableFile">{rows}</table></div>'


def _register_sec(
    submissions_by_cik=None,
    documents=None,
    index_pages=None,
    submission_pages=None,
    index_page_failures=None,
):
    submissions_by_cik = submissions_by_cik or {"0000001000": RECENT_A, "0000002000": RECENT_B}
    documents = documents if documents is not None else {}
    index_pages = index_pages if index_pages is not None else {}
    submission_pages = submission_pages or {}
    index_page_failures = index_page_failures or set()

    def _submissions_callback(request):
        m = re.search(r"CIK(\d{10})\.json", request.url)
        cik = m.group(1)
        recent = submissions_by_cik.get(cik, {"accessionNumber": []})
        return (200, {}, json_module.dumps({"filings": {"recent": recent, "files": []}}))

    def _page_callback(request):
        file_name = request.url.rsplit("/", 1)[-1]
        recent = submission_pages.get(file_name, {"accessionNumber": []})
        return (200, {}, json_module.dumps(recent))

    def _index_page_callback(request):
        m = re.search(rf"{re.escape(SEC_ARCHIVES_BASE)}/(\d+)/(\d+)/[\d-]+-index\.htm$", request.url)
        cik_no_zeros, acc_no_dashes = m.group(1), m.group(2)
        if (cik_no_zeros, acc_no_dashes) in index_page_failures:
            return (404, {}, "")  # non-retriable, so the test doesn't sleep through real backoff
        entries = index_pages.get((cik_no_zeros, acc_no_dashes), [])
        return (200, {}, _index_page_html(entries))

    def _document_callback(request):
        m = re.search(rf"{re.escape(SEC_ARCHIVES_BASE)}/(\d+)/(\d+)/(.+)$", request.url)
        cik_no_zeros, acc_no_dashes, filename = m.group(1), m.group(2), m.group(3)
        content = documents.get((cik_no_zeros, acc_no_dashes, filename))
        if content is None:
            return (404, {}, "")
        return (200, {}, content)

    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_DATA_BASE)}/submissions/CIK\d{{10}}\.json"), callback=_submissions_callback)
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_DATA_BASE)}/submissions/(?!CIK\d{{10}}\.json).+"), callback=_page_callback)
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_ARCHIVES_BASE)}/\d+/\d+/[\d-]+-index\.htm$"), callback=_index_page_callback)
    responses.add_callback(responses.GET, re.compile(rf"{re.escape(SEC_ARCHIVES_BASE)}/\d+/\d+/(?!.*-index\.htm$).+"), callback=_document_callback)


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), registry_file=str(tmp_path / "registry.yaml"), company=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch, registry_yaml=REGISTRY_YAML):
    (tmp_path / "registry.yaml").write_text(registry_yaml)
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
        index_pages={("1000", _acc_no_dashes(ACC_A1)): [
            ("a1.htm", "8-K", "8-K"),
            ("a1-ex.htm", "EX-99.1", "EX-99.1"),
        ]},
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
    assert exhibits_df.iloc[0]["exhibit_type"] == "EX-99.1"

    report_text = (tmp_path / "reports" / "acquisition" / "sec.md").read_text()
    assert "SEC EDGAR (Job 05)" in report_text


@responses.activate
def test_graphic_and_primary_document_are_not_treated_as_exhibits(tmp_path, monkeypatch):
    """Blocker fix: only SEC's own EX-* typed documents count as exhibits --
    not every non-primary file in the filing directory (which would sweep
    in embedded images, XBRL data files, etc.)."""
    _setup(tmp_path, monkeypatch)
    documents = _default_documents()
    _register_sec(
        documents=documents,
        index_pages={("1000", _acc_no_dashes(ACC_A1)): [
            ("a1.htm", "8-K", "8-K"),
            ("a1_g1.jpg", "GRAPHIC", ""),
        ]},
    )

    SECJob().run(_base_args(tmp_path))

    exhibits_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits.parquet")
    assert len(exhibits_df) == 0


@responses.activate
def test_primary_document_failure_does_not_block_exhibit_acquisition(tmp_path, monkeypatch):
    """Blocker fix: exhibits/filing-index must be attempted even when the
    primary document itself has no primaryDocument or 404s."""
    _setup(tmp_path, monkeypatch)
    recent_a = _recent([ACC_A1], ["8-K"], ["2020-01-01"], [""])  # empty primaryDocument
    documents = {("1000", _acc_no_dashes(ACC_A1), "a1-ex.htm"): b"<html>exhibit</html>"}
    _register_sec(
        submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}},
        documents=documents,
        index_pages={("1000", _acc_no_dashes(ACC_A1)): [("a1-ex.htm", "EX-99.1", "EX-99.1")]},
    )

    result = SECJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    assert result.records_downloaded == 0
    exhibits_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits.parquet")
    assert len(exhibits_df) == 1
    assert exhibits_df.iloc[0]["parent_record_id"] == ACC_A1


@responses.activate
def test_since_until_filter_discovered_filings_by_filing_date(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    recent_a = _recent(
        ["0000001000-19-000001", "0000001000-22-000001", "0000001000-25-000001"],
        ["8-K", "10-Q", "8-K"],
        ["2019-06-01", "2022-06-01", "2025-06-01"],
        ["old.htm", "mid.htm", "new.htm"],
    )
    _register_sec(submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}})

    result = SECJob().run(_base_args(tmp_path, dry_run=True, since="2022-01-01", until="2024-12-31"))

    assert result.records_discovered == 1


@responses.activate
def test_resume_advances_cursor_but_still_retries_unresolved_old_failures(tmp_path, monkeypatch):
    """Blocker fix: --resume's implicit --since must not let an unresolved
    old failure permanently drop out of scope just because the cursor
    advanced past its filing_date -- while a genuinely resolved old filing
    must NOT be needlessly re-targeted forever."""
    _setup(tmp_path, monkeypatch)
    OLD_OK = "0000001000-19-000001"     # succeeds in run 1 -> must not reappear
    OLD_FAIL = "0000001000-19-000099"   # fails in run 1 -> must still be retried
    NEW = "0000001000-25-000001"        # beyond the cursor either way
    recent_a = _recent(
        [OLD_OK, OLD_FAIL, NEW],
        ["8-K", "8-K", "8-K"],
        ["2019-06-01", "2019-07-01", "2025-06-01"],
        ["old-ok.htm", "old-fail.htm", "new.htm"],
    )
    documents = {
        ("1000", _acc_no_dashes(OLD_OK), "old-ok.htm"): b"<html>old ok</html>",
        ("1000", _acc_no_dashes(NEW), "new.htm"): b"<html>new</html>",
    }
    _register_sec(
        submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}},
        documents=documents,
    )

    # First run: both 2019 filings are in scope (--until bounds them in);
    # old-fail.htm 404s since it's absent from `documents`.
    result1 = SECJob().run(_base_args(tmp_path, until="2020-01-01"))
    assert result1.records_downloaded == 1
    assert result1.records_failed == 1
    checkpoint = json_module.loads((tmp_path / "DATA" / "checkpoints" / "sec.json").read_text())
    assert checkpoint["last_success_max_date"] == "2020-01-01"  # cursor advances despite the failure

    responses.reset()
    _register_sec(
        submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}},
        documents=documents,
    )
    result2 = SECJob().run(_base_args(tmp_path, resume=True))

    # NEW (>= cursor) is discovered normally; OLD_FAIL is unioned back in
    # despite predating the cursor; OLD_OK (already resolved) is not.
    assert result2.records_downloaded == 1  # NEW succeeds
    assert result2.records_failed == 1      # OLD_FAIL fails again (still no document registered)
    df = _metadata_df(tmp_path)
    assert set(df["source_record_id"]) == {OLD_OK, NEW}
    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_attempts.parquet")
    run2_attempts = attempts_df[attempts_df["run_id"] == attempts_df["run_id"].iloc[-1]]
    assert set(run2_attempts["source_record_id"]) == {OLD_FAIL, NEW}


@responses.activate
def test_resume_retries_unresolved_old_exhibit_failure_even_if_primary_resolved(tmp_path, monkeypatch):
    """Blocker fix: an exhibit-only failure on an old, already-primary-
    resolved filing must also be unioned back in on --resume -- not just
    primary-document failures."""
    _setup(tmp_path, monkeypatch)
    OLD = "0000001000-19-000001"
    NEW = "0000001000-25-000001"
    recent_a = _recent(
        [OLD, NEW], ["8-K", "8-K"], ["2019-06-01", "2025-06-01"], ["old.htm", "new.htm"],
    )
    documents = {
        ("1000", _acc_no_dashes(OLD), "old.htm"): b"<html>old</html>",
        ("1000", _acc_no_dashes(NEW), "new.htm"): b"<html>new</html>",
    }
    index_pages = {("1000", _acc_no_dashes(OLD)): [
        ("old.htm", "8-K", "8-K"),
        ("old-ex.htm", "EX-99.1", "EX-99.1"),  # deliberately absent from `documents` -> 404s
    ]}
    _register_sec(
        submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}},
        documents=documents,
        index_pages=index_pages,
    )

    SECJob().run(_base_args(tmp_path, until="2020-01-01"))
    exhibit_attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits_attempts.parquet")
    old_ex_row = exhibit_attempts[exhibit_attempts["source_record_id"] == f"{OLD}:old-ex.htm"].iloc[0]
    assert old_ex_row["status"] == "failed"

    responses.reset()
    # Second run: the exhibit now resolves.
    documents[("1000", _acc_no_dashes(OLD), "old-ex.htm")] = b"<html>exhibit now available</html>"
    _register_sec(
        submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}},
        documents=documents,
        index_pages=index_pages,
    )
    result = SECJob().run(_base_args(tmp_path, resume=True))

    exhibits_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits.parquet")
    assert len(exhibits_df) == 1
    assert exhibits_df.iloc[0]["source_record_id"] == f"{OLD}:old-ex.htm"
    assert result.records_downloaded == 1  # NEW; OLD's primary is unchanged (skipped)
    assert result.records_skipped_unchanged == 1  # OLD's primary, re-attempted but unchanged


@responses.activate
def test_filing_index_failure_self_heals_once_it_succeeds(tmp_path, monkeypatch):
    """Blocker fix: the filing-index step needs its OWN success attempt
    row -- otherwise, once it fails once, its one and only ever-recorded
    attempt stays "failed" forever (nothing else writes a success for that
    identity), so it would never leave the unresolved retry set even after
    a later run's filing-index fetch genuinely succeeds."""
    _setup(tmp_path, monkeypatch)
    OLD = "0000001000-19-000001"
    NEW = "0000001000-25-000001"
    recent_a = _recent([OLD, NEW], ["8-K", "8-K"], ["2019-06-01", "2025-06-01"], ["old.htm", "new.htm"])
    documents = {
        ("1000", _acc_no_dashes(OLD), "old.htm"): b"<html>old</html>",
        ("1000", _acc_no_dashes(NEW), "new.htm"): b"<html>new</html>",
    }
    _register_sec(
        submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}},
        documents=documents,
        index_page_failures={("1000", _acc_no_dashes(OLD))},
    )

    SECJob().run(_base_args(tmp_path, until="2020-01-01"))
    attempts1 = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits_attempts.parquet")
    idx_row1 = attempts1[attempts1["source_record_id"] == f"{OLD}:__filing_index__"].iloc[0]
    assert idx_row1["status"] == "failed"

    responses.reset()
    # Second run: the filing-index page itself now resolves (no failures
    # registered at all).
    _register_sec(submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}}, documents=documents)
    SECJob().run(_base_args(tmp_path, resume=True))
    attempts2 = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_exhibits_attempts.parquet")
    idx_rows2 = attempts2[attempts2["source_record_id"] == f"{OLD}:__filing_index__"]
    assert idx_rows2.iloc[-1]["status"] == "success"

    responses.reset()
    _register_sec(submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}}, documents=documents)
    result3 = SECJob().run(_base_args(tmp_path, dry_run=True, resume=True))

    # OLD is now fully resolved (primary succeeded run 1, filing-index
    # succeeded run 2) -- self-healed out of the retry set, not unioned
    # back in a third time.
    assert result3.records_discovered == 0


@responses.activate
def test_resume_fresh_filings_are_not_starved_by_backlog_retries(tmp_path, monkeypatch):
    """Blocker fix: a backlog of old, still-failing-but-not-terminal
    filings must not be able to occupy an entire --resume --limit budget
    forever -- fresh/in-range filings always get priority."""
    _setup(tmp_path, monkeypatch)
    old_ids = [f"0000001000-10-{i:06d}" for i in range(25)]
    old_docs = [f"old{i}.htm" for i in range(25)]
    NEW = "0000001000-25-000001"
    recent_a = _recent(
        old_ids + [NEW],
        ["8-K"] * 25 + ["8-K"],
        ["2010-01-01"] * 25 + ["2025-06-01"],
        old_docs + ["new.htm"],
    )
    # None of the 25 old documents are registered -> always 404 (retryable,
    # not the terminal no_primary_document condition).
    documents = {("1000", _acc_no_dashes(NEW), "new.htm"): b"<html>new</html>"}
    _register_sec(submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}}, documents=documents)

    result1 = SECJob().run(_base_args(tmp_path, until="2010-12-31", limit=30))
    assert result1.records_failed == 25

    responses.reset()
    _register_sec(submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}}, documents=documents)
    result2 = SECJob().run(_base_args(tmp_path, resume=True, limit=20))

    df = _metadata_df(tmp_path)
    assert NEW in set(df["source_record_id"])  # must not be starved out by the 25-item backlog
    assert result2.records_downloaded == 1


@responses.activate
def test_no_primary_document_is_terminal_and_not_retried_forever(tmp_path, monkeypatch):
    """Blocker fix: unlike a genuine fetch failure, a permanently missing
    primaryDocument in SEC's own metadata must not occupy the --resume
    retry set forever."""
    _setup(tmp_path, monkeypatch)
    OLD = "0000001000-19-000001"
    NEW = "0000001000-25-000001"
    recent_a = _recent([OLD, NEW], ["8-K", "8-K"], ["2019-06-01", "2025-06-01"], ["", "new.htm"])
    documents = {("1000", _acc_no_dashes(NEW), "new.htm"): b"<html>new</html>"}
    _register_sec(submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}}, documents=documents)

    SECJob().run(_base_args(tmp_path, until="2020-01-01"))
    attempts_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_attempts.parquet")
    assert attempts_df[attempts_df["source_record_id"] == OLD].iloc[0]["error"] == "no_primary_document"

    responses.reset()
    _register_sec(submissions_by_cik={"0000001000": recent_a, "0000002000": {"accessionNumber": []}}, documents=documents)
    result2 = SECJob().run(_base_args(tmp_path, dry_run=True, resume=True))

    # OLD's primary is a terminal condition -- must not be unioned back in.
    assert result2.records_discovered == 1  # only NEW


@responses.activate
def test_discovery_ledger_records_company_provenance(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_sec()

    SECJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "sec_discovery.parquet")
    assert set(discovery_df["source_record_id"]) == {
        "0000001000-20-000001", "0000001000-20-000002", "0000002000-20-000001",
    }
    assert discovery_df[discovery_df["source_record_id"] == "0000002000-20-000001"]["query_id"].iloc[0] == "SEC_FILINGS_COMPANY_B_0000002000"


@responses.activate
def test_multi_cik_company_pulls_filings_from_both_filers(tmp_path, monkeypatch):
    """Blocker fix: a company can have more than one CIK (e.g. Zymeworks'
    2022 redomicile) -- every CIK's filing history must be pulled."""
    _setup(tmp_path, monkeypatch, registry_yaml=REGISTRY_YAML_MULTI_CIK)
    recent_predecessor = _recent(["0000004000-15-000001"], ["10-K"], ["2015-01-01"], ["pre.htm"])
    _register_sec(submissions_by_cik={"0000001000": RECENT_A, "0000004000": recent_predecessor})

    result = SECJob().run(_base_args(tmp_path, dry_run=True))

    assert result.queries_run == 2  # one per CIK
    assert result.records_discovered == 3  # 2 from CIK 1000 + 1 from CIK 4000


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
        index_pages={("1000", _acc_no_dashes(ACC_A1)): [
            ("a1.htm", "8-K", "8-K"),
            ("a1-ex.htm", "EX-99.1", "EX-99.1"),
        ]},
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
    index_pages = {("1000", _acc_no_dashes(ACC_A1)): [
        ("a1.htm", "8-K", "8-K"),
        ("a1-ex.htm", "EX-99.1", "EX-99.1"),
    ]}
    _register_sec(documents=documents, index_pages=index_pages)

    SECJob().run(_base_args(tmp_path))
    v1_path = next((tmp_path / "DATA" / "raw" / "sec" / "0000001000-20-000001" / "exhibits").glob("v1_*"))
    assert v1_path.read_bytes() == b"original exhibit"

    responses.reset()
    documents[("1000", _acc_no_dashes(ACC_A1), "a1-ex.htm")] = b"revised exhibit"
    _register_sec(documents=documents, index_pages=index_pages)
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
    responses.add_callback(
        responses.GET,
        re.compile(rf"{re.escape(SEC_ARCHIVES_BASE)}/\d+/\d+/[\d-]+-index\.htm$"),
        callback=lambda r: (200, {}, _index_page_html([])),
    )

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
