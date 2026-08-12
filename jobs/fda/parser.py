"""Normalize openFDA /drug/drugsfda.json records.

One Drugs@FDA record (keyed by application_number) has three parts
(https://open.fda.gov/apis/drug/drugsfda/understanding-the-api-results/):
application-level identity (sponsor), a `products` array (brand name,
active ingredients, dosage form per marketed product number), and a
`submissions` array — each entry a distinct regulatory milestone
(original approval, a labeling supplement, an efficacy supplement, ...)
identified by (submission_type, submission_number), with its own
status/date and, optionally, an `application_docs` array of actual
downloadable documents (labels, approval letters, review documents, ...).
Defensive throughout: a submission, product, or doc missing an optional
field must never crash the batch.
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


@dataclass
class ParsedApplication:
    """The application/product-level identity Prompt.md section 14
    explicitly lists as key identifiers (product name, active
    ingredient) — separate from any one submission, since these describe
    the marketed product(s) under this application as a whole, not a
    single regulatory milestone."""

    application_number: str
    sponsor_name: str | None
    brand_names: list[str]
    active_ingredients: list[str]
    product_numbers: list[str]
    earliest_submission_date: str | None  # normalized YYYY-MM-DD, min across all submissions


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


def parse_application(record: dict[str, Any]) -> ParsedApplication | None:
    """The application/product-level view of one drugsfda `results[]`
    entry — deduplicated brand names / active ingredients across every
    product_number under this application, since Prompt.md's key
    identifiers are about the product(s), not a specific submission."""
    application_number = record.get("application_number")
    if not application_number:
        return None
    brand_names: list[str] = []
    active_ingredients: list[str] = []
    product_numbers: list[str] = []
    for product in record.get("products") or []:
        product_number = product.get("product_number")
        if product_number and product_number not in product_numbers:
            product_numbers.append(product_number)
        brand_name = product.get("brand_name")
        if brand_name and brand_name not in brand_names:
            brand_names.append(brand_name)
        for ingredient in product.get("active_ingredients") or []:
            name = ingredient.get("name")
            if name and name not in active_ingredients:
                active_ingredients.append(name)

    submission_dates = [
        normalize_fda_date(sub.get("submission_status_date")) for sub in record.get("submissions") or []
    ]
    submission_dates = [d for d in submission_dates if d]

    return ParsedApplication(
        application_number=application_number,
        sponsor_name=record.get("sponsor_name"),
        brand_names=brand_names,
        active_ingredients=active_ingredients,
        product_numbers=product_numbers,
        earliest_submission_date=min(submission_dates) if submission_dates else None,
    )


def parse_submissions(record: dict[str, Any]) -> list[ParsedSubmission]:
    """One drugsfda `results[]` entry -> one ParsedSubmission per
    submissions[] entry."""
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
