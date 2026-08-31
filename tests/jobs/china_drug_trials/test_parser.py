import pytest

from jobs.china_drug_trials.parser import parse_export_file

_HEADER_ROWS = """<Row ss:AutoFitHeight="0" ss:Height="39.9375" ss:StyleID="s63">
    <Cell ss:MergeAcross="5" ss:StyleID="s62"><Data ss:Type="String">临床试验查询结果列表</Data></Cell>
   </Row>
   <Row ss:AutoFitHeight="0" ss:Height="30" ss:StyleID="s69">
    <Cell ss:StyleID="s68"><Data ss:Type="String">序号</Data></Cell>
    <Cell ss:StyleID="s68"><Data ss:Type="String">登记号</Data></Cell>
    <Cell ss:StyleID="s68"><Data ss:Type="String">试验状态</Data></Cell>
    <Cell ss:StyleID="s68"><Data ss:Type="String">药物名称</Data></Cell>
    <Cell ss:StyleID="s68"><Data ss:Type="String">适应症</Data></Cell>
    <Cell ss:StyleID="s68"><Data ss:Type="String">试验通俗题目</Data></Cell>
   </Row>"""

_DATA_ROW_TEMPLATE = """<Row ss:AutoFitHeight="0" ss:Height="30" ss:StyleID="s67">
    <Cell ss:StyleID="s66"><Data ss:Type="String">{seq}</Data></Cell>
    <Cell ss:StyleID="s66"><Data ss:Type="String"><![CDATA[{reg}]]></Data></Cell>
    <Cell ss:StyleID="s66"><Data ss:Type="String"><![CDATA[{status}]]></Data></Cell>
    <Cell ss:StyleID="s66"><Data ss:Type="String"><![CDATA[{drug}]]></Data></Cell>
    <Cell ss:StyleID="s66"><Data ss:Type="String"><![CDATA[{indication}]]></Data></Cell>
    <Cell ss:StyleID="s66"><Data ss:Type="String"><![CDATA[{title}]]></Data></Cell>
   </Row>"""


def _workbook_xml(data_rows_xml):
    return f"""<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:html="http://www.w3.org/TR/REC-html40">
 <Worksheet ss:Name="Sheet1">
  <Table ss:ExpandedColumnCount="6" ss:ExpandedRowCount="3">
   {_HEADER_ROWS}
   {data_rows_xml}
  </Table>
 </Worksheet>
</Workbook>
"""


def _data_row(seq=1, reg="CTR20262727", status="进行中&nbsp;尚未招募", drug="BY101921片",
              indication="恶性实体瘤", title="一项TROP2 抗体药物偶联物研究"):
    return _DATA_ROW_TEMPLATE.format(seq=seq, reg=reg, status=status, drug=drug, indication=indication, title=title)


def _write_workbook(tmp_path, filename, data_rows_xml):
    path = tmp_path / filename
    path.write_text(_workbook_xml(data_rows_xml), encoding="utf-8")
    return path


def test_parse_single_row(tmp_path):
    path = _write_workbook(tmp_path, "export.xls", _data_row())
    trials = parse_export_file(path)
    assert len(trials) == 1
    trial = trials[0]
    assert trial["registration_number"] == "CTR20262727"
    assert trial["drug_name"] == "BY101921片"
    assert trial["indication"] == "恶性实体瘤"
    assert trial["public_title"] == "一项TROP2 抗体药物偶联物研究"


def test_nbsp_entity_inside_cdata_is_replaced_with_space(tmp_path):
    # &nbsp; appears LITERALLY inside <![CDATA[...]]> in the real export --
    # CDATA sections are never entity-decoded by an XML parser, so this
    # must be handled by explicit text cleaning, not XML entity resolution.
    path = _write_workbook(tmp_path, "export.xls", _data_row(status="进行中&nbsp;尚未招募"))
    trials = parse_export_file(path)
    assert trials[0]["trial_status"] == "进行中 尚未招募"


def test_parse_multiple_rows_preserves_order(tmp_path):
    rows = _data_row(seq=1, reg="CTR20000001") + _data_row(seq=2, reg="CTR20000002")
    path = _write_workbook(tmp_path, "export.xls", rows)
    trials = parse_export_file(path)
    assert [t["registration_number"] for t in trials] == ["CTR20000001", "CTR20000002"]


def test_sequence_column_is_dropped():
    from jobs.china_drug_trials.parser import _FIELDS
    assert "sequence" not in _FIELDS
    assert len(_FIELDS) == 5  # registration_number, trial_status, drug_name, indication, public_title


def test_wrong_root_element_raises(tmp_path):
    path = tmp_path / "not_an_export.xls"
    path.write_text("<?xml version='1.0'?><SomethingElse/>", encoding="utf-8")
    with pytest.raises(ValueError, match="does not look like"):
        parse_export_file(path)


def test_missing_header_row_raises(tmp_path):
    # A workbook that looks superficially right but never has the expected
    # 6-column Chinese header -- the export's column layout may have
    # changed, must fail loud rather than silently misread columns.
    body = """<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="Sheet1">
  <Table>
   <Row><Cell><Data ss:Type="String">unexpected content</Data></Cell></Row>
  </Table>
 </Worksheet>
</Workbook>
"""
    path = tmp_path / "export.xls"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="could not find the expected header row"):
        parse_export_file(path)


def test_short_malformed_row_is_skipped_not_crashed(tmp_path):
    malformed = """<Row><Cell><Data ss:Type="String">1</Data></Cell></Row>"""
    rows = malformed + _data_row(seq=2, reg="CTR20000002")
    path = _write_workbook(tmp_path, "export.xls", rows)
    trials = parse_export_file(path)
    assert len(trials) == 1
    assert trials[0]["registration_number"] == "CTR20000002"


def test_real_downloaded_exports_parse_without_error():
    """Live-data regression: parses the actual 3 files a human downloaded
    from chinadrugtrials.org.cn on 2026-08-31 (kept under DATA/raw/, not
    committed to git -- this test is skipped if they aren't present)."""
    from pathlib import Path
    corpus_dir = Path("DATA/raw/chinadrugtrials")
    files = sorted(corpus_dir.glob("*.xls")) if corpus_dir.exists() else []
    if not files:
        pytest.skip("no real chinadrugtrials export files present under DATA/raw/chinadrugtrials")
    total = 0
    for f in files:
        trials = parse_export_file(f)
        assert all(t["registration_number"] for t in trials)
        total += len(trials)
    assert total >= 1
