"""Normalize one Crossref `/works/{doi}` response (the `message` object).

Defensive throughout: a work record can legitimately be missing almost any
field (books have no container-title, some records have no author list,
etc.), and one missing field must never crash the batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedWork:
    doi: str
    title: str | None
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    container_title: str | None = None
    work_type: str | None = None
    published_date: str | None = None
    license_url: str | None = None
    references: list[str] = field(default_factory=list)
    url: str | None = None
    abstract: str | None = None


def _date_from_parts(date_obj: dict | None) -> str | None:
    if not date_obj:
        return None
    date_parts = date_obj.get("date-parts")
    if not date_parts or not date_parts[0] or date_parts[0][0] is None:
        return None
    year, *rest = date_parts[0]
    components = [str(year)] + [f"{p:02d}" for p in rest if p is not None]
    return "-".join(components)


def _best_published_date(message: dict[str, Any]) -> str | None:
    for key in ("published", "published-print", "published-online", "issued"):
        date_str = _date_from_parts(message.get(key))
        if date_str:
            return date_str
    return None


def _author_names(authors: list[dict] | None) -> list[str]:
    if not authors:
        return []
    names = []
    for a in authors:
        if a.get("name"):
            names.append(a["name"])
            continue
        given, family = a.get("given"), a.get("family")
        if given and family:
            names.append(f"{given} {family}")
        elif family:
            names.append(family)
        elif given:
            names.append(given)
    return names


def _reference_strings(references: list[dict] | None) -> list[str]:
    if not references:
        return []
    result = []
    for ref in references:
        text = ref.get("DOI") or ref.get("unstructured") or ref.get("article-title")
        if text:
            result.append(text)
    return result


def parse_work(message: dict[str, Any] | None) -> ParsedWork | None:
    if not message or not message.get("DOI"):
        return None

    titles = message.get("title") or []
    container_titles = message.get("container-title") or []
    licenses = message.get("license") or []

    return ParsedWork(
        doi=message["DOI"],
        title=titles[0] if titles else None,
        authors=_author_names(message.get("author")),
        publisher=message.get("publisher"),
        container_title=container_titles[0] if container_titles else None,
        work_type=message.get("type"),
        published_date=_best_published_date(message),
        license_url=licenses[0].get("URL") if licenses else None,
        references=_reference_strings(message.get("reference")),
        url=message.get("URL"),
        abstract=message.get("abstract"),
    )
