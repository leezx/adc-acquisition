"""Normalize openFDA /drug/drugsfda.json records.

One Drugs@FDA record (keyed by application_number) has a `submissions`
array — each entry is a distinct regulatory milestone (original approval,
a labeling supplement, an efficacy supplement, ...) identified by
(submission_type, submission_number), with its own status/date and,
optionally, an `application_docs` array of actual downloadable documents
(labels, approval letters, review documents, ...). Defensive throughout:
a submission or doc missing an optional field must never crash the batch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApplicationDoc:
    doc_id: str
    doc_type: str | None
    url: str | None
    doc_date: str | None


@dataclass
class ParsedSubmission:
    application_number: str
    submission_type: str | None
    submission_number: str | None
    submission_status: str | None
    submission_status_date: str | None  # normalized YYYY-MM-DD
    submission_class_code: str | None
    submission_class_code_description: str | None
    docs: list[ApplicationDoc] = field(default_factory=list)

    @property
    def submission_key(self) -> str:
        """f"{application_number}_{TYPE}{NUMBER}", e.g. "BLA125388_ORIG1" —
        unique within an application (submission_number alone is not:
        ORIG-1 and SUPPL-1 can coexist)."""
        return f"{self.application_number}_{self.submission_type or 'UNKNOWN'}{self.submission_number or ''}"


_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def normalize_fda_date(raw: str | None) -> str | None:
    """openFDA dates are YYYYMMDD strings (e.g. "20230614"); the universal
    manifest contract wants YYYY-MM-DD."""
    if not raw:
        return None
    m = _DATE_RE.match(raw)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def parse_drugsfda_record(record: dict[str, Any]) -> list[ParsedSubmission]:
    """One drugsfda `results[]` entry -> one ParsedSubmission per
    submissions[] entry (application-level fields like sponsor_name are
    not currently modeled per-submission; add if a future job needs them)."""
    application_number = record.get("application_number")
    if not application_number:
        return []
    submissions = []
    for sub in record.get("submissions") or []:
        docs = [
            ApplicationDoc(
                doc_id=doc.get("id"),
                doc_type=doc.get("type"),
                url=doc.get("url"),
                doc_date=normalize_fda_date(doc.get("date")),
            )
            for doc in (sub.get("application_docs") or [])
            if doc.get("id") and doc.get("url")
        ]
        submissions.append(
            ParsedSubmission(
                application_number=application_number,
                submission_type=sub.get("submission_type"),
                submission_number=sub.get("submission_number"),
                submission_status=sub.get("submission_status"),
                submission_status_date=normalize_fda_date(sub.get("submission_status_date")),
                submission_class_code=sub.get("submission_class_code"),
                submission_class_code_description=sub.get("submission_class_code_description"),
                docs=docs,
            )
        )
    return submissions


def within_date_range(date_str: str | None, since: str | None, until: str | None) -> bool:
    """Lexicographic YYYY-MM-DD comparison. A submission with no status
    date can't be verified against a requested range, so it's excluded
    once a range is actually requested (rather than silently assumed
    in-range) — same convention as jobs/sec/parser.py."""
    if not since and not until:
        return True
    if not date_str:
        return False
    if since and date_str < since:
        return False
    if until and date_str > until:
        return False
    return True
