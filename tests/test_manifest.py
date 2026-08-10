import pandas as pd
import pytest

from adc_acquisition.manifest import COMMON_FIELDS, new_manifest_row, write_manifest


def _row(**overrides):
    base = dict(
        source="pubmed",
        source_record_id="1",
        source_record_type="journal_article",
        title="t",
        url="http://x",
        publication_or_release_date="2020",
        retrieved_at="2020-01-01T00:00:00+00:00",
        query_id="Q1",
        query_text="term",
        raw_file_path="/tmp/1.xml",
        raw_format="xml",
        content_hash="abc",
        download_status="success",
        http_status=200,
        license_or_access_note="public",
        parent_record_id=None,
        version=1,
        notes=None,
        pmid="1",
    )
    base.update(overrides)
    return new_manifest_row(extra_fields=["pmid"], **base)


def test_new_manifest_row_fills_all_common_fields():
    row = _row()
    assert set(COMMON_FIELDS).issubset(row.keys())


def test_new_manifest_row_rejects_undeclared_field():
    with pytest.raises(ValueError):
        new_manifest_row(extra_fields=["pmid"], source="pubmed", not_a_real_field="x")


def test_write_manifest_creates_new_file(tmp_path):
    path = tmp_path / "pubmed.parquet"
    df = write_manifest([_row()], path, extra_fields=["pmid"])
    assert path.exists()
    assert len(df) == 1
    reloaded = pd.read_parquet(path)
    assert reloaded.iloc[0]["source_record_id"] == "1"


def test_write_manifest_upserts_same_key(tmp_path):
    path = tmp_path / "pubmed.parquet"
    write_manifest([_row(download_status="failed", http_status=500)], path, extra_fields=["pmid"])
    df = write_manifest([_row(download_status="success", http_status=200)], path, extra_fields=["pmid"])
    assert len(df) == 1
    assert df.iloc[0]["download_status"] == "success"


def test_write_manifest_keeps_distinct_versions_as_separate_rows(tmp_path):
    path = tmp_path / "pubmed.parquet"
    write_manifest([_row(version=1, content_hash="hash-v1")], path, extra_fields=["pmid"])
    df = write_manifest([_row(version=2, content_hash="hash-v2")], path, extra_fields=["pmid"])
    assert len(df) == 2
    assert sorted(df["version"].tolist()) == [1, 2]


def test_write_manifest_empty_rows_on_existing_file_is_noop(tmp_path):
    path = tmp_path / "pubmed.parquet"
    write_manifest([_row()], path, extra_fields=["pmid"])
    df = write_manifest([], path, extra_fields=["pmid"])
    assert len(df) == 1
