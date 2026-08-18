import argparse

import pandas as pd
import responses

from adc_acquisition import http_utils
from adc_acquisition.manifest import new_manifest_row, write_manifest
from jobs.patent_bioactivity_corpus.job import PatentBioactivityCorpusJob, _docdb_id

EPO_EXTRA_FIELDS = [
    "publication_number", "family_id", "application_number", "filing_date",
    "priority_date", "applicants", "inventors", "ipc_classes", "cpc_classes",
]

OPS_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
OPS_BASE = "https://ops.epo.org/3.2/rest-services"


def _epo_row(publication_number, application_number="APP123", pub_date="2026-01-01", version=1):
    return new_manifest_row(
        extra_fields=EPO_EXTRA_FIELDS,
        source="epo",
        source_record_id=publication_number,
        source_record_type="epo_publication",
        title=f"Title for {publication_number}",
        url=None,
        publication_or_release_date=pub_date,
        retrieved_at="2026-01-01T00:00:00+00:00",
        query_id="EPO_TEST_QUERY",
        query_text="pn=EP",
        raw_file_path="/dev/null",
        raw_format="xml",
        content_hash="deadbeef",
        download_status="success",
        http_status=200,
        license_or_access_note="test",
        parent_record_id=None,
        version=version,
        notes=None,
        publication_number=publication_number,
        family_id="FAM1",
        application_number=application_number,
        filing_date="2025-01-01",
        priority_date="2025-01-01",
        applicants=[],
        inventors=[],
        ipc_classes=[],
        cpc_classes=[],
    )


def _write_epo_manifest(path, rows):
    write_manifest(rows, path, extra_fields=EPO_EXTRA_FIELDS)


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None, refresh=False,
        output=str(tmp_path / "DATA"), epo_manifest=str(tmp_path / "DATA" / "manifests" / "epo.parquet"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch, epo_rows):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPS_CONSUMER_KEY", "test-key")
    monkeypatch.setenv("OPS_CONSUMER_SECRET", "test-secret")
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)
    import jobs.patent_bioactivity_corpus.job as job_module
    from adc_acquisition import ops_client
    monkeypatch.setattr(ops_client, "SEARCH_RATE_LIMIT", 1000)
    monkeypatch.setattr(ops_client, "BIBLIO_RATE_LIMIT", 1000)
    monkeypatch.setattr(job_module, "SEARCH_RATE_LIMIT", 1000)
    monkeypatch.setattr(job_module, "BIBLIO_RATE_LIMIT", 1000)
    _write_epo_manifest(tmp_path / "DATA" / "manifests" / "epo.parquet", epo_rows)


def _mock_auth():
    responses.add(
        responses.POST, OPS_AUTH_URL,
        json={"access_token": "tok", "expires_in": 1199}, status=200,
    )


def _mock_artifact(docdb_id, artifact_type, body=b"<xml>content</xml>", status=200):
    responses.add(
        responses.GET, f"{OPS_BASE}/published-data/publication/docdb/{docdb_id}/{artifact_type}",
        body=body, status=status, content_type="application/xml",
    )


def _manifest_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "patent_bioactivity_corpus.parquet")


def _attempts_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "patent_bioactivity_corpus_attempts.parquet")


def test_docdb_id_reconstruction():
    assert _docdb_id("EP4789684A1") == "EP.4789684.A1"
    assert _docdb_id("EP0222360A2") == "EP.0222360.A2"
    assert _docdb_id("not-a-valid-shape") is None


@responses.activate
def test_dry_run_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])

    result = PatentBioactivityCorpusJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.queries_run == 1
    assert result.records_discovered == 2  # description + claims
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "patent_bioactivity_corpus.parquet").exists()
    assert len(responses.calls) == 0


@responses.activate
def test_full_run_writes_manifest_and_attempts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1", application_number="APP999")])
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", body=b"<xml>description body</xml>")
    _mock_artifact("EP.1000000.A1", "claims", body=b"<xml>claims body</xml>")

    result = PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 2
    df = _manifest_df(tmp_path)
    assert set(df["artifact_type"]) == {"description", "claims"}
    assert set(df["publication_number"]) == {"EP1000000A1"}
    assert set(df["application_number"]) == {"APP999"}
    assert set(df["parent_record_id"]) == {"EP1000000A1"}
    assert set(df["version"]) == {1}

    attempts = _attempts_df(tmp_path)
    assert set(attempts["status"]) == {"success"}

    report_text = (tmp_path / "reports" / "acquisition" / "patent_bioactivity_corpus.md").read_text()
    assert "Patent Bioactivity Evidence Corpus (Job 13)" in report_text


@responses.activate
def test_unchanged_content_skipped_on_rerun(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description")
    _mock_artifact("EP.1000000.A1", "claims")
    PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    responses.reset()
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description")
    _mock_artifact("EP.1000000.A1", "claims")
    result = PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    assert result.records_skipped_unchanged == 2
    df = _manifest_df(tmp_path)
    assert len(df) == 2
    assert set(df["version"]) == {1}


@responses.activate
def test_ordinary_run_skips_without_request_and_does_not_detect_changes(tmp_path, monkeypatch):
    """Skip-by-default (same design as Job 10/EPO): once an artifact is
    successfully materialized, an ORDINARY run (no --refresh) skips it
    with NO OPS request at all -- it does not even check whether the
    content changed. Only --refresh re-verifies (see
    test_refresh_reverifies_already_successful)."""
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", body=b"<xml>v1 description</xml>")
    _mock_artifact("EP.1000000.A1", "claims", body=b"<xml>v1 claims</xml>")
    PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    responses.reset()
    _mock_auth()
    # Deliberately NOT registering description/claims fetch mocks -- if
    # the ordinary rerun tried to fetch them, this test would fail with a
    # connection error, proving the skip-by-default path made no request.
    result = PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    assert result.records_skipped_unchanged == 2
    df = _manifest_df(tmp_path)
    assert set(df["version"]) == {1}


@responses.activate
def test_not_available_is_retried_not_treated_as_permanent(tmp_path, monkeypatch):
    """A 404 (OPS confirms no full text for this WO-family-only-style
    gap or an old undigitized publication) must be recorded as
    `not_available`, distinct from `failed`, and still retried on the
    very next ordinary run -- not silently dropped, not assumed
    permanent (see module docstring's SEC-round-3-derived conservatism)."""
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", status=404, body=b"")
    _mock_artifact("EP.1000000.A1", "claims", status=404, body=b"")
    result1 = PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result1.records_downloaded == 0
    assert result1.records_failed == 0  # not_available is not counted as a failure
    attempts1 = _attempts_df(tmp_path)
    assert set(attempts1["status"]) == {"not_available"}

    # Next ordinary run (no --refresh) retries it since not_available is
    # an UNRESOLVED status, not a terminal one.
    responses.reset()
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", status=404, body=b"")
    _mock_artifact("EP.1000000.A1", "claims", body=b"<xml>claims now available</xml>")
    result2 = PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 1  # claims recovered
    df = _manifest_df(tmp_path)
    assert set(df["artifact_type"]) == {"claims"}


@responses.activate
def test_failed_fetch_is_retried_on_next_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])
    _mock_auth()
    for _ in range(5):
        _mock_artifact("EP.1000000.A1", "description", status=500, body=b"")
    _mock_artifact("EP.1000000.A1", "claims")
    result1 = PatentBioactivityCorpusJob().run(_base_args(tmp_path))
    assert result1.records_failed == 1
    assert result1.records_downloaded == 1

    responses.reset()
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", body=b"<xml>description recovered</xml>")
    result2 = PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert set(df["artifact_type"]) == {"description", "claims"}


@responses.activate
def test_stale_ledger_recovers_without_bumping_version(tmp_path, monkeypatch):
    """Mirrors Job 10 (EPO)'s round-1 regression test: reproduces a crash
    between checkpoint_store.save() (durable immediately after the raw
    write) and the end-of-run manifest/attempts flush (batched once,
    after the whole loop) -- the checkpoint durably remembers v1/hash A,
    but the manifest/attempts ledger never got a row for it. The next
    run, fetching the SAME content, must recover the missing row --
    NOT bump the version, NOT re-fetch a genuinely new v2."""
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", body=b"<xml>v1</xml>")
    _mock_artifact("EP.1000000.A1", "claims", body=b"<xml>v1 claims</xml>")
    PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    # Simulate the crash: the checkpoint (already saved durably per-item
    # during the loop) is left untouched, but the manifest/attempts
    # ledger -- only flushed once, after the entire loop -- never made it
    # to disk.
    (tmp_path / "DATA" / "manifests" / "patent_bioactivity_corpus.parquet").unlink()
    (tmp_path / "DATA" / "manifests" / "patent_bioactivity_corpus_attempts.parquet").unlink()

    responses.reset()
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", body=b"<xml>v1</xml>")
    _mock_artifact("EP.1000000.A1", "claims", body=b"<xml>v1 claims</xml>")
    result = PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 2
    assert result.records_skipped_unchanged == 0
    df = _manifest_df(tmp_path)
    desc_versions = sorted(df[df["artifact_type"] == "description"]["version"])
    claims_versions = sorted(df[df["artifact_type"] == "claims"]["version"])
    assert desc_versions == [1]  # NOT [2] -- recovery must not bump the version
    assert claims_versions == [1]


@responses.activate
def test_refresh_reverifies_already_successful(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", body=b"<xml>v1</xml>")
    _mock_artifact("EP.1000000.A1", "claims", body=b"<xml>v1 claims</xml>")
    PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    responses.reset()
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description", body=b"<xml>v2 corrected</xml>")
    _mock_artifact("EP.1000000.A1", "claims", body=b"<xml>v1 claims</xml>")  # unchanged
    result = PatentBioactivityCorpusJob().run(_base_args(tmp_path, refresh=True))

    assert result.records_downloaded == 1  # description changed
    assert result.records_skipped_unchanged == 1  # claims unchanged, reverified with a request
    df = _manifest_df(tmp_path)
    desc_versions = sorted(df[df["artifact_type"] == "description"]["version"])
    assert desc_versions == [1, 2]


@responses.activate
def test_since_until_filters_candidates(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [
        _epo_row("EP1000000A1", pub_date="2026-01-01"),
        _epo_row("EP2000000A1", pub_date="2020-01-01"),
    ])
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description")
    _mock_artifact("EP.1000000.A1", "claims")

    result = PatentBioactivityCorpusJob().run(_base_args(tmp_path, since="2025-01-01"))

    assert result.queries_run == 1  # only EP1000000A1 is in range
    df = _manifest_df(tmp_path)
    assert set(df["publication_number"]) == {"EP1000000A1"}


@responses.activate
def test_limit_prioritizes_fresh_over_backlog(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])
    _mock_auth()
    for _ in range(5):
        _mock_artifact("EP.1000000.A1", "description", status=500, body=b"")
    for _ in range(5):
        _mock_artifact("EP.1000000.A1", "claims", status=500, body=b"")
    PatentBioactivityCorpusJob().run(_base_args(tmp_path))  # both fail -> backlog

    responses.reset()
    _mock_auth()
    _write_epo_manifest(
        tmp_path / "DATA" / "manifests" / "epo.parquet",
        [_epo_row("EP1000000A1"), _epo_row("EP2000000A1")],  # EP2000000A1 is brand new (fresh)
    )
    # limit=1 gives exactly ONE artifact id a slot -- fresh_ids are
    # sorted alphabetically, and "PATENTBIO_EP2000000A1_CLAIMS" sorts
    # before "...DESCRIPTION", so that's the one slot fresh gets.
    # EP1000000A1's 2 backlog artifacts don't get attempted at all this
    # run (no slots left), so no mocks are needed for them.
    _mock_artifact("EP.2000000.A1", "claims", body=b"<xml>fresh</xml>")

    result = PatentBioactivityCorpusJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert set(df["publication_number"]) == {"EP2000000A1"}  # fresh got the single slot, not EP1000000A1's backlog retry
    assert set(df["artifact_type"]) == {"claims"}


@responses.activate
def test_no_candidates_raises_clear_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [])

    try:
        PatentBioactivityCorpusJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised


@responses.activate
def test_query_id_deterministic_and_stable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [_epo_row("EP1000000A1")])
    _mock_auth()
    _mock_artifact("EP.1000000.A1", "description")
    _mock_artifact("EP.1000000.A1", "claims")
    PatentBioactivityCorpusJob().run(_base_args(tmp_path))

    attempts = _attempts_df(tmp_path)
    assert set(attempts["query_id"]) == {"PATENTBIO_EP1000000A1_DESCRIPTION", "PATENTBIO_EP1000000A1_CLAIMS"}
