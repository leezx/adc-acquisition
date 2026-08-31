"""Parsing for CDE's chinadrugtrials.org.cn manually-downloaded "search
results" export file.

Live-verified 2026-08-31 (real files downloaded by a human via the search
results page's own "下载" button, dropped into `DATA/raw/chinadrugtrials/`):
despite the `.xls` extension, the file is Microsoft's legacy SpreadsheetML
XML format (`<?mso-application progid="Excel.Sheet"?>`), NOT a real binary
XLS/XLSX -- the same "extension lies about format" shape this project has
already seen (WHO ICTRP's `.xml` export is the genuine article; this one
merely LOOKS like Excel to a human double-clicking it). `xlrd`/`openpyxl`
cannot open this format; it must be parsed as plain XML.

Structure (verified against 3 real downloaded files, 41 total rows): one
`<Worksheet><Table>` with a merged title row ("临床试验查询结果列表"), a
header row naming exactly 6 columns in a fixed order (序号/登记号/试验状态/
药物名称/适应症/试验通俗题目), then one `<Row>` per trial. The header row is
matched by CONTENT, not a fixed row index, so a future export with an extra
banner row still parses correctly; a genuinely different column set (the
export format changing) fails loudly instead of silently misreading columns.

`序号` (display sequence number, resets per file/page) carries no stable
identity and is dropped -- `登记号` (registration_number, e.g. "CTR20262727")
is CDE's own cross-file-stable identifier and is used directly as
`source_record_id`.

The list-only export deliberately does NOT include the internal per-trial
UUID used by chinadrugtrials.org.cn's own detail-page URL
(`clinicaltrials.searchlistdetail.dhtml?id=<uuid>`) or any of the richer
detail-page fields (applicant/sponsor, phase, enrollment, etc.) -- verified
by grepping the real export files for any href/hyperlink data (none found).
Materializing those requires visiting a live detail page, which this
acquisition-only round deliberately does not do (see jobs/china_drug_trials/
job.py's module docstring for the access-model rationale) -- a follow-up
increment once terms/access are clearer.

`&nbsp;` appears LITERALLY inside a `<![CDATA[...]]>` text node in the real
export (e.g. "进行中&nbsp;尚未招募", joining two status phrases) -- CDATA
sections are never entity-decoded by an XML parser, so this project's own
generic text-cleaning must replace it explicitly rather than relying on
XML entity resolution.
"""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from pathlib import Path

_NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}

# Exact header text, in column order, verified against all 3 real export
# files -- used to LOCATE the header row by content (robust to an extra
# banner/title row above it), not by a fixed row index.
_EXPECTED_HEADER = ["序号", "登记号", "试验状态", "药物名称", "适应症", "试验通俗题目"]

# Column 0 (序号) is dropped -- see module docstring.
_FIELDS = ["registration_number", "trial_status", "drug_name", "indication", "public_title"]


def _cell_text(cell: ET.Element) -> str | None:
    data = cell.find("ss:Data", _NS)
    if data is None or data.text is None:
        return None
    text = data.text.replace("&nbsp;", " ")
    text = html.unescape(text).strip()
    return text or None


def _row_cells(row: ET.Element) -> list[str | None]:
    return [_cell_text(c) for c in row.findall("ss:Cell", _NS)]


def parse_export_file(path: Path) -> list[dict]:
    """Returns every trial row in one CDE search-results export file as a
    plain dict. Raises on a file that isn't this export shape (wrong root
    element, or the expected header row can't be found at all) rather than
    silently returning an empty list, matching every other job's "fail loud
    on a bad external input" precedent."""
    tree = ET.parse(path)
    root = tree.getroot()
    if not root.tag.endswith("}Workbook"):
        raise ValueError(
            f"{path} does not look like a chinadrugtrials.org.cn search-results export "
            f"(root element is <{root.tag}>, expected a SpreadsheetML <Workbook>)"
        )
    rows = root.findall(".//ss:Worksheet/ss:Table/ss:Row", _NS)
    header_idx = None
    for i, row in enumerate(rows):
        if _row_cells(row) == _EXPECTED_HEADER:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            f"{path}: could not find the expected header row {_EXPECTED_HEADER} -- "
            "this export's column layout may have changed since this parser was written"
        )
    trials = []
    for row in rows[header_idx + 1:]:
        cells = _row_cells(row)
        if len(cells) < len(_EXPECTED_HEADER):
            continue  # defensive: skip a malformed/short row rather than crash
        trials.append(dict(zip(_FIELDS, cells[1:len(_EXPECTED_HEADER)])))
    return trials
