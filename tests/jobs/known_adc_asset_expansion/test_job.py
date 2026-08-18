import argparse

import pytest
import responses
import yaml

import jobs.known_adc_asset_expansion.job as job_module
from adc_acquisition import http_utils
from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.job_base import JobRunResult
from jobs.known_adc_asset_expansion.job import KnownADCAssetExpansionJob, _invoke_isolated
from jobs.known_adc_asset_expansion.query_templates import _query_id

PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPS_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
OPS_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"
CTGOV_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
USPTO_SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"

MINIMAL_ASSETS_YAML = """
assets:
  - asset_id: integration_test_adc
    canonical_name: Integration Test ADC
    aliases: []
    dev_codes: []
    target: HER2
    company: Test Pharma
    active: true
"""

ASSETS_YAML = """
assets:
  - asset_id: test_adc_one
    canonical_name: Test ADC One
    aliases: [TestBrand]
    dev_codes: [TAD-001]
    target: HER2
    company: Test Pharma
    active: true
  - asset_id: test_adc_two
    canonical_name: Test ADC Two
    aliases: []
    dev_codes: []
    target: CD30
    company: Test Pharma
    active: false
"""


def _write_assets_file(tmp_path):
    path = tmp_path / "known_adc_assets.yaml"
    path.write_text(ASSETS_YAML, encoding="utf-8")
    return path


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"),
        assets_file=str(_write_assets_file(tmp_path)),
        generated_queries_dir=None,
        sources=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_fake_job_class(name, calls, records_discovered=2, records_downloaded=1):
    class _FakeJob:
        job_name = name

        def run(self, args):
            calls.setdefault(name, []).append(args)
            result = JobRunResult(job_name=name, dry_run=bool(args.dry_run))
            result.queries_run = 1
            result.records_discovered = records_discovered
            result.records_downloaded = records_downloaded
            result.records_skipped_unchanged = 0
            result.records_failed = 0
            return result

    _FakeJob.name = name
    return _FakeJob


def _install_fake_sources(monkeypatch, records_discovered=2, records_downloaded=1):
    calls: dict[str, list] = {}
    monkeypatch.setattr(job_module, "QUERY_DRIVEN_SOURCES", [
        ("pubmed", _make_fake_job_class("pubmed", calls, records_discovered, records_downloaded), job_module.pubmed_queries),
        ("europe_pmc", _make_fake_job_class("europe_pmc", calls, records_discovered, records_downloaded), job_module.europe_pmc_queries),
        ("wipo", _make_fake_job_class("wipo", calls, records_discovered, records_downloaded), job_module.wipo_queries),
        ("epo", _make_fake_job_class("epo", calls, records_discovered, records_downloaded), job_module.epo_queries),
        ("uspto", _make_fake_job_class("uspto", calls, records_discovered, records_downloaded), job_module.uspto_queries),
    ])
    monkeypatch.setattr(job_module, "ALLOWED_SOURCES", {"pubmed", "europe_pmc", "wipo", "epo", "uspto", "clinicaltrials"})
    monkeypatch.setattr(job_module, "ClinicalTrialsJob", _make_fake_job_class("clinicaltrials", calls, records_discovered, records_downloaded))
    return calls


def test_generates_correct_number_of_queries_per_source(tmp_path, monkeypatch):
    """test_adc_one has 3 identifiers (canonical + alias + dev code) ->
    3 bare + 6 suffix = 9 queries for pubmed/europe_pmc/uspto, 3 for
    wipo/epo (bare identifiers only). test_adc_two is inactive and must
    be excluded entirely."""
    calls = _install_fake_sources(monkeypatch)
    KnownADCAssetExpansionJob().run(_base_args(tmp_path))

    assert calls["pubmed"][0].queries_file.endswith("pubmed_asset_expansion_queries.yaml")
    with open(calls["pubmed"][0].queries_file) as f:
        pubmed_queries = yaml.safe_load(f)["queries"]
    assert len(pubmed_queries) == 9
    assert all("test_adc_two" not in q["query_id"].lower() for q in pubmed_queries)

    with open(calls["wipo"][0].queries_file) as f:
        wipo_queries = yaml.safe_load(f)["queries"]
    assert len(wipo_queries) == 3
    assert all(q["query_text"].startswith("pn=WO") for q in wipo_queries)

    with open(calls["epo"][0].queries_file) as f:
        epo_queries = yaml.safe_load(f)["queries"]
    assert all(q["query_text"].startswith("pn=EP") for q in epo_queries)

    with open(calls["uspto"][0].queries_file) as f:
        uspto_queries = yaml.safe_load(f)["queries"]
    assert len(uspto_queries) == 9  # gets suffix templates too, unlike wipo/epo
    assert any(q["query_text"].endswith("AND ic50") for q in uspto_queries)


def test_clinicaltrials_called_once_per_identifier(tmp_path, monkeypatch):
    calls = _install_fake_sources(monkeypatch)
    KnownADCAssetExpansionJob().run(_base_args(tmp_path))

    assert len(calls["clinicaltrials"]) == 3  # canonical name + 1 alias + 1 dev code, for the one active asset
    interventions = {c.intervention for c in calls["clinicaltrials"]}
    assert interventions == {"Test ADC One", "TestBrand", "TAD-001"}


def test_aggregates_results_across_sources(tmp_path, monkeypatch):
    _install_fake_sources(monkeypatch, records_discovered=2, records_downloaded=1)
    result = KnownADCAssetExpansionJob().run(_base_args(tmp_path))

    # 5 query-driven sources (1 call each) + clinicaltrials (3 calls, one per identifier)
    assert result.records_discovered == 5 * 2 + 3 * 2
    assert result.records_downloaded == 5 * 1 + 3 * 1
    assert any("pubmed:" in n for n in result.notes)
    assert any("uspto:" in n for n in result.notes)
    assert any("clinicaltrials:" in n for n in result.notes)


def test_sources_filter_limits_which_jobs_run(tmp_path, monkeypatch):
    calls = _install_fake_sources(monkeypatch)
    KnownADCAssetExpansionJob().run(_base_args(tmp_path, sources="pubmed,clinicaltrials"))

    assert "pubmed" in calls
    assert "clinicaltrials" in calls
    assert "europe_pmc" not in calls
    assert "wipo" not in calls
    assert "epo" not in calls
    assert "uspto" not in calls


def test_sources_filter_tolerates_whitespace(tmp_path, monkeypatch):
    calls = _install_fake_sources(monkeypatch)
    KnownADCAssetExpansionJob().run(_base_args(tmp_path, sources=" pubmed , uspto "))

    assert "pubmed" in calls
    assert "uspto" in calls
    assert "europe_pmc" not in calls


def test_unknown_sources_value_raises_not_silently_skips(tmp_path, monkeypatch):
    """Round-1 fix: a typo/stray value in --sources must raise immediately,
    not silently run a smaller subset while still reporting overall
    success."""
    _install_fake_sources(monkeypatch)

    with pytest.raises(ValueError, match="pubmedd"):
        KnownADCAssetExpansionJob().run(_base_args(tmp_path, sources="pubmedd,uspto"))


def test_since_until_passed_through_to_subjobs(tmp_path, monkeypatch):
    calls = _install_fake_sources(monkeypatch)
    KnownADCAssetExpansionJob().run(_base_args(tmp_path, since="2020-01-01", until="2025-01-01"))

    for name in ("pubmed", "wipo"):
        assert calls[name][0].since == "2020-01-01"
        assert calls[name][0].until == "2025-01-01"
    for call in calls["clinicaltrials"]:
        assert call.since == "2020-01-01"
        assert call.until == "2025-01-01"


def test_resume_is_noop_with_note(tmp_path, monkeypatch):
    _install_fake_sources(monkeypatch)
    result = KnownADCAssetExpansionJob().run(_base_args(tmp_path, resume=True))

    assert any("--resume is a no-op" in n for n in result.notes)


def test_subjobs_never_receive_resume_true(tmp_path, monkeypatch):
    calls = _install_fake_sources(monkeypatch)
    KnownADCAssetExpansionJob().run(_base_args(tmp_path, resume=True))

    for name, invocations in calls.items():
        for call in invocations:
            assert call.resume is False


def test_dry_run_does_not_write_report(tmp_path, monkeypatch):
    _install_fake_sources(monkeypatch)
    result = KnownADCAssetExpansionJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert not (tmp_path / "reports" / "acquisition" / "known_adc_asset_expansion.md").exists()


def test_full_run_writes_report(tmp_path, monkeypatch):
    _install_fake_sources(monkeypatch)
    KnownADCAssetExpansionJob().run(_base_args(tmp_path))

    report_text = (tmp_path / "reports" / "acquisition" / "known_adc_asset_expansion.md").read_text()
    assert "Known-ADC Asset Expansion (Job 15)" in report_text
    assert "Test ADC One" in report_text
    assert "Test ADC Two" not in report_text  # inactive, excluded


def test_no_active_assets_raises_clear_error(tmp_path, monkeypatch):
    _install_fake_sources(monkeypatch)
    inactive_only = tmp_path / "inactive_only.yaml"
    inactive_only.write_text("assets:\n  - asset_id: x\n    canonical_name: X\n    active: false\n", encoding="utf-8")

    with pytest.raises(RuntimeError):
        KnownADCAssetExpansionJob().run(_base_args(tmp_path, assets_file=str(inactive_only)))


@responses.activate
def test_real_subjobs_dry_run_end_to_end(tmp_path, monkeypatch):
    """Integration regression test: drives the REAL Jobs 01/02/03/08/10
    (not fakes) through this job's orchestration layer with only HTTP
    mocked. Catches exactly the bug class a live run surfaced (a
    hand-built argparse.Namespace missing an attribute a real sub-job
    accesses, e.g. WIPO/EPO's --refresh) that fakes alone cannot catch,
    since a fake job's run() never touches those attributes."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPS_CONSUMER_KEY", "test-key")
    monkeypatch.setenv("OPS_CONSUMER_SECRET", "test-secret")
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key")
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)

    assets_path = tmp_path / "assets.yaml"
    assets_path.write_text(MINIMAL_ASSETS_YAML, encoding="utf-8")

    responses.add(responses.GET, PUBMED_ESEARCH_URL, json={"esearchresult": {"count": "0", "idlist": []}})
    responses.add(responses.GET, EUROPEPMC_SEARCH_URL, json={"hitCount": 0, "resultList": {"result": []}})
    responses.add(responses.POST, OPS_AUTH_URL, json={"access_token": "tok", "expires_in": 1199})
    responses.add(
        responses.GET, OPS_SEARCH_URL, status=404,
        body='<fault xmlns="http://ops.epo.org"><code>SERVER.EntityNotFound</code></fault>',
    )
    responses.add(responses.GET, USPTO_SEARCH_URL, json={"patentFileWrapperDataBag": [], "count": 0})
    responses.add(responses.GET, CTGOV_STUDIES_URL, json={"studies": [], "totalCount": 0})

    args = argparse.Namespace(
        dry_run=True, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), assets_file=str(assets_path),
        generated_queries_dir=None, sources=None,
    )
    result = KnownADCAssetExpansionJob().run(args)

    assert result.dry_run is True
    assert result.records_discovered == 0
    assert result.records_failed == 0


def _write_report(output_dir, job_name, text):
    report_path = output_dir.parent / "reports" / "acquisition" / f"{job_name}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return report_path


def _read_report(output_dir, job_name):
    return (output_dir.parent / "reports" / "acquisition" / f"{job_name}.md").read_text(encoding="utf-8")


def test_cursor_and_report_preserved_across_successful_subjob_call(tmp_path):
    """Direct regression test for the self-caught isolation bug: a
    sub-job that (like every real Jobs 01/02/03/08/09/10) writes
    checkpoint["last_success_max_date"] AND overwrites its own report.md
    unconditionally must NOT be allowed to permanently move that job's
    OWN resume cursor or clobber its OWN broad report just because this
    job called it with a different query set."""
    output_dir = tmp_path / "DATA"
    checkpoint_store = CheckpointStore("fake_source", output_dir)
    checkpoint = checkpoint_store.load()
    checkpoint["last_success_max_date"] = "2020-01-01"
    checkpoint_store.save(checkpoint)
    _write_report(output_dir, "fake_source", "# Broad report\noriginal content")

    class _FakeJobThatMutatesSharedState:
        name = "fake_source"

        def run(self, args):
            store = CheckpointStore(self.name, output_dir)
            cp = store.load()
            cp["last_run_at"] = "SIMULATED_RUN"
            cp["last_success_max_date"] = "2099-01-01"  # the hazard this test guards against
            store.save(cp)
            _write_report(output_dir, self.name, "# Asset-expansion-only report\noverwritten content")
            return JobRunResult(job_name=self.name, dry_run=False, records_discovered=1)

    args = argparse.Namespace(dry_run=False, limit=None, resume=False, since=None, until=None, output=str(output_dir))
    result = _invoke_isolated(_FakeJobThatMutatesSharedState, args, output_dir)

    assert result.records_discovered == 1
    final_checkpoint = checkpoint_store.load()
    assert final_checkpoint["last_success_max_date"] == "2020-01-01"  # restored, not overwritten
    assert final_checkpoint["last_run_at"] == "SIMULATED_RUN"  # informational field, fine to update
    assert _read_report(output_dir, "fake_source") == "# Broad report\noriginal content"  # restored, not overwritten


def test_cursor_and_report_preserved_even_if_subjob_raises(tmp_path):
    """P1 fix: restoration must happen in a `finally`, not just code that
    runs after a successful call -- the exact scenario this isolation
    exists for (a sub-job crash mid-run) must not leave the broad pass's
    cursor/report corrupted. The exception must still propagate."""
    output_dir = tmp_path / "DATA"
    checkpoint_store = CheckpointStore("fake_source", output_dir)
    checkpoint = checkpoint_store.load()
    checkpoint["last_success_max_date"] = "2020-01-01"
    checkpoint_store.save(checkpoint)
    _write_report(output_dir, "fake_source", "# Broad report\noriginal content")

    class _FakeJobThatMutatesThenRaises:
        name = "fake_source"

        def run(self, args):
            store = CheckpointStore(self.name, output_dir)
            cp = store.load()
            cp["last_success_max_date"] = "2099-01-01"
            store.save(cp)
            _write_report(output_dir, self.name, "# Corrupted mid-crash report")
            raise RuntimeError("simulated sub-job crash")

    args = argparse.Namespace(dry_run=False, limit=None, resume=False, since=None, until=None, output=str(output_dir))
    with pytest.raises(RuntimeError, match="simulated sub-job crash"):
        _invoke_isolated(_FakeJobThatMutatesThenRaises, args, output_dir)

    final_checkpoint = checkpoint_store.load()
    assert final_checkpoint["last_success_max_date"] == "2020-01-01"  # still restored despite the exception
    assert _read_report(output_dir, "fake_source") == "# Broad report\noriginal content"  # still restored


def test_report_removed_if_it_did_not_exist_before(tmp_path):
    """A sub-job invoked for the FIRST time ever (no prior report.md) must
    not leave behind an asset-expansion-only report masquerading as that
    job's broad report."""
    output_dir = tmp_path / "DATA"

    class _FakeJobThatWritesAReport:
        name = "brand_new_source"

        def run(self, args):
            _write_report(output_dir, self.name, "# Asset-expansion-only report")
            return JobRunResult(job_name=self.name, dry_run=False, records_discovered=1)

    args = argparse.Namespace(dry_run=False, limit=None, resume=False, since=None, until=None, output=str(output_dir))
    _invoke_isolated(_FakeJobThatWritesAReport, args, output_dir)

    report_path = output_dir.parent / "reports" / "acquisition" / "brand_new_source.md"
    assert not report_path.exists()


def test_cursor_key_absent_before_stays_absent_after(tmp_path):
    """Mirrors the report-absence case for the cursor field: if a sub-job
    checkpoint file never had last_success_max_date at all (e.g. a legacy
    checkpoint predating that field), it must not gain one just because
    the sub-job happened to set it during this call. CheckpointStore.load()
    normally defaults a MISSING checkpoint file to a dict that already
    has the key set to None -- to exercise the genuinely-absent-key path
    this test writes the checkpoint file directly, bypassing that
    default."""
    output_dir = tmp_path / "DATA"
    checkpoint_path = output_dir / "checkpoints" / "fake_source_no_cursor.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text('{"job": "fake_source_no_cursor", "records": {}}', encoding="utf-8")

    class _FakeJobWithNoPriorCursor:
        name = "fake_source_no_cursor"

        def run(self, args):
            store = CheckpointStore(self.name, output_dir)
            cp = store.load()
            cp["last_success_max_date"] = "2099-01-01"
            store.save(cp)
            return JobRunResult(job_name=self.name, dry_run=False, records_discovered=1)

    args = argparse.Namespace(dry_run=False, limit=None, resume=False, since=None, until=None, output=str(output_dir))
    _invoke_isolated(_FakeJobWithNoPriorCursor, args, output_dir)

    final_checkpoint = CheckpointStore("fake_source_no_cursor", output_dir).load()
    assert "last_success_max_date" not in final_checkpoint


def test_query_id_changes_when_canonical_name_changes():
    """P1/P2 fix: since Prompt.md's own asset input is explicitly
    'canonical/temporary ADC name', a name can legitimately be
    corrected/finalized later. The suffix query_id must change when the
    underlying query_text changes, not stay fixed forever."""
    id_v1 = _query_id("PUBMED_ASSETEXP", "x", "IC50", '"Temporary-123"[tiab] AND ic50[tiab]')
    id_v2 = _query_id("PUBMED_ASSETEXP", "x", "IC50", '"Finalumab vedotin"[tiab] AND ic50[tiab]')
    assert id_v1 != id_v2


def test_query_id_stable_for_unchanged_query_text():
    id_a = _query_id("PUBMED_ASSETEXP", "x", "IC50", '"Same Name"[tiab] AND ic50[tiab]')
    id_b = _query_id("PUBMED_ASSETEXP", "x", "IC50", '"Same Name"[tiab] AND ic50[tiab]')
    assert id_a == id_b


def test_query_id_does_not_collide_when_slug_would():
    """Two different identifiers that _slug() would normalize to the same
    string must still get distinct query_ids, since the hash is derived
    from the actual query_text, not the slug alone."""
    id_a = _query_id("PUBMED_ASSETEXP", "x", "T_DXD", '"T-DXd"[tiab]')
    id_b = _query_id("PUBMED_ASSETEXP", "x", "T_DXD", '"T DXd"[tiab]')
    assert id_a != id_b
