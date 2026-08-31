import argparse
import pathlib

import pandas as pd
import pytest

from jobs.who_ictrp.job import WHOICTRPJob

TRIAL_TEMPLATE = """  <Trial>
    <TrialID>{trial_id}
    </TrialID>
    <Public_title>{title}
    </Public_title>
    <Scientific_title>A phase 1 study
    </Scientific_title>
    <Primary_sponsor>{sponsor}
    </Primary_sponsor>
    <Secondary_Sponsor/>
    <Source_Register>{source_register}
    </Source_Register>
    <web_address>{url}
    </web_address>
    <Recruitment_Status>{status}
    </Recruitment_Status>
    <other_records>No
    </other_records>
    <Phase>Phase 1
    </Phase>
    <Countries>United States
    </Countries>
    <Intervention>Drug: {intervention}
    </Intervention>
    <Condition>Solid tumors
    </Condition>
    <Date_registration3>{date_reg}
    </Date_registration3>
    <Last_Refreshed_on>24 August 2026
    </Last_Refreshed_on>
    <Target_size>100
    </Target_size>
    <Study_type>Interventional
    </Study_type>
  </Trial>
"""


def _trial_xml(**overrides):
    defaults = dict(
        trial_id="NCT01234567", title="A study of Foo-ADC", sponsor="Example Pharma",
        source_register="ClinicalTrials.gov", url="https://clinicaltrials.gov/study/NCT01234567",
        status="Recruiting", intervention="Foo-ADC", date_reg="20260101",
    )
    defaults.update(overrides)
    return TRIAL_TEMPLATE.format(**defaults)


def _write_export(corpus_dir, export_date, trial_xmls):
    corpus_dir.mkdir(parents=True, exist_ok=True)
    path = corpus_dir / f"ICTRP-Results-{export_date}.xml"
    body = "".join(trial_xmls)
    path.write_text(
        f"<?xml version='1.0' encoding='UTF-8' ?>\n<Trials_downloaded_from_ICTRP>\n{body}</Trials_downloaded_from_ICTRP>\n",
        encoding="utf-8",
    )
    return path


def _write_queries(tmp_path, export_file_dates, query_id="WHO_ICTRP_TEST", filename="queries.yaml"):
    """A minimal single-query registry attributing every given
    export_file_date to one test query -- mirrors the real
    configs/who_ictrp_queries.yaml's per-date `export_file_dates` shape
    (see jobs/who_ictrp/job.py's _load_export_date_query_map)."""
    dates_yaml = ", ".join(f'"{d}"' for d in export_file_dates)
    path = tmp_path / filename
    path.write_text(
        f"""
queries:
  - query_id: {query_id}
    query_version: 1
    query_text: "test query text"
    purpose: "test"
    active: true
    export_file_dates: [{dates_yaml}]
""",
        encoding="utf-8",
    )
    return path


def _base_args(tmp_path, corpus_dir, export_file_dates=("20260828",), **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), corpus_dir=str(corpus_dir),
        queries_file=str(_write_queries(tmp_path, export_file_dates)),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture(autouse=True)
def _chdir_to_repo_root(monkeypatch):
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    monkeypatch.chdir(repo_root)


def test_missing_corpus_dir_raises(tmp_path):
    args = _base_args(tmp_path, tmp_path / "does_not_exist")
    with pytest.raises(RuntimeError, match="not found"):
        WHOICTRPJob().run(args)


def test_empty_corpus_dir_raises(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    args = _base_args(tmp_path, corpus_dir)
    with pytest.raises(RuntimeError, match="0 trials found"):
        WHOICTRPJob().run(args)


def test_basic_materialization_builds_manifest_discovery_and_attempts(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [
        _trial_xml(trial_id="NCT01234567", source_register="ClinicalTrials.gov"),
        _trial_xml(trial_id="ChiCTR2600000001", source_register="ChiCTR", url="https://www.chictr.org.cn/x"),
    ])

    result = WHOICTRPJob().run(_base_args(tmp_path, corpus_dir))

    assert result.records_discovered == 2
    assert result.records_downloaded == 2

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "who_ictrp.parquet")
    assert len(manifest) == 2
    assert set(manifest["source_record_id"]) == {"NCT01234567", "ChiCTR2600000001"}
    assert set(manifest["source_register"]) == {"ClinicalTrials.gov", "ChiCTR"}
    assert all(v == 1 for v in manifest["version"])

    discovery = pd.read_parquet(tmp_path / "DATA" / "manifests" / "who_ictrp_discovery.parquet")
    assert len(discovery) == 2
    assert set(discovery["query_id"]) == {"WHO_ICTRP_TEST"}

    attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "who_ictrp_attempts.parquet")
    assert set(attempts["status"]) == {"success"}


def test_second_run_is_idempotent_skipped_unchanged(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [_trial_xml()])

    args = _base_args(tmp_path, corpus_dir)
    WHOICTRPJob().run(args)
    result2 = WHOICTRPJob().run(args)

    assert result2.records_downloaded == 0
    assert result2.records_skipped_unchanged == 1

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "who_ictrp.parquet")
    assert len(manifest) == 1  # no duplicate row, no spurious version bump


def test_content_change_bumps_version(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [_trial_xml(status="Recruiting")])
    args = _base_args(tmp_path, corpus_dir, export_file_dates=("20260828", "20260901"))
    WHOICTRPJob().run(args)

    _write_export(corpus_dir, "20260901", [_trial_xml(status="Completed")])
    result = WHOICTRPJob().run(args)

    assert result.records_downloaded == 1
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "who_ictrp.parquet")
    rows = manifest[manifest["source_record_id"] == "NCT01234567"].sort_values("version")
    assert list(rows["version"]) == [1, 2]  # old version preserved, new version appended
    assert rows.iloc[-1]["recruitment_status"] == "Completed"


def test_unchanged_trial_reexported_under_new_date_stays_skipped_unchanged(tmp_path):
    """Regression: a trial's own content_hash must NOT depend on
    export_file_date. A human re-running the manual export produces a
    NEW dated file every time even when a given trial's real content
    (sponsor/status/phase/etc.) hasn't changed at all -- if export_file_date
    were folded into content_hash, every unchanged trial would get a
    spurious version bump on every new export, defeating the whole
    point of content-hash-based change detection."""
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [_trial_xml(status="Recruiting")])
    args = _base_args(tmp_path, corpus_dir, export_file_dates=("20260828", "20260901"))
    result1 = WHOICTRPJob().run(args)
    assert result1.records_downloaded == 1

    # Same trial, IDENTICAL content, re-exported under a later date only.
    _write_export(corpus_dir, "20260901", [_trial_xml(status="Recruiting")])
    result2 = WHOICTRPJob().run(args)

    assert result2.records_downloaded == 0
    assert result2.records_skipped_unchanged == 1

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "who_ictrp.parquet")
    rows = manifest[manifest["source_record_id"] == "NCT01234567"]
    assert len(rows) == 1  # no spurious second version
    assert rows.iloc[0]["version"] == 1
    # skipped_unchanged never rewrites the manifest row, so it still shows
    # the export_file_date from when version 1 was actually materialized --
    # NOT the later file that merely re-confirmed the same content.
    assert rows.iloc[0]["export_file_date"] == "20260828"


def test_most_recent_export_file_wins_for_overlapping_trial(tmp_path):
    """A trial present in both an older and a newer export must reflect the
    NEWER file's state -- files are iterated oldest-first, later wins."""
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260801", [_trial_xml(trial_id="NCT01111111", status="Recruiting")])
    _write_export(corpus_dir, "20260828", [_trial_xml(trial_id="NCT01111111", status="Completed")])

    result = WHOICTRPJob().run(_base_args(tmp_path, corpus_dir, export_file_dates=("20260801", "20260828")))

    assert result.records_discovered == 1  # deduplicated across both files, not double-counted
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "who_ictrp.parquet")
    assert manifest.iloc[0]["recruitment_status"] == "Completed"
    assert manifest.iloc[0]["export_file_date"] == "20260828"


def test_trial_only_in_older_export_is_not_lost(tmp_path):
    """A trial present ONLY in an older export (absent from a later one)
    must still be materialized -- never silently dropped just because a
    newer export doesn't happen to include it."""
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260801", [_trial_xml(trial_id="NCT02222222")])
    _write_export(corpus_dir, "20260828", [_trial_xml(trial_id="NCT03333333")])

    result = WHOICTRPJob().run(_base_args(tmp_path, corpus_dir, export_file_dates=("20260801", "20260828")))

    assert result.records_discovered == 2
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "who_ictrp.parquet")
    assert set(manifest["source_record_id"]) == {"NCT02222222", "NCT03333333"}


def test_dry_run_makes_no_manifest(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [_trial_xml()])

    result = WHOICTRPJob().run(_base_args(tmp_path, corpus_dir, dry_run=True))

    assert result.records_discovered == 1
    assert not (tmp_path / "DATA" / "manifests" / "who_ictrp.parquet").exists()


def test_no_active_queries_raises(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [_trial_xml()])
    bad_queries = tmp_path / "empty_queries.yaml"
    bad_queries.write_text("queries: []\n", encoding="utf-8")

    args = _base_args(tmp_path, corpus_dir, queries_file=str(bad_queries))
    with pytest.raises(RuntimeError, match="no active queries"):
        WHOICTRPJob().run(args)


def test_export_date_with_no_attributed_query_raises(tmp_path):
    """A dated export file whose date isn't listed under ANY query's
    export_file_dates must hard-fail, never silently attribute it to
    whatever query happens to exist -- this is the exact mechanism that
    keeps an old unverified-query export from being retroactively
    relabeled as having come from a later, different confirmed query."""
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [_trial_xml()])
    # queries.yaml only attributes a DIFFERENT date -- 20260828 is unmapped.
    args = _base_args(tmp_path, corpus_dir, export_file_dates=("20260901",))

    with pytest.raises(RuntimeError, match="no query attributed to export_file_date.*20260828"):
        WHOICTRPJob().run(args)


def test_two_queries_claiming_the_same_export_date_raises(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [_trial_xml()])
    conflicting = tmp_path / "conflicting_queries.yaml"
    conflicting.write_text(
        """
queries:
  - query_id: WHO_ICTRP_A
    query_version: 1
    query_text: "query A"
    purpose: "test"
    active: true
    export_file_dates: ["20260828"]
  - query_id: WHO_ICTRP_B
    query_version: 1
    query_text: "query B"
    purpose: "test"
    active: true
    export_file_dates: ["20260828"]
""",
        encoding="utf-8",
    )

    args = _base_args(tmp_path, corpus_dir, queries_file=str(conflicting))
    with pytest.raises(ValueError, match="claimed by both"):
        WHOICTRPJob().run(args)


def test_unrelated_filename_in_corpus_dir_is_ignored(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "20260828", [_trial_xml()])
    (corpus_dir / "readme.txt").write_text("not an export file", encoding="utf-8")

    result = WHOICTRPJob().run(_base_args(tmp_path, corpus_dir))
    assert result.records_discovered == 1
