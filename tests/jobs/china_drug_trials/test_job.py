import argparse
import pathlib

import pandas as pd
import pytest

from jobs.china_drug_trials.job import ChinaDrugTrialsJob

_HEADER_ROWS = """<Row>
    <Cell><Data ss:Type="String">序号</Data></Cell>
    <Cell><Data ss:Type="String">登记号</Data></Cell>
    <Cell><Data ss:Type="String">试验状态</Data></Cell>
    <Cell><Data ss:Type="String">药物名称</Data></Cell>
    <Cell><Data ss:Type="String">适应症</Data></Cell>
    <Cell><Data ss:Type="String">试验通俗题目</Data></Cell>
   </Row>"""

_DATA_ROW_TEMPLATE = """<Row>
    <Cell><Data ss:Type="String">{seq}</Data></Cell>
    <Cell><Data ss:Type="String"><![CDATA[{reg}]]></Data></Cell>
    <Cell><Data ss:Type="String"><![CDATA[{status}]]></Data></Cell>
    <Cell><Data ss:Type="String"><![CDATA[{drug}]]></Data></Cell>
    <Cell><Data ss:Type="String"><![CDATA[{indication}]]></Data></Cell>
    <Cell><Data ss:Type="String"><![CDATA[{title}]]></Data></Cell>
   </Row>"""


def _data_row(seq=1, reg="CTR20262727", status="进行中", drug="BY101921片",
              indication="恶性实体瘤", title="TROP2 抗体药物偶联物研究"):
    return _DATA_ROW_TEMPLATE.format(seq=seq, reg=reg, status=status, drug=drug, indication=indication, title=title)


def _write_export(corpus_dir, filename, data_rows_xml):
    corpus_dir.mkdir(parents=True, exist_ok=True)
    path = corpus_dir / filename
    path.write_text(
        f"""<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="Sheet1">
  <Table>
   {_HEADER_ROWS}
   {data_rows_xml}
  </Table>
 </Worksheet>
</Workbook>
""",
        encoding="utf-8",
    )
    return path


def _write_queries(tmp_path, exports_by_query, filename="queries.yaml"):
    """exports_by_query: {query_id: [(query_text, active, [(filename, export_date), ...])]}
    Simplified helper below builds the common single-query-per-id case."""
    path = tmp_path / filename
    blocks = []
    for query_id, (query_text, active, exports) in exports_by_query.items():
        exports_yaml = "\n".join(
            f'      - filename: "{fname}"\n        export_date: "{edate}"' for fname, edate in exports
        )
        blocks.append(f"""  - query_id: {query_id}
    query_version: 1
    query_text: "{query_text}"
    purpose: "test"
    active: {"true" if active else "false"}
    exports:
{exports_yaml}""")
    path.write_text("queries:\n" + "\n".join(blocks) + "\n", encoding="utf-8")
    return path


def _base_args(tmp_path, corpus_dir, queries_file, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), corpus_dir=str(corpus_dir),
        queries_file=str(queries_file),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture(autouse=True)
def _chdir_to_repo_root(monkeypatch):
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    monkeypatch.chdir(repo_root)


def test_missing_corpus_dir_raises(tmp_path):
    queries_file = _write_queries(tmp_path, {"Q1": ("ADC", True, [("export.xls", "20260831")])})
    args = _base_args(tmp_path, tmp_path / "does_not_exist", queries_file)
    with pytest.raises(RuntimeError, match="not found"):
        ChinaDrugTrialsJob().run(args)


def test_empty_corpus_dir_raises(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    queries_file = _write_queries(tmp_path, {"Q1": ("ADC", True, [("export.xls", "20260831")])})
    args = _base_args(tmp_path, corpus_dir, queries_file)
    with pytest.raises(RuntimeError, match="0 trials found"):
        ChinaDrugTrialsJob().run(args)


def test_no_active_queries_raises(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export.xls", _data_row())
    queries_file = _write_queries(tmp_path, {"Q1": ("ADC", False, [("export.xls", "20260831")])})
    args = _base_args(tmp_path, corpus_dir, queries_file)
    with pytest.raises(RuntimeError, match="no active queries"):
        ChinaDrugTrialsJob().run(args)


def test_basic_materialization_builds_manifest_discovery_and_attempts(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export.xls", _data_row(reg="CTR20262727") + _data_row(seq=2, reg="CTR20262728"))
    queries_file = _write_queries(tmp_path, {"CHINADRUGTRIALS_002": ("抗体药物偶联物", True, [("export.xls", "20260831")])})

    result = ChinaDrugTrialsJob().run(_base_args(tmp_path, corpus_dir, queries_file))

    assert result.records_discovered == 2
    assert result.records_downloaded == 2

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials.parquet")
    assert len(manifest) == 2
    assert set(manifest["source_record_id"]) == {"CTR20262727", "CTR20262728"}
    assert all(v == 1 for v in manifest["version"])

    discovery = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials_discovery.parquet")
    assert len(discovery) == 2
    assert set(discovery["query_id"]) == {"CHINADRUGTRIALS_002"}

    attempts = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials_attempts.parquet")
    assert set(attempts["status"]) == {"success"}


def test_second_run_is_idempotent_skipped_unchanged(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export.xls", _data_row())
    queries_file = _write_queries(tmp_path, {"Q1": ("ADC", True, [("export.xls", "20260831")])})

    args = _base_args(tmp_path, corpus_dir, queries_file)
    ChinaDrugTrialsJob().run(args)
    result2 = ChinaDrugTrialsJob().run(args)

    assert result2.records_downloaded == 0
    assert result2.records_skipped_unchanged == 1

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials.parquet")
    assert len(manifest) == 1  # no duplicate row, no spurious version bump


def test_content_change_bumps_version(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export1.xls", _data_row(status="进行中"))
    queries_file = _write_queries(tmp_path, {
        "Q1": ("ADC", True, [("export1.xls", "20260831"), ("export2.xls", "20260901")]),
    })
    args = _base_args(tmp_path, corpus_dir, queries_file)
    ChinaDrugTrialsJob().run(args)

    _write_export(corpus_dir, "export2.xls", _data_row(status="已完成"))
    result = ChinaDrugTrialsJob().run(args)

    assert result.records_downloaded == 1
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials.parquet")
    rows = manifest[manifest["source_record_id"] == "CTR20262727"].sort_values("version")
    assert list(rows["version"]) == [1, 2]
    assert rows.iloc[-1]["trial_status"] == "已完成"


def test_same_registration_number_discovered_by_two_queries_keeps_both_discovery_observations(tmp_path):
    """Regression (reviewer-flagged round-1 fix): a registration number
    found in TWO DIFFERENT queries' export files must produce TWO
    discovery-ledger rows, one per query -- content dedup (one current
    manifest row) is correct, but collapsing the discovery ledger to only
    the winning file's query would silently erase the other query's own
    real discovery of that record."""
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export_a.xls", _data_row(status="进行中"))
    _write_export(corpus_dir, "export_b.xls", _data_row(status="进行中"))
    queries_file = _write_queries(tmp_path, {
        "Q1": ("ADC", True, [("export_a.xls", "20260831")]),
        "Q2": ("抗体药物偶联物", True, [("export_b.xls", "20260831")]),
    })

    result = ChinaDrugTrialsJob().run(_base_args(tmp_path, corpus_dir, queries_file))

    assert result.records_discovered == 1  # one distinct registration number

    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials.parquet")
    assert len(manifest) == 1  # content dedup: one current snapshot

    discovery = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials_discovery.parquet")
    rows = discovery[discovery["source_record_id"] == "CTR20262727"]
    assert len(rows) == 2  # both discovery observations retained
    assert set(rows["query_id"]) == {"Q1", "Q2"}


def test_duplicate_row_within_same_file_is_not_double_counted_as_discovery(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export.xls", _data_row() + _data_row())  # same regnum twice, same file
    queries_file = _write_queries(tmp_path, {"Q1": ("ADC", True, [("export.xls", "20260831")])})

    ChinaDrugTrialsJob().run(_base_args(tmp_path, corpus_dir, queries_file))

    discovery = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials_discovery.parquet")
    rows = discovery[discovery["source_record_id"] == "CTR20262727"]
    assert len(rows) == 1  # a file re-listing its own row twice is not a second discovery event


def test_unchanged_trial_in_new_export_file_stays_skipped_unchanged(tmp_path):
    """Regression (same lesson as WHO ICTRP): content_hash must NOT depend
    on export_filename/export_date -- a human re-downloading the same
    search under a new filename/date, with the trial's real content
    unchanged, must not spuriously bump the version."""
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export1.xls", _data_row(status="进行中"))
    queries_file = _write_queries(tmp_path, {
        "Q1": ("ADC", True, [("export1.xls", "20260831"), ("export2.xls", "20260901")]),
    })
    args = _base_args(tmp_path, corpus_dir, queries_file)
    result1 = ChinaDrugTrialsJob().run(args)
    assert result1.records_downloaded == 1

    _write_export(corpus_dir, "export2.xls", _data_row(status="进行中"))  # identical content
    result2 = ChinaDrugTrialsJob().run(args)

    assert result2.records_downloaded == 0
    assert result2.records_skipped_unchanged == 1
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials.parquet")
    rows = manifest[manifest["source_record_id"] == "CTR20262727"]
    assert len(rows) == 1


def test_most_recent_export_file_wins_for_overlapping_registration_number(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export1.xls", _data_row(status="进行中"))
    _write_export(corpus_dir, "export2.xls", _data_row(status="已完成"))
    queries_file = _write_queries(tmp_path, {
        "Q1": ("ADC", True, [("export1.xls", "20260801"), ("export2.xls", "20260831")]),
    })

    result = ChinaDrugTrialsJob().run(_base_args(tmp_path, corpus_dir, queries_file))

    assert result.records_discovered == 1
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials.parquet")
    assert manifest.iloc[0]["trial_status"] == "已完成"
    assert manifest.iloc[0]["export_filename"] == "export2.xls"


def test_registration_number_only_in_older_export_is_not_lost(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export1.xls", _data_row(reg="CTR20000001"))
    _write_export(corpus_dir, "export2.xls", _data_row(reg="CTR20000002"))
    queries_file = _write_queries(tmp_path, {
        "Q1": ("ADC", True, [("export1.xls", "20260801"), ("export2.xls", "20260831")]),
    })

    result = ChinaDrugTrialsJob().run(_base_args(tmp_path, corpus_dir, queries_file))

    assert result.records_discovered == 2
    manifest = pd.read_parquet(tmp_path / "DATA" / "manifests" / "china_drug_trials.parquet")
    assert set(manifest["source_record_id"]) == {"CTR20000001", "CTR20000002"}


def test_dry_run_makes_no_manifest(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export.xls", _data_row())
    queries_file = _write_queries(tmp_path, {"Q1": ("ADC", True, [("export.xls", "20260831")])})

    result = ChinaDrugTrialsJob().run(_base_args(tmp_path, corpus_dir, queries_file, dry_run=True))

    assert result.records_discovered == 1
    assert not (tmp_path / "DATA" / "manifests" / "china_drug_trials.parquet").exists()


def test_export_file_with_no_attributed_query_raises(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "unmapped.xls", _data_row())
    queries_file = _write_queries(tmp_path, {"Q1": ("ADC", True, [("other.xls", "20260831")])})
    args = _base_args(tmp_path, corpus_dir, queries_file)

    with pytest.raises(RuntimeError, match=r"no query attributed to export file\(s\).*unmapped\.xls"):
        ChinaDrugTrialsJob().run(args)


def test_two_queries_claiming_the_same_filename_raises(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export.xls", _data_row())
    conflicting = tmp_path / "conflicting_queries.yaml"
    conflicting.write_text(
        """
queries:
  - query_id: QA
    query_version: 1
    query_text: "A"
    purpose: "test"
    active: true
    exports:
      - filename: "export.xls"
        export_date: "20260831"
  - query_id: QB
    query_version: 1
    query_text: "B"
    purpose: "test"
    active: true
    exports:
      - filename: "export.xls"
        export_date: "20260831"
""",
        encoding="utf-8",
    )
    args = _base_args(tmp_path, corpus_dir, conflicting)
    with pytest.raises(ValueError, match="claimed by both"):
        ChinaDrugTrialsJob().run(args)


def test_unrelated_filename_in_corpus_dir_without_xls_extension_is_ignored(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_export(corpus_dir, "export.xls", _data_row())
    (corpus_dir / "readme.txt").write_text("not an export file", encoding="utf-8")
    queries_file = _write_queries(tmp_path, {"Q1": ("ADC", True, [("export.xls", "20260831")])})

    result = ChinaDrugTrialsJob().run(_base_args(tmp_path, corpus_dir, queries_file))
    assert result.records_discovered == 1
