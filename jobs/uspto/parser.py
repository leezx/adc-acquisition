"""Parsing for USPTO ODP Patent File Wrapper records (see jobs/uspto/client.py
for the live-verified endpoint shapes)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedApplication:
    application_number: str
    title: str | None
    filing_date: str | None
    publication_date: str | None
    publication_number: str | None
    status: str | None
    applicants: list[str] = field(default_factory=list)
    inventors: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    cpc_classes: list[str] = field(default_factory=list)
    foreign_priority: list[dict] = field(default_factory=list)


def parse_application(raw: dict) -> ParsedApplication:
    meta = raw.get("applicationMetaData") or {}

    applicants = [a["applicantNameText"] for a in meta.get("applicantBag") or [] if a.get("applicantNameText")]
    inventors = [i["inventorNameText"] for i in meta.get("inventorBag") or [] if i.get("inventorNameText")]

    assignees = []
    seen = set()
    for assignment in raw.get("assignmentBag") or []:
        for assignee in assignment.get("assigneeBag") or []:
            name = assignee.get("assigneeNameText")
            if name and name not in seen:
                seen.add(name)
                assignees.append(name)

    foreign_priority = [
        {
            "application_number": p.get("applicationNumberText"),
            "filing_date": p.get("filingDate"),
            "ip_office_name": p.get("ipOfficeName"),
        }
        for p in raw.get("foreignPriorityBag") or []
    ]

    return ParsedApplication(
        application_number=raw.get("applicationNumberText"),
        title=meta.get("inventionTitle"),
        filing_date=meta.get("filingDate") or meta.get("effectiveFilingDate"),
        publication_date=meta.get("earliestPublicationDate"),
        publication_number=meta.get("earliestPublicationNumber"),
        status=meta.get("applicationStatusDescriptionText"),
        applicants=applicants,
        inventors=inventors,
        assignees=assignees,
        cpc_classes=list(meta.get("cpcClassificationBag") or []),
        foreign_priority=foreign_priority,
    )


@dataclass
class ParsedDocument:
    document_identifier: str
    application_number: str
    document_code: str
    document_description: str | None
    official_date: str | None
    download_url: str | None
    mime_type: str | None


def parse_documents(application_number: str, document_bag: list[dict]) -> list[ParsedDocument]:
    """Only Specification documents (documentCode == "SPEC") are kept —
    the actual filed claims/full-text document per Prompt.md's "claims/
    full text where legally and technically available" ask. Other file
    wrapper document types (filing receipts, fee worksheets, notices,
    office actions, ...) are a separate, not-yet-acquired concern (see
    job.py's known-gaps documentation) — this is a deliberate, source-
    typed filter (the document's own `documentCode` field), not a
    negative "everything that isn't X" filter."""
    parsed = []
    for doc in document_bag:
        if doc.get("documentCode") != "SPEC":
            continue
        download_options = doc.get("downloadOptionBag") or []
        pdf_option = next((o for o in download_options if o.get("mimeTypeIdentifier") == "PDF"), None)
        chosen = pdf_option or (download_options[0] if download_options else None)
        parsed.append(
            ParsedDocument(
                document_identifier=doc.get("documentIdentifier"),
                application_number=application_number,
                document_code=doc.get("documentCode"),
                document_description=doc.get("documentCodeDescriptionText"),
                official_date=doc.get("officialDate"),
                download_url=chosen.get("downloadUrl") if chosen else None,
                mime_type=chosen.get("mimeTypeIdentifier") if chosen else None,
            )
        )
    return parsed
