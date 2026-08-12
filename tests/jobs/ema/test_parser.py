import io

import openpyxl

from jobs.ema.parser import (
    ParsedMedicine,
    is_adc_candidate,
    normalize_ema_date,
    parse_epar_documents,
    parse_medicines_xlsx,
    within_date_range,
)

# Trimmed from a real EPAR page (adcetris), fetched live on 2026-08-12.
EPAR_HTML_FRAGMENT = """
<div class="file-language-links">
<div><p class="language-meta" translate="no">English (EN)<span> (1.56 MB - PDF)</span></p>
<div class="dates-metadata"><small class="metadata-row first-published"><strong class="label">First published: </strong><span class="value"><time datetime="2012-11-22T10:00:00Z">22/11/2012</time></span></small>
<small class="metadata-row last-updated"><strong class="label">Last updated: </strong><span class="value"><time datetime="2012-11-22T11:00:00Z">22/11/2012</time></span></small></div></div>
<a href="/en/documents/assessment-report/adcetris-epar-public-assessment-report_en.pdf">View</a>
</div>
<div class="file-language-links">
<div><p class="language-meta" translate="no">German (DE)<span> (1.2 MB - PDF)</span></p>
<a href="/de/documents/assessment-report/adcetris-epar-public-assessment-report_de.pdf">View</a>
</div>
"""


def _build_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(8):
        ws.append([None] * 39)
    header = [f"col_{i}" for i in range(39)]
    header[1] = "Name of medicine"
    header[2] = "EMA product number"
    header[3] = "Medicine status"
    header[7] = "Active substance"
    header[8] = "Therapeutic area (MeSH)"
    header[25] = "Marketing authorisation developer / applicant / holder"
    header[26] = "European Commission decision date"
    header[31] = "Marketing authorisation date"
    header[33] = "Withdrawal / expiry / revocation / lapse of marketing authorisation date"
    header[37] = "Last updated date"
    header[38] = "Medicine URL"
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _medicine_row(name, product_number, active_substance, last_updated="01/01/2020", url=None):
    row = [None] * 39
    row[1] = name
    row[2] = product_number
    row[3] = "Authorised"
    row[7] = active_substance
    row[8] = "Oncology"
    row[25] = "TEST HOLDER"
    row[26] = "01/01/2020"
    row[31] = "01/02/2020"
    row[37] = last_updated
    row[38] = url or f"https://www.ema.europa.eu/en/medicines/human/EPAR/{name.lower()}"
    return row


def test_parse_medicines_xlsx_extracts_medicines():
    xlsx = _build_xlsx([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")])
    medicines = parse_medicines_xlsx(xlsx)
    assert len(medicines) == 1
    m = medicines[0]
    assert m.product_number == "EMEA/H/C/002455"
    assert m.name == "Adcetris"
    assert m.active_substance == "brentuximab vedotin"
    assert m.authorisation_date == "2020-02-01"
    assert m.last_updated_date == "2020-01-01"
    assert m.epar_url == "https://www.ema.europa.eu/en/medicines/human/EPAR/adcetris"
    assert m.raw_row["Name of medicine"] == "Adcetris"


def test_parse_medicines_xlsx_skips_rows_with_no_product_number():
    row = _medicine_row("X", "", "vedotin")
    row[2] = None
    xlsx = _build_xlsx([row])
    assert parse_medicines_xlsx(xlsx) == []


def test_normalize_ema_date():
    assert normalize_ema_date("22/11/2012") == "2012-11-22"
    assert normalize_ema_date(None) is None
    assert normalize_ema_date("") is None
    assert normalize_ema_date("not-a-date") is None


def test_is_adc_candidate_matches_active_substance():
    m = ParsedMedicine(
        product_number="X", name="Adcetris", status=None, active_substance="brentuximab vedotin",
        therapeutic_area=None, marketing_authorisation_holder=None, decision_date=None,
        authorisation_date=None, withdrawal_date=None, last_updated_date=None, epar_url=None, raw_row={},
    )
    assert is_adc_candidate(m, ["vedotin", "emtansine"]) is True
    assert is_adc_candidate(m, ["emtansine"]) is False


def test_parse_epar_documents_only_english():
    docs = parse_epar_documents(EPAR_HTML_FRAGMENT)
    assert len(docs) == 1
    d = docs[0]
    assert d.filename == "adcetris-epar-public-assessment-report_en.pdf"
    assert d.doc_type == "assessment-report"
    assert d.last_updated == "2012-11-22"
    assert d.url == "https://www.ema.europa.eu/en/documents/assessment-report/adcetris-epar-public-assessment-report_en.pdf"


def test_parse_epar_documents_no_matches_returns_empty():
    assert parse_epar_documents("<html>no documents here</html>") == []


def test_within_date_range_no_bounds_keeps_everything():
    assert within_date_range(None, None, None) is True


def test_within_date_range_since_and_until():
    assert within_date_range("2022-06-01", "2022-01-01", "2022-12-31") is True
    assert within_date_range("2021-12-31", "2022-01-01", "2022-12-31") is False


def test_within_date_range_missing_date_excluded_once_a_range_is_requested():
    assert within_date_range(None, "2022-01-01", None) is False
