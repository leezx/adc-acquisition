import argparse
import io
import re

import openpyxl
import pandas as pd
import responses

from jobs.ema.client import EMA_MEDICINES_XLSX_URL
from jobs.ema.job import EMAJob

PATTERNS_YAML = """
substance_patterns:
  - vedotin
  - emtansine
"""


def _build_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(8):
        ws.append([None] * 39)
    header = [f"col_{i}" for i in range(39)]
    header[1], header[2], header[3], header[7] = (
        "Name of medicine", "EMA product number", "Medicine status", "Active substance",
    )
    header[8], header[25] = "Therapeutic area (MeSH)", "Marketing authorisation developer / applicant / holder"
    header[26] = "European Commission decision date"
    header[31] = "Marketing authorisation date"
    header[33] = "Withdrawal / expiry / revocation / lapse of marketing authorisation date"
    header[37], header[38] = "Last updated date", "Medicine URL"
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _medicine_row(name, product_number, active_substance, last_updated="01/01/2020", url=None):
    row = [None] * 39
    row[1], row[2], row[3], row[7], row[8] = name, product_number, "Authorised", active_substance, "Oncology"
    row[25] = "TEST HOLDER"
    row[26] = "01/01/2020"
    row[31] = "01/02/2020"
    row[37] = last_updated
    row[38] = url or f"https://www.ema.europa.eu/en/medicines/human/EPAR/{name.lower()}"
    return row


def _epar_html(docs):
    """docs: list of (doc_type, filename, last_updated_iso)"""
    cards = []
    for doc_type, filename, last_updated in docs:
        cards.append(
            f'<div class="file-language-links"><p class="language-meta" translate="no">English (EN)</p>'
            f'<time datetime="{last_updated}">x</time>'
            f'<a href="/en/documents/{doc_type}/{filename}">View</a></div>'
        )
    return "<html>" + "".join(cards) + "</html>"


def _register_ema(xlsx_bytes, epar_pages=None, documents=None, epar_failures=None):
    epar_pages = epar_pages if epar_pages is not None else {}
    documents = documents if documents is not None else {}
    epar_failures = epar_failures or set()

    responses.add(responses.GET, EMA_MEDICINES_XLSX_URL, body=xlsx_bytes)

    def _epar_callback(request):
        if request.url in epar_failures:
            return (404, {}, "")
        html = epar_pages.get(request.url, "<html>no docs</html>")
        return (200, {}, html)

    def _document_callback(request):
        content = documents.get(request.url)
        if content is None:
            return (404, {}, "")
        return (200, {}, content)

    responses.add_callback(
        responses.GET, re.compile(r"https://www\.ema\.europa\.eu/en/medicines/human/EPAR/.*"), callback=_epar_callback
    )
    responses.add_callback(
        responses.GET, re.compile(r"https://www\.ema\.europa\.eu/en/documents/(?!report/).*"), callback=_document_callback
    )


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), patterns_file=str(tmp_path / "patterns.yaml"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch):
    (tmp_path / "patterns.yaml").write_text(PATTERNS_YAML)
    monkeypatch.chdir(tmp_path)
    import jobs.ema.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)


def _metadata_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema.parquet")


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    xlsx = _build_xlsx([
        _medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin"),
        _medicine_row("Zebinix", "EMEA/H/C/000988", "eslicarbazepine acetate"),  # not an ADC
    ])
    _register_ema(xlsx)

    result = EMAJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 1
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "ema.parquet").exists()


@responses.activate
def test_full_run_writes_medicine_and_documents(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    xlsx = _build_xlsx([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")])
    epar_url = "https://www.ema.europa.eu/en/medicines/human/EPAR/adcetris"
    doc_url = "https://www.ema.europa.eu/en/documents/product-information/adcetris-epar-product-information_en.pdf"
    _register_ema(
        xlsx,
        epar_pages={epar_url: _epar_html([("product-information", "adcetris-epar-product-information_en.pdf", "2020-01-01T00:00:00Z")])},
        documents={doc_url: b"%PDF product info"},
    )

    result = EMAJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert result.records_downloaded == 1
    df = _metadata_df(tmp_path)
    assert df.iloc[0]["source_record_id"] == "EMEA/H/C/002455"
    assert df.iloc[0]["active_substance"] == "brentuximab vedotin"

    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents.parquet")
    assert len(docs_df) == 1
    assert docs_df.iloc[0]["source_record_id"] == "EMEA/H/C/002455:adcetris-epar-product-information_en.pdf"
    assert docs_df.iloc[0]["parent_record_id"] == "EMEA/H/C/002455"
    assert docs_df.iloc[0]["doc_type"] == "product-information"

    report_text = (tmp_path / "reports" / "acquisition" / "ema.md").read_text()
    assert "EMA (Job 07)" in report_text


@responses.activate
def test_document_404_is_a_failed_attempt_not_a_crash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    xlsx = _build_xlsx([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")])
    epar_url = "https://www.ema.europa.eu/en/medicines/human/EPAR/adcetris"
    _register_ema(
        xlsx,
        epar_pages={epar_url: _epar_html([("product-information", "missing_en.pdf", "2020-01-01T00:00:00Z")])},
        documents={},  # doc always 404s
    )

    result = EMAJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1  # the medicine itself always succeeds
    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents.parquet")
    assert len(docs_df) == 0
    doc_attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents_attempts.parquet")
    real = doc_attempts[~doc_attempts["source_record_id"].str.endswith("__epar_page__")]
    assert real.iloc[0]["status"] == "failed"


@responses.activate
def test_epar_page_failure_self_heals_once_it_succeeds(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    xlsx = _build_xlsx([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin", last_updated="01/01/2019")])
    epar_url = "https://www.ema.europa.eu/en/medicines/human/EPAR/adcetris"
    _register_ema(xlsx, epar_failures={epar_url})

    EMAJob().run(_base_args(tmp_path, until="2020-01-01"))
    attempts1 = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents_attempts.parquet")
    epar_row1 = attempts1[attempts1["source_record_id"] == "EMEA/H/C/002455:__epar_page__"].iloc[0]
    assert epar_row1["status"] == "failed"

    responses.reset()
    _register_ema(xlsx, epar_pages={epar_url: _epar_html([])})  # now resolves, no failures
    EMAJob().run(_base_args(tmp_path, resume=True))

    attempts2 = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents_attempts.parquet")
    epar_rows2 = attempts2[attempts2["source_record_id"] == "EMEA/H/C/002455:__epar_page__"]
    assert epar_rows2.iloc[-1]["status"] == "success"


@responses.activate
def test_resume_fresh_medicines_not_starved_by_backlog_retries(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    old_rows = [
        _medicine_row(f"Old{i}", f"EMEA/H/C/{i:06d}", "brentuximab vedotin", last_updated="01/01/2010")
        for i in range(25)
    ]
    new_row = _medicine_row("New1", "EMEA/H/C/999999", "brentuximab vedotin", last_updated="01/06/2025")
    xlsx = _build_xlsx(old_rows)
    _register_ema(xlsx, epar_failures=set())  # EPAR pages 200 with no docs by default

    result1 = EMAJob().run(_base_args(tmp_path, until="2010-12-31", limit=30))
    assert result1.records_downloaded == 25

    responses.reset()
    xlsx2 = _build_xlsx(old_rows + [new_row])
    _register_ema(xlsx2)
    result2 = EMAJob().run(_base_args(tmp_path, resume=True, limit=20))

    df = _metadata_df(tmp_path)
    assert "EMEA/H/C/999999" in set(df["source_record_id"])  # must not be starved out


@responses.activate
def test_since_until_filters_by_last_updated_date(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    xlsx = _build_xlsx([
        _medicine_row("A", "EMEA/H/C/1", "vedotin", last_updated="01/06/2019"),
        _medicine_row("B", "EMEA/H/C/2", "vedotin", last_updated="01/06/2022"),
        _medicine_row("C", "EMEA/H/C/3", "vedotin", last_updated="01/06/2025"),
    ])
    _register_ema(xlsx)

    result = EMAJob().run(_base_args(tmp_path, dry_run=True, since="2022-01-01", until="2024-12-31"))

    assert result.records_discovered == 1


@responses.activate
def test_rerun_with_unchanged_content_skips_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    xlsx = _build_xlsx([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")])
    _register_ema(xlsx)

    EMAJob().run(_base_args(tmp_path))
    second = EMAJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 1
    df = _metadata_df(tmp_path)
    assert len(df) == 1
    assert (df["version"] == 1).all()


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    xlsx = _build_xlsx([
        _medicine_row("A", "EMEA/H/C/1", "vedotin"),
        _medicine_row("B", "EMEA/H/C/2", "emtansine"),
    ])
    _register_ema(xlsx)

    result = EMAJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    assert len(_metadata_df(tmp_path)) == 1


@responses.activate
def test_empty_result_set_produces_empty_manifest_without_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    xlsx = _build_xlsx([_medicine_row("Zebinix", "EMEA/H/C/000988", "eslicarbazepine acetate")])
    _register_ema(xlsx)

    result = EMAJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert len(_metadata_df(tmp_path)) == 0
