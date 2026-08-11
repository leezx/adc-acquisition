from jobs.sec.parser import filings_from_recent_block, filter_relevant_forms

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
