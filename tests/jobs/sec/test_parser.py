from jobs.sec.parser import (
    filings_from_recent_block,
    filter_relevant_forms,
    list_exhibit_entries,
    parse_document_format_table,
    within_date_range,
)

# Trimmed from a real filing's {accession}-index.htm ("Document Format
# Files" table) — https://www.sec.gov/Archives/edgar/data/1060736/000106073623000032/,
# fetched live on 2026-08-11. Deliberately keeps the primary document row,
# a real EX-10.x exhibit, an EX-31.x exhibit, a GRAPHIC support file (an
# embedded image referenced from within an exhibit — not itself an
# exhibit), and the trailing "Complete submission text file" row (no Type).
INDEX_PAGE_HTML = """
<div class="tableFile">
<p>Document Format Files</p>
<table class="tableFile" summary="Document Format Files">
<tr>
<th scope="col">Seq</th>
<th scope="col">Description</th>
<th scope="col">Document</th>
<th scope="col">Type</th>
<th scope="col">Size</th>
</tr>
<tr>
<td scope="row">1</td>
<td scope="row">10-Q</td>
<td scope="row"><a href="/ix?doc=/Archives/edgar/data/1060736/000106073623000032/sgen-20230331.htm">sgen-20230331.htm</a>&nbsp;&nbsp;<span>iXBRL</span></td>
<td scope="row">10-Q</td>
<td scope="row">1419747</td>
</tr>
<tr class="evenRow">
<td scope="row">2</td>
<td scope="row">EX-10.3</td>
<td scope="row"><a href="/Archives/edgar/data/1060736/000106073623000032/ex103abbottsgn-30manufac.htm">ex103abbottsgn-30manufac.htm</a></td>
<td scope="row">EX-10.3</td>
<td scope="row">8275</td>
</tr>
<tr>
<td scope="row">9</td>
<td scope="row">EX-31.1</td>
<td scope="row"><a href="/Archives/edgar/data/1060736/000106073623000032/ex-3112023q1.htm">ex-3112023q1.htm</a></td>
<td scope="row">EX-31.1</td>
<td scope="row">10628</td>
</tr>
<tr class="evenRow">
<td scope="row">18</td>
<td scope="row">&nbsp;</td>
<td scope="row"><a href="/Archives/edgar/data/1060736/000106073623000032/ex103abbottsgn-30manufac001.jpg">ex103abbottsgn-30manufac001.jpg</a></td>
<td scope="row">GRAPHIC</td>
<td scope="row">257612</td>
</tr>
<tr>
<td scope="row">&nbsp;</td>
<td scope="row">Complete submission text file</td>
<td scope="row"><a href="/Archives/edgar/data/1060736/000106073623000032/0001060736-23-000032.txt">0001060736-23-000032.txt</a></td>
<td scope="row">&nbsp;</td>
<td scope="row">21708707</td>
</tr>
</table>
</div>
"""

FULL_RECENT = {
    "accessionNumber": ["0000078003-00-000007", "0000078003-00-000016"],
    "form": ["8-K", "10-Q"],
    "filingDate": ["2000-02-18", "2000-05-17"],
    "reportDate": ["2000-02-15", "2000-03-31"],
    "primaryDocument": ["d1.html", "q1.html"],
    "items": ["2.01,9.01", ""],
    "fileNumber": ["001-08689", "001-08689"],
    "filmNumber": ["12345", "12346"],
}


def test_zips_parallel_arrays_into_filings():
    filings = filings_from_recent_block(FULL_RECENT)
    assert len(filings) == 2
    f0 = filings[0]
    assert f0.accession_number == "0000078003-00-000007"
    assert f0.form == "8-K"
    assert f0.filing_date == "2000-02-18"
    assert f0.report_date == "2000-02-15"
    assert f0.primary_document == "d1.html"
    assert f0.item_codes == ["2.01", "9.01"]
    assert f0.file_number == "001-08689"
    assert f0.film_number == "12345"


def test_empty_items_string_gives_empty_list():
    filings = filings_from_recent_block(FULL_RECENT)
    assert filings[1].item_codes == []


def test_skips_entries_with_missing_accession_number():
    recent = {**FULL_RECENT, "accessionNumber": ["0000078003-00-000007", ""]}
    filings = filings_from_recent_block(recent)
    assert len(filings) == 1


def test_missing_optional_arrays_default_to_none_or_empty():
    minimal = {"accessionNumber": ["0000078003-00-000007"], "form": ["8-K"]}
    filings = filings_from_recent_block(minimal)
    assert len(filings) == 1
    f = filings[0]
    assert f.filing_date is None
    assert f.report_date is None
    assert f.primary_document is None
    assert f.item_codes == []
    assert f.file_number is None


def test_empty_recent_block_returns_empty_list():
    assert filings_from_recent_block({}) == []


def test_filter_relevant_forms_keeps_only_known_forms_and_amendments():
    recent = {
        "accessionNumber": ["a1", "a2", "a3", "a4"],
        "form": ["8-K", "4", "10-K/A", "SC 13D"],
    }
    filings = filings_from_recent_block(recent)
    relevant = filter_relevant_forms(filings)
    assert sorted(f.accession_number for f in relevant) == ["a1", "a3"]


def test_within_date_range_no_bounds_keeps_everything():
    assert within_date_range(None, None, None) is True
    assert within_date_range("2020-01-01", None, None) is True


def test_within_date_range_since_and_until():
    assert within_date_range("2022-06-01", "2022-01-01", "2022-12-31") is True
    assert within_date_range("2021-12-31", "2022-01-01", "2022-12-31") is False
    assert within_date_range("2023-01-01", "2022-01-01", "2022-12-31") is False


def test_within_date_range_missing_date_excluded_once_a_range_is_requested():
    assert within_date_range(None, "2022-01-01", None) is False


def test_parse_document_format_table_extracts_all_rows():
    entries = parse_document_format_table(INDEX_PAGE_HTML)
    assert [e.filename for e in entries] == [
        "sgen-20230331.htm",
        "ex103abbottsgn-30manufac.htm",
        "ex-3112023q1.htm",
        "ex103abbottsgn-30manufac001.jpg",
        "0001060736-23-000032.txt",
    ]
    assert entries[1].doc_type == "EX-10.3"
    assert entries[1].description == "EX-10.3"
    assert entries[3].doc_type == "GRAPHIC"


def test_parse_document_format_table_no_table_returns_empty():
    assert parse_document_format_table("<html>no table here</html>") == []


def test_list_exhibit_entries_keeps_only_ex_typed_documents():
    entries = parse_document_format_table(INDEX_PAGE_HTML)
    exhibits = list_exhibit_entries(entries, primary_document="sgen-20230331.htm")
    # Real exhibits (EX-10.3, EX-31.1) only -- not the primary 10-Q, not the
    # GRAPHIC support file, not the complete-submission .txt.
    assert [e.filename for e in exhibits] == ["ex103abbottsgn-30manufac.htm", "ex-3112023q1.htm"]


def test_list_exhibit_entries_excludes_primary_even_if_its_type_looks_ex_like():
    entries = [
        parse_document_format_table(INDEX_PAGE_HTML)[1],  # EX-10.3 row
    ]
    assert list_exhibit_entries(entries, primary_document="ex103abbottsgn-30manufac.htm") == []
