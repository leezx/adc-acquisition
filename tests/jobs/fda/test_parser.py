from jobs.fda.parser import normalize_fda_date, parse_application, parse_submissions, within_date_range

# Trimmed from a real drugsfda.json record (BLA125388 / Adcetris),
# fetched live on 2026-08-11.
DRUGSFDA_RECORD = {
    "application_number": "BLA125388",
    "sponsor_name": "SEATTLE GENETICS",
    "products": [
        {
            "product_number": "001",
            "brand_name": "ADCETRIS",
            "active_ingredients": [{"name": "BRENTUXIMAB VEDOTIN", "strength": "50MG/VIAL"}],
            "dosage_form": "INJECTABLE",
        }
    ],
    "submissions": [
        {
            "submission_type": "ORIG",
            "submission_number": "1",
            "submission_status": "AP",
            "submission_status_date": "20110819",
            "submission_class_code": "TYPE 1",
            "submission_class_code_description": "Type 1 - New Molecular Entity",
            "application_docs": [
                {"id": "39948", "url": "http://www.accessdata.fda.gov/.../lbl.pdf", "date": "20110819", "type": "Label"},
                {"id": "31951", "url": "http://www.accessdata.fda.gov/.../ltr.pdf", "date": "20110819", "type": "Letter"},
            ],
        },
        {
            "submission_type": "SUPPL",
            "submission_number": "6",
            "submission_status": "AP",
            "submission_status_date": "20110819",
            "submission_class_code": "EFFICACY",
            "submission_class_code_description": "Efficacy",
        },
    ],
}


def test_parse_submissions_extracts_all_submissions():
    submissions = parse_submissions(DRUGSFDA_RECORD)
    assert len(submissions) == 2
    s0 = submissions[0]
    assert s0.application_number == "BLA125388"
    assert s0.submission_type == "ORIG"
    assert s0.submission_number == "1"
    assert s0.submission_status_date == "2011-08-19"
    assert s0.submission_key == "BLA125388_ORIG1"
    assert len(s0.docs) == 2
    assert s0.docs[0].doc_id == "39948"
    assert s0.docs[0].doc_type == "Label"


def test_submission_key_distinguishes_orig_from_suppl_with_same_number():
    submissions = parse_submissions(
        {
            "application_number": "BLA1",
            "submissions": [
                {"submission_type": "ORIG", "submission_number": "1"},
                {"submission_type": "SUPPL", "submission_number": "1"},
            ],
        }
    )
    keys = {s.submission_key for s in submissions}
    assert keys == {"BLA1_ORIG1", "BLA1_SUPPL1"}


def test_submission_with_no_application_docs_has_empty_docs_list():
    submissions = parse_submissions(DRUGSFDA_RECORD)
    assert submissions[1].docs == []


def test_missing_application_number_returns_empty_list():
    assert parse_submissions({"submissions": [{"submission_type": "ORIG"}]}) == []


def test_doc_missing_id_or_url_is_skipped():
    submissions = parse_submissions(
        {
            "application_number": "BLA1",
            "submissions": [
                {
                    "submission_type": "ORIG",
                    "submission_number": "1",
                    "application_docs": [
                        {"id": "1", "url": "http://x/1.pdf", "type": "Label"},
                        {"id": "2", "type": "Letter"},  # missing url
                        {"url": "http://x/3.pdf", "type": "Review"},  # missing id
                    ],
                }
            ],
        }
    )
    assert [d.doc_id for d in submissions[0].docs] == ["1"]


def test_normalize_fda_date():
    assert normalize_fda_date("20230614") == "2023-06-14"
    assert normalize_fda_date(None) is None
    assert normalize_fda_date("") is None
    assert normalize_fda_date("not-a-date") is None


def test_within_date_range_no_bounds_keeps_everything():
    assert within_date_range(None, None, None) is True
    assert within_date_range("2020-01-01", None, None) is True


def test_within_date_range_since_and_until():
    assert within_date_range("2022-06-01", "2022-01-01", "2022-12-31") is True
    assert within_date_range("2021-12-31", "2022-01-01", "2022-12-31") is False
    assert within_date_range("2023-01-01", "2022-01-01", "2022-12-31") is False


def test_within_date_range_missing_date_excluded_once_a_range_is_requested():
    assert within_date_range(None, "2022-01-01", None) is False


def test_parse_application_extracts_product_identity():
    app = parse_application(DRUGSFDA_RECORD)
    assert app.application_number == "BLA125388"
    assert app.sponsor_name == "SEATTLE GENETICS"
    assert app.brand_names == ["ADCETRIS"]
    assert app.active_ingredients == ["BRENTUXIMAB VEDOTIN"]
    assert app.product_numbers == ["001"]
    assert app.earliest_submission_date == "2011-08-19"


def test_parse_application_dedupes_across_multiple_products():
    record = {
        "application_number": "BLA1",
        "sponsor_name": "X",
        "products": [
            {"product_number": "001", "brand_name": "DRUG-A", "active_ingredients": [{"name": "INGR-1"}]},
            {"product_number": "002", "brand_name": "DRUG-A", "active_ingredients": [{"name": "INGR-1"}]},
        ],
        "submissions": [],
    }
    app = parse_application(record)
    assert app.brand_names == ["DRUG-A"]
    assert app.active_ingredients == ["INGR-1"]
    assert app.product_numbers == ["001", "002"]


def test_parse_application_missing_application_number_returns_none():
    assert parse_application({"submissions": []}) is None


def test_parse_application_handles_no_products_or_submissions():
    app = parse_application({"application_number": "BLA1"})
    assert app.brand_names == []
    assert app.active_ingredients == []
    assert app.earliest_submission_date is None
