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


def _doi_suffix_contains(message: dict, value: str) -> bool:
    doi = message.get("DOI") or ""
    suffix = doi.split("/", 1)[1] if "/" in doi else doi
    return value.lower() in suffix.lower()


def _matches_volume_issue_pairs(message: dict, pairs: list[str]) -> bool:
    """`pairs` is an explicit allowlist of "volume:issue" strings.

    Reviewer-flagged (round-1): a generic "issue starts with S" check is
    NOT sufficient for HemaSphere -- it publishes MULTIPLE societies'
    S-numbered supplements in the same congress year (e.g. 2024: S1=EHA2024
    Hybrid Congress, S2=International Symposium on Hodgkin Lymphoma,
    S3/S4=Annual Sickle Cell & Thalassaemia Conference; 2022: S3=EHA2022
    Hybrid Congress, with S1/S2/S4/S5 belonging to four OTHER societies).
    This checks the record's own (volume, issue) pair against an explicit,
    live-verified allowlist instead -- see
    configs/conference_crossref_search.yaml's EHA entry for the sourced
    year->volume->issue mapping. A (volume, issue) pair not in the
    allowlist fails closed (never guessed)."""
    volume = str(message.get("volume") or "")
    issue = str(message.get("issue") or "")
    return f"{volume}:{issue}" in set(pairs or [])


_SIGNATURE_FUNCS = {
    "no_issue_and_s_page": lambda message, value: _no_issue_and_s_page(message),
    "issue_contains_supplement": lambda message, value: _issue_contains_supplement(message),
    "doi_suffix_contains": lambda message, value: _doi_suffix_contains(message, value),
    "volume_issue_map": lambda message, value: _matches_volume_issue_pairs(message, value),
}


def matches_signature(message: dict, signature_type: str, signature_value: str | None) -> bool:
    try:
        func = _SIGNATURE_FUNCS[signature_type]
    except KeyError:
        raise ValueError(f"unknown signature_type: {signature_type!r}") from None
    return func(message, signature_value)
