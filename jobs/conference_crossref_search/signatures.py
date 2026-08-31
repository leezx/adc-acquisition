"""Deterministic, locally-applied conference-attribution signatures.

Container-title/ISSN match alone is NOT conference attribution -- see
configs/conference_crossref_search.yaml's own file header for the live
evidence (Cancer Research alone carries AACR Annual Meeting, SABCS, and
other congresses' abstracts side by side, plus regular research articles).
Each function here takes one Crossref `/works?` item (a `message` dict) and
returns True iff it structurally matches THIS congress's own supplement
publication shape -- independent of any ADC-relevance question, which is a
separate, later filter.

Every signature was live-verified against real Crossref data on
2026-08-31; see each conference's own `purpose` field in
configs/conference_crossref_search.yaml for the specific DOIs inspected.
"""

from __future__ import annotations


def _no_issue_and_s_page(message: dict) -> bool:
    if message.get("issue"):
        return False
    page = message.get("page") or ""
    return page.startswith("S")


def _issue_contains_supplement(message: dict) -> bool:
    issue = message.get("issue") or ""
    return "supplement" in issue.lower()


def _issue_starts_with_s(message: dict) -> bool:
    issue = message.get("issue") or ""
    return issue.upper().startswith("S")


def _doi_suffix_contains(message: dict, value: str) -> bool:
    doi = message.get("DOI") or ""
    suffix = doi.split("/", 1)[1] if "/" in doi else doi
    return value.lower() in suffix.lower()


_SIGNATURE_FUNCS = {
    "no_issue_and_s_page": lambda message, value: _no_issue_and_s_page(message),
    "issue_contains_supplement": lambda message, value: _issue_contains_supplement(message),
    "issue_starts_with_s": lambda message, value: _issue_starts_with_s(message),
    "doi_suffix_contains": lambda message, value: _doi_suffix_contains(message, value),
}


def matches_signature(message: dict, signature_type: str, signature_value: str | None) -> bool:
    try:
        func = _SIGNATURE_FUNCS[signature_type]
    except KeyError:
        raise ValueError(f"unknown signature_type: {signature_type!r}") from None
    return func(message, signature_value)
