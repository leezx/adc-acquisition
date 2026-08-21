import argparse
import json

import pandas as pd
import pytest

from jobs.conference_abstract_corpus.job import ConferenceAbstractCorpusJob


def _write_aacr_year(corpus_root, year, records):
    d = corpus_root / "AACR_Abstracts" / f"AACR_{year}_ADC"
    d.mkdir(parents=True, exist_ok=True)
    (d / "adc_abstracts.json").write_text(json.dumps(records), encoding="utf-8")


def _write_asco_year(corpus_root, year, records):
    d = corpus_root / "ASCO_Abstracts" / f"ASCO_{year}_ADC"
    d.mkdir(parents=True, exist_ok=True)
    (d / "adc_abstracts.json").write_text(json.dumps({"year": year, "records": records}), encoding="utf-8")


def _aacr_record(abstract_number="1214", doi="10.1158/1538-7445.AM2020-1214", title="An anti-HER2 ADC", abstract_text="Some abstract text.", published_print=None):
    return {
        "abstract_number": abstract_number,
        "presentation_id": f"#{abstract_number}",
        "title": title,
        "authors": ["Jane Doe"],
        "affiliations": ["Some University"],
        "abstract_text": abstract_text,
        "adc_targets": ["HER2"],
        "doi": doi,
        "published_online": {},
        "published_print": published_print if published_print is not None else {"date-parts": [[2020, 8, 15]]},
        "container_title": "Cancer Research",
        "crossref_url": f"https://doi.org/{doi}" if doi else None,
        "aacrjournals_url": "https://aacrjournals.org/example",
    }


def _asco_record(abs_id="1036", doi="10.1200/JCO.2020.38.15_suppl.1036", title="A HER2 ADC trial", abstract="Some ASCO abstract.", publication_date="2020-5-20"):
    return {
        "absId": abs_id,
        "doi": doi,
        "title": title,
        "drug": "Trastuzumab deruxtecan",
        "target": "HER2",
        "authors": ["John Smith"],
        "publication_date": publication_date,
        "source_url": f"https://ascopubs.org/doi/{doi}",
        "abstract": abstract,
        "clinical_trials": ["NCT03248492"],
    }


def _base_args(tmp_path, corpus_root, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), corpus_root=str(corpus_root),
        queries_file="configs/conference_abstract_corpus_queries.yaml",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture(autouse=True)
def _chdir_to_repo_root(monkeypatch):
    # The job's default --queries-file argument resolves relative to CWD;
    # tests must run with the real repo's configs/ on the resolvable path.
    import pathlib
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    monkeypatch.chdir(repo_root)


def test_missing_corpus_root_raises(tmp_path):
    args = _base_args(tmp_path, tmp_path / "does_not_exist")
    with pytest.raises(RuntimeError, match="not found"):
        ConferenceAbstractCorpusJob().run(args)


def test_basic_materialization_builds_manifest_discovery_and_attempts(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2020, [_aacr_record()])
    _write_asco_year(corpus_root, 2020, [_asco_record()])

    args = _base_args(tmp_path, corpus_root)
    result = ConferenceAbstractCorpusJob().run(args)

    assert result.records_discovered == 2
    assert result.records_downloaded == 2

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    assert len(manifest) == 2
    assert set(manifest["conference"]) == {"AACR", "ASCO"}
    assert set(manifest["doi"]) == {"10.1158/1538-7445.am2020-1214", "10.1200/jco.2020.38.15_suppl.1036"}

    discovery = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus_discovery.parquet")
    assert len(discovery) == 2
    query_by_source_id = dict(zip(discovery["source_record_id"], discovery["query_id"]))
    assert query_by_source_id["10.1158/1538-7445.am2020-1214"] == "CONFERENCE_AACR_001"
    assert query_by_source_id["10.1200/jco.2020.38.15_suppl.1036"] == "CONFERENCE_ASCO_001"

    attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus_attempts.parquet")
    assert len(attempts) == 2
    assert set(attempts["status"]) == {"success"}


def test_doi_is_normalized_lowercase(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2020, [_aacr_record(doi="10.1158/1538-7445.AM2020-1214")])

    ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    assert manifest.iloc[0]["source_record_id"] == "10.1158/1538-7445.am2020-1214"
    assert manifest.iloc[0]["doi"] == "10.1158/1538-7445.am2020-1214"


def test_aacr_record_without_doi_falls_back_to_composite_id_and_no_date(tmp_path):
    corpus_root = tmp_path / "corpus"
    # AACR 2026's real schema (PDF-extracted, ahead of Crossref indexing) has
    # no doi AND no published_online/published_print keys at all.
    record = _aacr_record(abstract_number="9999", doi=None, published_print={})
    _write_aacr_year(corpus_root, 2026, [record])

    ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    row = manifest.iloc[0]
    assert row["source_record_id"] == "aacr:2026:9999"
    assert row["doi"] is None
    assert row["publication_or_release_date"] is None


def test_asco_date_is_zero_padded(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_asco_year(corpus_root, 2020, [_asco_record(publication_date="2020-5-20")])

    ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    assert manifest.iloc[0]["publication_or_release_date"] == "2020-05-20"


def test_since_until_filter_by_publication_date(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_asco_year(corpus_root, 2020, [
        _asco_record(abs_id="1", doi="10.1200/jco.2020.38.15_suppl.1", publication_date="2020-1-1"),
        _asco_record(abs_id="2", doi="10.1200/jco.2020.38.15_suppl.2", publication_date="2020-12-1"),
    ])

    ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root, since="2020-06-01"))

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    assert len(manifest) == 1
    assert manifest.iloc[0]["publication_or_release_date"] == "2020-12-01"


def test_since_never_excludes_undated_records_from_change_detection(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2026, [_aacr_record(doi=None, published_print={}, abstract_text="Original text.")])

    ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    assert len(manifest) == 1
    assert manifest.iloc[0]["version"] == 1

    _write_aacr_year(corpus_root, 2026, [_aacr_record(doi=None, published_print={}, abstract_text="Corrected text.")])
    result2 = ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root, since="2026-08-01"))

    assert result2.records_discovered == 1
    assert result2.records_downloaded == 1
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    latest = manifest.sort_values("version").iloc[-1]
    assert latest["version"] == 2
    assert latest["abstract"] == "Corrected text."


def test_dry_run_writes_nothing(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2020, [_aacr_record()])

    result = ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root, dry_run=True))

    assert result.records_discovered == 1
    assert not (tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet").exists()


def test_limit_caps_materialization(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2020, [
        _aacr_record(abstract_number="1", doi="10.1158/1538-7445.am2020-1"),
        _aacr_record(abstract_number="2", doi="10.1158/1538-7445.am2020-2"),
    ])

    result = ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root, limit=1))

    assert result.records_discovered == 2
    assert result.records_downloaded == 1


def test_rerun_with_unchanged_corpus_skips_without_new_version(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2020, [_aacr_record()])

    ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))
    result2 = ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))

    assert result2.records_downloaded == 0
    assert result2.records_skipped_unchanged == 1

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    assert len(manifest) == 1
    assert manifest.iloc[0]["version"] == 1


def test_content_change_bumps_version(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2020, [_aacr_record(abstract_text="Original text.")])
    ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))

    _write_aacr_year(corpus_root, 2020, [_aacr_record(abstract_text="Corrected text.")])
    result2 = ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))

    assert result2.records_downloaded == 1
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "conference_abstract_corpus.parquet")
    # Both versions are kept (never-overwrite versioning, same as every other
    # job's manifest) -- the latest version carries the corrected content.
    assert len(manifest) == 2
    assert sorted(manifest["version"]) == [1, 2]
    latest = manifest.sort_values("version").iloc[-1]
    assert latest["version"] == 2
    assert latest["abstract"] == "Corrected text."


def test_new_year_folder_picked_up_without_code_change(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2020, [_aacr_record(abstract_number="1", doi="10.1158/1538-7445.am2020-1")])

    ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))

    _write_aacr_year(corpus_root, 2027, [_aacr_record(abstract_number="2", doi="10.1158/1538-7445.am2027-2")])
    result2 = ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))

    assert result2.records_discovered == 2
    assert result2.records_downloaded == 1


def test_missing_query_id_in_registry_raises(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_aacr_year(corpus_root, 2020, [_aacr_record()])
    bad_queries = tmp_path / "empty_queries.yaml"
    bad_queries.write_text("queries: []\n", encoding="utf-8")

    args = _base_args(tmp_path, corpus_root, queries_file=str(bad_queries))
    with pytest.raises(RuntimeError, match="CONFERENCE_AACR_001"):
        ConferenceAbstractCorpusJob().run(args)


def test_no_records_in_corpus_raises(tmp_path):
    corpus_root = tmp_path / "corpus"
    (corpus_root / "AACR_Abstracts").mkdir(parents=True)
    (corpus_root / "ASCO_Abstracts").mkdir(parents=True)

    with pytest.raises(RuntimeError, match="0 records"):
        ConferenceAbstractCorpusJob().run(_base_args(tmp_path, corpus_root))
