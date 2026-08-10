"""Normalize one Europe PMC `resultType=core` search-result record.

Unlike PubMed's XML, Europe PMC's core result is already structured JSON, so
there's no XML tree to walk — just defensive dict lookups, since a record
missing an optional field (no DOI, no journal, preprint with no PMID) must
never crash the batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ParsedRecord:
    epmc_source: str
    epmc_id: str
    pmid: str | None
    pmcid: str | None
    doi: str | None
    title: str | None
    abstract: str | None
    journal: str | None
    publication_date: str | None
    is_open_access: bool
    in_pmc: bool
    license: str | None


def _publication_date(result: dict[str, Any]) -> str | None:
    first_pub_date = result.get("firstPublicationDate")
    if first_pub_date:
        return first_pub_date
    journal_info = result.get("journalInfo") or {}
    print_date = journal_info.get("printPublicationDate")
    if print_date:
        return print_date
    year = result.get("pubYear")
    return str(year) if year else None


def parse_search_result(result: dict[str, Any]) -> ParsedRecord | None:
    """Returns None (skip, don't fabricate an identifier) if the record has
    neither `source` nor `id` — Europe PMC's own compound primary key."""
    epmc_source = result.get("source")
    epmc_id = result.get("id")
    if not epmc_source or not epmc_id:
        return None

    journal_info = result.get("journalInfo") or {}
    journal = (journal_info.get("journal") or {}).get("title")

    return ParsedRecord(
        epmc_source=epmc_source,
        epmc_id=str(epmc_id),
        pmid=result.get("pmid"),
        pmcid=result.get("pmcid"),
        doi=result.get("doi"),
        title=result.get("title"),
        abstract=result.get("abstractText"),
        journal=journal,
        publication_date=_publication_date(result),
        is_open_access=result.get("isOpenAccess") == "Y",
        in_pmc=result.get("inPMC") == "Y",
        license=result.get("license"),
    )
