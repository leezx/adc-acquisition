"""Normalize SEC EDGAR submissions-API filing lists.

The submissions API returns filings as parallel arrays (one list per field,
all the same length) rather than a list of per-filing objects — this module
just zips them into normal dicts. Defensive: a company can have a filing
missing an optional field (e.g. no `items` for a non-8-K), and one missing
field must never crash the batch.

Prompt.md section 13's relevant document types: 10-K, 10-Q, 8-K, S-1, 20-F,
6-K, plus their amendments (a "/A" suffix, e.g. 10-K/A) — SEC EDGAR treats
an amendment as its own filing with its own accession number, not a patch
to the original.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RELEVANT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "S-1", "S-1/A", "20-F", "20-F/A", "6-K", "6-K/A"}


@dataclass
class ParsedFiling:
    accession_number: str
    form: str
    filing_date: str | None
    report_date: str | None
    primary_document: str | None
    item_codes: list[str]
    file_number: str | None
    film_number: str | None


def filings_from_recent_block(recent: dict[str, list[Any]]) -> list[ParsedFiling]:
    """`recent` is filings["recent"] (or a page from filings["files"]) from
    the submissions API — a dict of equal-length parallel arrays."""
    accession_numbers = recent.get("accessionNumber") or []
    count = len(accession_numbers)
    forms = recent.get("form") or [None] * count
    filing_dates = recent.get("filingDate") or [None] * count
    report_dates = recent.get("reportDate") or [None] * count
    primary_documents = recent.get("primaryDocument") or [None] * count
    items = recent.get("items") or [None] * count
    file_numbers = recent.get("fileNumber") or [None] * count
    film_numbers = recent.get("filmNumber") or [None] * count

    filings = []
    for i in range(count):
        accession_number = accession_numbers[i]
        if not accession_number:
            continue
        raw_items = items[i] if i < len(items) else None
        item_codes = [c.strip() for c in raw_items.split(",") if c.strip()] if raw_items else []
        filings.append(
            ParsedFiling(
                accession_number=accession_number,
                form=forms[i] if i < len(forms) else None,
                filing_date=filing_dates[i] if i < len(filing_dates) else None,
                report_date=report_dates[i] if i < len(report_dates) else None,
                primary_document=primary_documents[i] if i < len(primary_documents) else None,
                item_codes=item_codes,
                file_number=file_numbers[i] if i < len(file_numbers) else None,
                film_number=film_numbers[i] if i < len(film_numbers) else None,
            )
        )
    return filings


def filter_relevant_forms(filings: list[ParsedFiling]) -> list[ParsedFiling]:
    return [f for f in filings if f.form in RELEVANT_FORMS]
