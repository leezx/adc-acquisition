import argparse

import pandas as pd
import responses

from adc_acquisition import http_utils
from jobs.company_pipeline.job import CompanyPipelineJob

REGISTRY_YAML = """
companies:
  - company_id: acme
    canonical_name: Acme Therapeutics, Inc.
    official_domain: acme.example
    pipeline_urls: ["https://acme.example/pipeline"]
    active: true
  - company_id: no_pipeline
    canonical_name: NoPipeline Inc.
    official_domain: nopipeline.example
    pipeline_urls: []
    active: true
  - company_id: inactive_co
    canonical_name: Inactive Co.
    official_domain: inactive.example
    pipeline_urls: ["https://inactive.example/pipeline"]
    active: false
"""

TWO_URL_REGISTRY_YAML = """
companies:
  - company_id: acme
    canonical_name: Acme Therapeutics, Inc.
    official_domain: acme.example
    pipeline_urls: ["https://acme.example/pipeline"]
    active: true
  - company_id: beta
    canonical_name: Beta Biopharma, Inc.
    official_domain: beta.example
    pipeline_urls: ["https://beta.example/pipeline"]
    active: true
"""

PAGE_A = b"<html><head><title>Acme Pipeline</title></head><body>ADC-101 Phase 1</body></html>"
PAGE_A_V2 = b"<html><head><title>Acme Pipeline</title></head><body>ADC-101 Phase 2</body></html>"


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None, company=None,
        output=str(tmp_path / "DATA"), registry_file=str(tmp_path / "registry.yaml"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch, registry_yaml=REGISTRY_YAML):
    (tmp_path / "registry.yaml").write_text(registry_yaml)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)
    import jobs.company_pipeline.job as job_module
    monkeypatch.setattr(job_module, "RATE_LIMIT", 1000)


def _manifest_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "company_pipeline.parquet")


def _attempts_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "company_pipeline_attempts.parquet")


@responses.activate
def test_dry_run_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")

    result = CompanyPipelineJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 1  # only acme has a pipeline_url; inactive_co and no_pipeline excluded
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "company_pipeline.parquet").exists()
    assert len(responses.calls) == 0


@responses.activate
def test_full_run_writes_manifest_and_attempts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")

    result = CompanyPipelineJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["company_id"] == "acme"
    assert df.iloc[0]["company"] == "Acme Therapeutics, Inc."
    assert df.iloc[0]["title"] == "Acme Pipeline"
    assert df.iloc[0]["url"] == "https://acme.example/pipeline"
    assert df.iloc[0]["version"] == 1

    attempts = _attempts_df(tmp_path)
    assert attempts.iloc[0]["status"] == "success"
    assert attempts.iloc[0]["query_id"].startswith("PIPELINE_ACME_")

    report_text = (tmp_path / "reports" / "acquisition" / "company_pipeline.md").read_text()
    assert "Company Pipeline Pages (Job 11)" in report_text


@responses.activate
def test_inactive_and_no_pipeline_companies_excluded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")
    # inactive_co's URL is deliberately NOT registered with responses -- if the job
    # tried to fetch it, this test would fail with a ConnectionError from `responses`.

    result = CompanyPipelineJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert result.records_downloaded == 1


@responses.activate
def test_unchanged_content_skipped_on_rerun(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")
    CompanyPipelineJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")
    result = CompanyPipelineJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    assert result.records_skipped_unchanged == 1
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["version"] == 1


@responses.activate
def test_changed_content_creates_new_version(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")
    CompanyPipelineJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A_V2, content_type="text/html")
    result = CompanyPipelineJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    versions = sorted(df["version"])
    assert versions == [1, 2]


@responses.activate
def test_failed_fetch_is_retried_on_next_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", status=500)
    responses.add(responses.GET, "https://acme.example/pipeline", status=500)
    responses.add(responses.GET, "https://acme.example/pipeline", status=500)
    responses.add(responses.GET, "https://acme.example/pipeline", status=500)
    responses.add(responses.GET, "https://acme.example/pipeline", status=500)

    result1 = CompanyPipelineJob().run(_base_args(tmp_path))
    assert result1.records_failed == 1

    responses.reset()
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")
    result2 = CompanyPipelineJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 1


@responses.activate
def test_non_retriable_failure_recorded_as_failed_not_retried_forever_silently(tmp_path, monkeypatch):
    """Simulates AbbVie's live-verified Cloudflare-403 case: a non-retriable
    HTTP status must be recorded as a normal failed attempt, not silently
    dropped, and must not crash the whole run."""
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", status=403, body="Just a moment...")

    result = CompanyPipelineJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    assert result.records_downloaded == 0
    attempts = _attempts_df(tmp_path)
    assert attempts.iloc[0]["status"] == "failed"
    assert attempts.iloc[0]["http_status"] == 403


@responses.activate
def test_limit_prioritizes_fresh_over_backlog(tmp_path, monkeypatch):
    """acme fails in run 1 (becomes backlog). Run 2 registers a brand-new
    company (beta, fresh) alongside acme (still backlog) with limit=1 --
    beta must get the slot, not acme, even though acme was registered
    first alphabetically."""
    registry_v1 = """
companies:
  - company_id: acme
    canonical_name: Acme Therapeutics, Inc.
    pipeline_urls: ["https://acme.example/pipeline"]
    active: true
"""
    _setup(tmp_path, monkeypatch, registry_yaml=registry_v1)
    for _ in range(5):
        responses.add(responses.GET, "https://acme.example/pipeline", status=500)
    CompanyPipelineJob().run(_base_args(tmp_path))  # acme fails -> backlog

    responses.reset()
    (tmp_path / "registry.yaml").write_text(TWO_URL_REGISTRY_YAML)  # now beta is registered too, never attempted
    for _ in range(5):
        responses.add(responses.GET, "https://acme.example/pipeline", status=500)
    responses.add(responses.GET, "https://beta.example/pipeline", body=b"<html><title>Beta</title></html>", content_type="text/html")

    result = CompanyPipelineJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert set(df["company_id"]) == {"beta"}  # fresh got the single slot, not acme's backlog retry


@responses.activate
def test_query_id_deterministic_and_stable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")
    CompanyPipelineJob().run(_base_args(tmp_path))

    responses.reset()
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A_V2, content_type="text/html")
    CompanyPipelineJob().run(_base_args(tmp_path))

    attempts = _attempts_df(tmp_path)
    assert attempts["query_id"].nunique() == 1  # same (company, url) pair -> same query_id across runs


@responses.activate
def test_raw_pdf_content_type_versioned_correctly(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    responses.add(responses.GET, "https://acme.example/pipeline", body=b"%PDF-fake-pipeline-chart", content_type="application/pdf")

    result = CompanyPipelineJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["raw_format"] == "pdf"
    assert df.iloc[0]["title"] is None  # no HTML title extraction attempted for PDF
    raw_path = tmp_path / "DATA" / "raw" / "company_pipeline" / "acme"
    pdf_files = list(raw_path.rglob("v1.pdf"))
    assert len(pdf_files) == 1


@responses.activate
def test_empty_registry_raises_clear_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml="companies: []")

    try:
        CompanyPipelineJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised


@responses.activate
def test_company_filter_selects_single_company(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, registry_yaml=TWO_URL_REGISTRY_YAML)
    responses.add(responses.GET, "https://acme.example/pipeline", body=PAGE_A, content_type="text/html")

    result = CompanyPipelineJob().run(_base_args(tmp_path, company="acme"))

    assert result.records_discovered == 1
    df = _manifest_df(tmp_path)
    assert set(df["company_id"]) == {"acme"}
