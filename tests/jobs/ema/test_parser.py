import json

from jobs.ema.parser import (
    ParsedMedicine,
    is_adc_candidate,
    normalize_ema_date,
    parse_epar_documents_json,
    parse_medicines_json,
    within_date_range,
)


def _medicines_json(rows):
    return json.dumps({"meta": {"total_records": len(rows)}, "data": rows}).encode("utf-8")


def _documents_json(rows):
    return json.dumps({"meta": {"total_records": len(rows)}, "data": rows}).encode("utf-8")


def _medicine_row(name, product_number, active_substance, last_updated="12/08/2026"):
    return {
        "name_of_medicine": name,
        "ema_product_number": product_number,
        "medicine_status": "Authorised",
        "active_substance": active_substance,
        "therapeutic_area_mesh": "Oncology",
        "marketing_authorisation_developer_applicant_holder": "TEST HOLDER",
        "european_commission_decision_date": "01/01/2020",
        "marketing_authorisation_date": "01/02/2020",
        "withdrawal_expiry_revocation_lapse_of_marketing_authorisation_date": "",
        "last_updated_date": last_updated,
        "medicine_url": f"https://www.ema.europa.eu/en/medicines/human/EPAR/{name.lower()}",
    }


def _document_row(doc_id, product_number, doc_type, last_updated="2020-01-01T00:00:00Z", url=None):
    return {
        "id": doc_id,
        "ema_product_number": product_number,
        "type": doc_type,
        "first_published_date": last_updated,
        "last_updated_date": last_updated,
        "document_url": url or f"https://www.ema.europa.eu/en/documents/{doc_type}/{doc_id}_en.pdf",
    }


def test_parse_medicines_json_extracts_medicines():
    xs = _medicines_json([_medicine_row("Adcetris", "EMEA/H/C/002455", "brentuximab vedotin")])
    medicines = parse_medicines_json(xs)
    assert len(medicines) == 1
    m = medicines[0]
    assert m.product_number == "EMEA/H/C/002455"
    assert m.name == "Adcetris"
    assert m.active_substance == "brentuximab vedotin"
    assert m.authorisation_date == "2020-02-01"
    assert m.last_updated_date == "2026-08-12"
    assert m.raw_row["name_of_medicine"] == "Adcetris"


def test_parse_medicines_json_skips_rows_with_no_product_number():
    row = _medicine_row("X", "", "vedotin")
    row["ema_product_number"] = None
    xs = _medicines_json([row])
    assert parse_medicines_json(xs) == []


def test_normalize_ema_date_handles_both_formats():
    assert normalize_ema_date("22/11/2012") == "2012-11-22"
    assert normalize_ema_date("2012-11-22T10:00:00Z") == "2012-11-22"
    assert normalize_ema_date(None) is None
    assert normalize_ema_date("not-a-date") is None


def test_is_adc_candidate_matches_active_substance():
    m = ParsedMedicine(
        product_number="X", name="Adcetris", status=None, active_substance="brentuximab vedotin",
        therapeutic_area=None, marketing_authorisation_holder=None, decision_date=None,
        authorisation_date=None, withdrawal_date=None, last_updated_date=None, epar_url=None, raw_row={},
    )
    assert is_adc_candidate(m, ["vedotin", "emtansine"]) is True
    assert is_adc_candidate(m, ["emtansine"]) is False


def test_parse_epar_documents_json_extracts_documents():
    xs = _documents_json([_document_row("123", "EMEA/H/C/002455", "product-information")])
    docs = parse_epar_documents_json(xs)
    assert len(docs) == 1
    d = docs[0]
    assert d.doc_id == "123"
    assert d.product_number == "EMEA/H/C/002455"
    assert d.doc_type == "product-information"
    assert d.last_updated == "2020-01-01"


def test_parse_epar_documents_json_skips_incomplete_rows():
    rows = [
        _document_row("1", "EMEA/H/C/1", "label"),
        {**_document_row("2", "EMEA/H/C/1", "label"), "document_url": None},
        {**_document_row("3", "EMEA/H/C/1", "label"), "ema_product_number": None},
    ]
    docs = parse_epar_documents_json(_documents_json(rows))
    assert [d.doc_id for d in docs] == ["1"]


def test_within_date_range_no_bounds_keeps_everything():
    assert within_date_range(None, None, None) is True


def test_within_date_range_since_and_until():
    assert within_date_range("2022-06-01", "2022-01-01", "2022-12-31") is True
    assert within_date_range("2021-12-31", "2022-01-01", "2022-12-31") is False


def test_within_date_range_missing_date_excluded_once_a_range_is_requested():
    assert within_date_range(None, "2022-01-01", None) is False
