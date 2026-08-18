"""Per-source query generation for known-ADC asset expansion (Prompt.md
section 19, Job 15): "<ADC name>", "<ADC alias>", "<ADC name>" patent/
trial/activity/cytotoxicity/xenograft/IC50.

Each source gets Prompt.md's templates translated into ITS OWN real query
syntax (same translation this repo already does for the broad discovery
query family: configs/pubmed_queries.yaml uses [tiab], europe_pmc_queries.yaml
uses TITLE:/ABSTRACT:, wipo_queries.yaml/epo_queries.yaml use OPS CQL,
uspto_queries.yaml uses free-text phrases/AND) -- never passed through
verbatim as English text.

SUFFIX TEMPLATES (patent/trial/activity/cytotoxicity/xenograft/IC50) are
generated for PubMed, Europe PMC, AND USPTO. Disclosed, not silently
narrowed: USPTO's own free-text `q=` search (jobs/uspto/client.py, verified
live) covers the FULL specification content of an application, not just
title/abstract, so experimental-data language like "xenograft"/"IC50"
genuinely can appear there. WIPO/EPO's OPS biblio search is restricted to
title/abstract only -- that full-specification text is what Job 13 already
acquires separately for these same publications -- so appending those
suffix words to a WIPO/EPO query would search for text that structurally
isn't there. WIPO/EPO instead get the bare "<name>"/"<alias>" identifier
templates only (every distinct identifier KnownADCAsset.identifiers()
returns, not canonical name alone); USPTO gets BOTH the bare identifiers
AND the 6 suffixes.

ClinicalTrials.gov (Job 03) is handled entirely through its existing
--intervention lookup (jobs/clinicaltrials/job.py), one call per
identifier -- its own corpus already IS trials, so the "trial" suffix
would be redundant, and "patent"/"activity"/"cytotoxicity"/"xenograft"/
"IC50" don't map onto CT.gov's query.intr field at all.

Crossref (Job 04) is NOT a target here: its own module docstring already
established (verified live) that free-text search is relevance-ranked and
unusable for precise discovery -- Job 04 exists for DOI-exact
reconciliation, not name search, and this job doesn't change that.

QUERY_ID STABILITY (round-1 fix): every query_id is now derived from a
hash of its OWN query_text (`_query_id()`), not just from (asset_id,
identifier-or-suffix-name). Prompt.md's own asset input is explicitly
"canonical/temporary ADC name" -- a name can legitimately be corrected or
finalized over an asset's lifetime. The previous scheme
(`PUBMED_ASSETEXP_{asset_id}_NAME_IC50`) would silently keep the SAME
query_id after such a rename even though query_text (which embeds
canonical_name) had changed underneath it -- exactly the "same query_id,
different query_text" violation Prompt.md section 20 exists to prevent.
Hashing the actual query_text fixes this (a name change produces a new
query_id, as it must) and, as a bonus, eliminates any risk of two
different identifiers colliding after `_slug()` normalization (e.g. two
distinct aliases that happen to slug to the same string) -- the hash
disambiguates even when the readable component doesn't. Re-running this
job with an UNCHANGED registry reproduces the exact same query_ids (the
hash is a pure function of the query text), so ordinary reruns are still
stable.
"""

from __future__ import annotations

import hashlib
import re

from jobs.known_adc_asset_expansion.asset_registry import KnownADCAsset

SUFFIX_TEMPLATES = ["patent", "trial", "activity", "cytotoxicity", "xenograft", "ic50"]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")[:40]


def _query_id(prefix: str, asset_id: str, readable: str, query_text: str) -> str:
    """query_id is derived from a hash of the ACTUAL query_text, not just
    (asset_id, readable) -- see module docstring's "QUERY_ID STABILITY"
    section. `readable` is purely a human-legibility aid; only the hash
    is load-bearing for uniqueness/stability."""
    digest = hashlib.sha256(query_text.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{asset_id.upper()}_{readable}_{digest}"


def _bare_identifier_queries(assets: list[KnownADCAsset], prefix: str, build_query_text) -> list[dict]:
    queries = []
    for asset in assets:
        for identifier in asset.identifiers():
            query_text = build_query_text(identifier)
            queries.append(dict(
                query_id=_query_id(prefix, asset.asset_id, _slug(identifier), query_text),
                query_version=1,
                query_text=query_text,
                purpose=f"Known-ADC asset expansion: bare identifier {identifier!r} for asset {asset.asset_id}.",
                active=True,
            ))
    return queries


def _suffix_queries(assets: list[KnownADCAsset], prefix: str, build_query_text) -> list[dict]:
    queries = []
    for asset in assets:
        for suffix in SUFFIX_TEMPLATES:
            query_text = build_query_text(asset.canonical_name, suffix)
            queries.append(dict(
                query_id=_query_id(prefix, asset.asset_id, suffix.upper(), query_text),
                query_version=1,
                query_text=query_text,
                purpose=f"Known-ADC asset expansion: {asset.canonical_name!r} + {suffix!r} for asset {asset.asset_id}.",
                active=True,
            ))
    return queries


def pubmed_queries(assets: list[KnownADCAsset]) -> list[dict]:
    return (
        _bare_identifier_queries(assets, "PUBMED_ASSETEXP", lambda identifier: f'"{identifier}"[tiab]')
        + _suffix_queries(assets, "PUBMED_ASSETEXP", lambda name, suffix: f'"{name}"[tiab] AND {suffix}[tiab]')
    )


def europe_pmc_queries(assets: list[KnownADCAsset]) -> list[dict]:
    return (
        _bare_identifier_queries(
            assets, "EPMC_ASSETEXP",
            lambda identifier: f'(TITLE:"{identifier}" OR ABSTRACT:"{identifier}")',
        )
        + _suffix_queries(
            assets, "EPMC_ASSETEXP",
            lambda name, suffix: f'(TITLE:"{name}" OR ABSTRACT:"{name}") AND {suffix}',
        )
    )


def wipo_queries(assets: list[KnownADCAsset]) -> list[dict]:
    """WO-prefixed only (pn=WO), same authority restriction as Job 08's own
    discovery queries. Title AND abstract, unlike EPO -- Job 08's own
    queries confirm this ti=/pn=WO combination is not affected by the
    title-search bug epo_queries.yaml documents for pn=EP. Bare identifiers
    only -- no suffix templates, see module docstring."""
    return _bare_identifier_queries(
        assets, "WIPO_ASSETEXP",
        lambda identifier: f'pn=WO and (ti="{identifier}" or ab="{identifier}")',
    )


def epo_queries(assets: list[KnownADCAsset]) -> list[dict]:
    """EP-prefixed only (pn=EP), abstract-only -- same disclosed
    title-search limitation jobs/epo/job.py's own discovery queries
    already accept (EPO OPS 500s on 3+-effective-title-term queries
    restricted to pn=EP; ab= sidesteps it entirely rather than risking a
    per-asset failure). Bare identifiers only -- no suffix templates, see
    module docstring."""
    return _bare_identifier_queries(
        assets, "EPO_ASSETEXP",
        lambda identifier: f'pn=EP and ab="{identifier}"',
    )


def uspto_queries(assets: list[KnownADCAsset]) -> list[dict]:
    """USPTO's free-text `q=` search covers the full specification content
    of an application (verified live, configs/uspto_queries.yaml), not
    just title/abstract -- unlike WIPO/EPO's OPS biblio search, so this
    is the one patent source that also gets the 6 suffix templates (see
    module docstring). `AND` is USPTO's own established boolean operator
    for this field (already used by its broad-discovery query family,
    e.g. 'antibody AND linker AND cytotoxin')."""
    return (
        _bare_identifier_queries(assets, "USPTO_ASSETEXP", lambda identifier: f'"{identifier}"')
        + _suffix_queries(assets, "USPTO_ASSETEXP", lambda name, suffix: f'"{name}" AND {suffix}')
    )
