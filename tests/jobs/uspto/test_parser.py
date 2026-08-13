from jobs.uspto.parser import parse_application, parse_documents

RAW_APPLICATION = {
    "applicationNumberText": "19640639",
    "applicationMetaData": {
        "inventionTitle": "ANTIBODY DRUG CONJUGATE",
        "filingDate": "2026-04-07",
        "earliestPublicationDate": "2026-07-30",
        "earliestPublicationNumber": "US20260216364A1",
        "applicationStatusDescriptionText": "Docketed New Case",
        "applicantBag": [{"applicantNameText": "Acme Pharma"}],
        "inventorBag": [{"inventorNameText": "Jane Doe"}],
        "cpcClassificationBag": ["A61K 47/54"],
    },
    "assignmentBag": [
        {"assigneeBag": [{"assigneeNameText": "Acme Pharma"}]},
        {"assigneeBag": [{"assigneeNameText": "Acme Pharma"}, {"assigneeNameText": "Subsidiary Co"}]},
    ],
    "foreignPriorityBag": [
        {"applicationNumberText": "202010814877.X", "filingDate": "2020-08-13", "ipOfficeName": "CHINA"},
    ],
}

DOCUMENT_BAG = [
    {
        "documentIdentifier": "DOC1",
        "documentCode": "SPEC",
        "documentCodeDescriptionText": "Specification",
        "officialDate": "2026-04-20T13:40:59.000-0400",
        "downloadOptionBag": [
            {"mimeTypeIdentifier": "PDF", "downloadUrl": "https://x/doc1.pdf"},
            {"mimeTypeIdentifier": "XML", "downloadUrl": "https://x/doc1.xml"},
        ],
    },
    {
        "documentIdentifier": "DOC2",
        "documentCode": "NTC.PUB",
        "documentCodeDescriptionText": "Notice of Publication",
        "officialDate": "2026-07-30T00:00:00.000-0400",
        "downloadOptionBag": [{"mimeTypeIdentifier": "PDF", "downloadUrl": "https://x/doc2.pdf"}],
    },
]


def test_parse_application_extracts_all_fields():
    p = parse_application(RAW_APPLICATION)
    assert p.application_number == "19640639"
    assert p.title == "ANTIBODY DRUG CONJUGATE"
    assert p.filing_date == "2026-04-07"
    assert p.publication_date == "2026-07-30"
    assert p.publication_number == "US20260216364A1"
    assert p.status == "Docketed New Case"
    assert p.applicants == ["Acme Pharma"]
    assert p.inventors == ["Jane Doe"]
    assert p.assignees == ["Acme Pharma", "Subsidiary Co"]  # deduped across assignment records
    assert p.cpc_classes == ["A61K 47/54"]
    assert p.foreign_priority == [{"application_number": "202010814877.X", "filing_date": "2020-08-13", "ip_office_name": "CHINA"}]


def test_parse_documents_keeps_only_spec_type():
    docs = parse_documents("19640639", DOCUMENT_BAG)
    assert len(docs) == 1
    assert docs[0].document_identifier == "DOC1"
    assert docs[0].document_code == "SPEC"
    assert docs[0].download_url == "https://x/doc1.pdf"  # prefers PDF over XML
    assert docs[0].mime_type == "PDF"


def test_parse_documents_empty_bag_returns_empty_list():
    assert parse_documents("19640639", []) == []
