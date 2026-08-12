import argparse
import json

import pandas as pd
import responses

from jobs.ema.client import EMA_EPAR_DOCUMENTS_JSON_URL, EMA_MEDICINES_JSON_URL
from jobs.ema.job import EMAJob

PATTERNS_YAML = """
query_id: EMA_ADC_SUBSTANCE_PATTERN
query_version: 1
substance_patterns:
  - vedotin
  - emtansine
"""


def _medicine_row(name, product_number, active_substance, last_updated="12/08/2026"):
    return {
        "name_of_medicine": name,
        "ema_product_number": product_number,
        "medicine_status": "Authorised",
        "active_substance": active_substance,
        "therapeutic_area_mesh": "Oncology",
        "marketing_authorisation_developer_applicant_holder": "TEST HOLDER",
        "european_commission_decision_date": "01/01/2020",
        "marketing_authorisation_date": "01/02/2020",
        "withdrawal_expiry_revocation_lapse_of_marketing_authorisation_date": "",
        "last_updated_date": last_updated,
        "medicine_url": f"https://www.ema.europa.eu/en/medicines/human/EPAR/{name.lower()}",
    }


def _document_row(doc_id, product_number, doc_type, last_updated="2020-01-01T00:00:00Z", url=None):
    return {
        "id": doc_id,
        "ema_product_number": product_number,
        "type": doc_type,
        "first_published_date": last_updated,
        "last_updated_date": last_updated,
        "document_url": url or f"https://www.ema.europa.eu/en/documents/{doc_type}/{doc_id}_en.pdf",
    }


def _register_ema(medicine_rows, document_rows=None, documents=None):
    document_rows = document_rows if document_rows is not None else []
    documents = documents if documents is not None else {}

    responses.add(responses.GET, EMA_MEDICINES_JSON_URL, json={"meta": {"timestamp": "2026-08-12T00:00:00Z"}, "data": medicine_rows})
    responses.add(responses.GET, EMA_EPAR_DOCUMENTS_JSON_URL, json={"meta": {"timestamp": "2026-08-12T00:00:00Z"}, "data": document_rows})

    def _document_callback(request):
        content = documents.get(request.url)
        if content is None:
            return (404, {}, "")
        return (200, {}, content)

    responses.add_callback(responses.GET, "https://www.ema.europa.eu/en/documents/product-information/1_en.pdf", callback=_document_callback)
    for url in documents:
        responses.add_callback(responses.GET, url, callback=_document_callback)


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
    _register_ema([
        _medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin"),
        _medicine_row("Zebinix", "EMEA/H/C/000988", "eslicarbazepine acetate"),  # not an ADC
    ])

    result = EMAJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 1
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "ema.parquet").exists()


@responses.activate
def test_full_run_writes_medicine_document_and_bulk_snapshots(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    doc_url = "https://www.ema.europa.eu/en/documents/product-information/1_en.pdf"
    _register_ema(
        [_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")],
        document_rows=[_document_row("1", "EMEA/H/C/002455", "product-information")],
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
    assert docs_df.iloc[0]["source_record_id"] == "EMEA/H/C/002455:1"
    assert docs_df.iloc[0]["parent_record_id"] == "EMEA/H/C/002455"
    assert docs_df.iloc[0]["doc_type"] == "product-information"

    bulk_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_bulk.parquet")
    assert set(bulk_df["source_record_id"]) == {"medicines_bulk", "documents_bulk"}

    report_text = (tmp_path / "reports" / "acquisition" / "ema.md").read_text()
    assert "EMA (Job 07)" in report_text


@responses.activate
def test_document_discovery_is_independent_of_medicine_limit_scope(tmp_path, monkeypatch):
    """Blocker fix: a document must be discovered/downloaded for a
    medicine even if that medicine itself was excluded from this run's
    materialization scope by --limit."""
    _setup(tmp_path, monkeypatch)
    doc_url = "https://www.ema.europa.eu/en/documents/product-information/1_en.pdf"
    _register_ema(
        [
            _medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin"),
            _medicine_row("Kadcyla", "EMEA/H/C/002389", "trastuzumab emtansine"),
        ],
        document_rows=[_document_row("1", "EMEA/H/C/002389", "product-information")],
        documents={doc_url: b"%PDF product info"},
    )

    result = EMAJob().run(_base_args(tmp_path, limit=1))  # only 1 of 2 medicines gets materialized

    assert result.records_downloaded == 1
    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents.parquet")
    assert len(docs_df) == 1  # still discovered even though its medicine was limited out
    assert docs_df.iloc[0]["parent_record_id"] == "EMEA/H/C/002389"


@responses.activate
def test_new_document_discovered_on_resume_even_when_medicine_is_unchanged(tmp_path, monkeypatch):
    """Blocker fix: document discovery must not be gated by the medicine's
    own --resume fresh/backlog scope."""
    _setup(tmp_path, monkeypatch)
    med_row = _medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin", last_updated="01/01/2019")
    _register_ema([med_row], document_rows=[])
    EMAJob().run(_base_args(tmp_path, until="2020-01-01"))
    assert len(pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents.parquet")) == 0

    responses.reset()
    doc_url = "https://www.ema.europa.eu/en/documents/product-information/1_en.pdf"
    # Medicine itself is unchanged (same last_updated, before the cursor) and
    # would NOT be in fresh/backlog scope on --resume; a new document appears.
    _register_ema(
        [med_row],
        document_rows=[_document_row("1", "EMEA/H/C/002455", "product-information")],
        documents={doc_url: b"%PDF new doc"},
    )
    result = EMAJob().run(_base_args(tmp_path, resume=True))

    assert result.records_discovered == 0  # medicine correctly outside this run's scope
    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents.parquet")
    assert len(docs_df) == 1  # document still discovered and downloaded


@responses.activate
def test_document_404_is_a_failed_attempt_not_a_crash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_ema(
        [_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")],
        document_rows=[_document_row("1", "EMEA/H/C/002455", "product-information")],
        documents={},  # doc always 404s
    )

    result = EMAJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1  # the medicine itself always succeeds
    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents.parquet")
    assert len(docs_df) == 0
    doc_attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents_attempts.parquet")
    assert doc_attempts.iloc[0]["status"] == "failed"


@responses.activate
def test_query_version_from_registry_propagates_not_hardcoded(tmp_path, monkeypatch):
    (tmp_path / "patterns.yaml").write_text(
        "query_id: EMA_ADC_SUBSTANCE_PATTERN\nquery_version: 7\nsubstance_patterns:\n  - vedotin\n"
    )
    monkeypatch.chdir(tmp_path)
    import jobs.ema.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)
    _register_ema([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")])

    EMAJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_discovery.parquet")
    assert discovery_df.iloc[0]["query_version"] == 7


@responses.activate
def test_resume_fresh_medicines_not_starved_by_backlog_retries(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    old_rows = [_medicine_row(f"Old{i}", f"EMEA/H/C/{i:06d}", "brentuximab vedotin", last_updated="01/01/2010") for i in range(25)]
    new_row = _medicine_row("New1", "EMEA/H/C/999999", "brentuximab vedotin", last_updated="01/06/2025")
    _register_ema(old_rows)

    result1 = EMAJob().run(_base_args(tmp_path, until="2010-12-31", limit=30))
    assert result1.records_downloaded == 25

    responses.reset()
    _register_ema(old_rows + [new_row])
    EMAJob().run(_base_args(tmp_path, resume=True, limit=20))

    df = _metadata_df(tmp_path)
    assert "EMEA/H/C/999999" in set(df["source_record_id"])  # must not be starved out


@responses.activate
def test_since_until_filters_by_last_updated_date(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_ema([
        _medicine_row("A", "EMEA/H/C/1", "vedotin", last_updated="01/06/2019"),
        _medicine_row("B", "EMEA/H/C/2", "vedotin", last_updated="01/06/2022"),
        _medicine_row("C", "EMEA/H/C/3", "vedotin", last_updated="01/06/2025"),
    ])

    result = EMAJob().run(_base_args(tmp_path, dry_run=True, since="2022-01-01", until="2024-12-31"))

    assert result.records_discovered == 1


@responses.activate
def test_rerun_with_unchanged_content_skips_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_ema([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")])

    EMAJob().run(_base_args(tmp_path))
    second = EMAJob().run(_base_args(tmp_path))

    assert second.records_downloaded == 0
    assert second.records_skipped_unchanged == 1
    df = _metadata_df(tmp_path)
    assert len(df) == 1
    assert (df["version"] == 1).all()


@responses.activate
def test_bulk_snapshot_versions_only_when_content_changes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    rows = [_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")]
    _register_ema(rows)
    EMAJob().run(_base_args(tmp_path))

    responses.reset()
    _register_ema(rows)  # identical content
    EMAJob().run(_base_args(tmp_path))

    bulk_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_bulk.parquet")
    assert (bulk_df["version"] == 1).all()  # unchanged content never got a v2


@responses.activate
def test_unchanged_document_metadata_skips_refetch_without_http_request(tmp_path, monkeypatch):
    """Blocker fix: incremental document fetch must be feed-metadata-driven,
    not hash-after-download — an unchanged, previously-successful document
    must not trigger an HTTP request at all, while a previously-failed one
    must still be retried even though its metadata also didn't change."""
    _setup(tmp_path, monkeypatch)
    ok_url = "https://www.ema.europa.eu/en/documents/product-information/1_en.pdf"
    fail_url = "https://www.ema.europa.eu/en/documents/product-information/2_en.pdf"
    doc_rows = [
        _document_row("1", "EMEA/H/C/002455", "product-information", url=ok_url),
        _document_row("2", "EMEA/H/C/002455", "product-information", url=fail_url),
    ]
    _register_ema(
        [_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")],
        document_rows=doc_rows,
        documents={ok_url: b"%PDF ok"},  # fail_url has no registered content -> 404
    )

    EMAJob().run(_base_args(tmp_path))
    doc_attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents_attempts.parquet")
    assert set(doc_attempts["status"]) == {"success", "failed"}

    responses.calls.reset()
    EMAJob().run(_base_args(tmp_path))  # identical bulk feed, identical metadata

    doc_urls_hit = {c.request.url for c in responses.calls if c.request.url in (ok_url, fail_url)}
    assert doc_urls_hit == {fail_url}  # only the unresolved failure is re-requested


@responses.activate
def test_document_last_updated_change_triggers_refetch_and_new_version(tmp_path, monkeypatch):
    """Blocker fix: a change in the feed's own last_updated for a document
    must still trigger a refetch even though the document was previously
    successful, and a genuinely changed body must create a new version."""
    _setup(tmp_path, monkeypatch)
    doc_url = "https://www.ema.europa.eu/en/documents/product-information/1_en.pdf"
    _register_ema(
        [_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")],
        document_rows=[_document_row("1", "EMEA/H/C/002455", "product-information", last_updated="2020-01-01T00:00:00Z", url=doc_url)],
        documents={doc_url: b"%PDF v1"},
    )
    EMAJob().run(_base_args(tmp_path))

    responses.reset()
    _register_ema(
        [_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")],
        document_rows=[_document_row("1", "EMEA/H/C/002455", "product-information", last_updated="2021-06-01T00:00:00Z", url=doc_url)],
        documents={doc_url: b"%PDF v2 changed"},
    )
    EMAJob().run(_base_args(tmp_path))

    docs_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_documents.parquet")
    versions = sorted(docs_df.loc[docs_df["source_record_id"] == "EMEA/H/C/002455:1", "version"])
    assert versions == [1, 2]


@responses.activate
def test_bulk_snapshot_persisted_before_parser_runs(tmp_path, monkeypatch):
    """Blocker fix: raw bulk bytes must be durable (raw file + ema_bulk.parquet)
    BEFORE they're handed to a parser, so a parser crash (e.g. EMA changes a
    feed's schema) never erases the evidence that caused the crash."""
    _setup(tmp_path, monkeypatch)
    _register_ema([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")])

    import jobs.ema.job as job_module

    def _boom(_bytes):
        raise RuntimeError("EMA changed the medicines feed schema")

    monkeypatch.setattr(job_module, "parse_medicines_json", _boom)

    try:
        EMAJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    bulk_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "ema_bulk.parquet")
    assert set(bulk_df["source_record_id"]) == {"medicines_bulk", "documents_bulk"}
    raw_dir = tmp_path / "DATA" / "raw" / "ema" / "bulk"
    assert (raw_dir / "medicines_bulk" / "v1.json").exists()
    assert (raw_dir / "documents_bulk" / "v1.json").exists()


@responses.activate
def test_limit_caps_records_processed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_ema([
        _medicine_row("A", "EMEA/H/C/1", "vedotin"),
        _medicine_row("B", "EMEA/H/C/2", "emtansine"),
    ])

    result = EMAJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    assert len(_metadata_df(tmp_path)) == 1


@responses.activate
def test_empty_result_set_produces_empty_manifest_without_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_ema([_medicine_row("Zebinix", "EMEA/H/C/000988", "eslicarbazepine acetate")])

    result = EMAJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
    assert len(_metadata_df(tmp_path)) == 0
