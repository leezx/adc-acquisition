"""Per-source query generation for known-ADC asset expansion (Prompt.md
section 19, Job 15): "<ADC name>", "<ADC alias>", "<ADC name>" patent/
trial/activity/cytotoxicity/xenograft/IC50.

Each source gets Prompt.md's templates translated into ITS OWN real query
syntax (same translation this repo already does for the broad discovery
query family: configs/pubmed_queries.yaml uses [tiab], europe_pmc_queries.yaml
uses TITLE:/ABSTRACT:, wipo_queries.yaml/epo_queries.yaml use OPS CQL) --
never passed through verbatim as English text.

SUFFIX TEMPLATES (patent/trial/activity/cytotoxicity/xenograft/IC50) are
generated ONLY for the two general-literature sources (PubMed, Europe PMC).
Disclosed, not silently narrowed: WIPO/EPO's searchable fields (OPS
biblio's title/abstract) essentially never contain experimental-data
language like "xenograft" or "IC50" -- that lives in the full specification
text, which Job 13 (patent bioactivity corpus) already acquires separately
for the same publications. Appending those suffix words to a WIPO/EPO
title/abstract query would search for text that structurally isn't there,
not narrow anything meaningfully. WIPO/EPO instead get the bare "<name>"/
"<alias>" identifier templates only (every distinct identifier
KnownADCAsset.identifiers() returns, not canonical name alone).
ClinicalTrials.gov (Job 03) is handled entirely through its existing
--intervention lookup (jobs/clinicaltrials/job.py), one call per
identifier -- its own corpus already IS trials, so the "trial" suffix
would be redundant, and "patent"/"activity"/"cytotoxicity"/"xenograft"/
"IC50" don't map onto CT.gov's query.intr field at all.

Crossref (Job 04) is NOT a target here: its own module docstring already
established (verified live) that free-text search is relevance-ranked and
unusable for precise discovery -- Job 04 exists for DOI-exact
reconciliation, not name search, and this job doesn't change that.

Every generated query_id is a deterministic function of (asset_id,
identifier-or-suffix) -- re-running this job reproduces the SAME ids, so a
query_id is never silently reused for a materially different query_text
(Prompt.md section 20) even across repeated runs or registry regenerations.
"""

from __future__ import annotations

import re

from jobs.known_adc_asset_expansion.asset_registry import KnownADCAsset

SUFFIX_TEMPLATES = ["patent", "trial", "activity", "cytotoxicity", "xenograft", "ic50"]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def pubmed_queries(assets: list[KnownADCAsset]) -> list[dict]:
    queries = []
    for asset in assets:
        for identifier in asset.identifiers():
            queries.append(dict(
                query_id=f"PUBMED_ASSETEXP_{asset.asset_id.upper()}_{_slug(identifier)}",
                query_version=1,
                query_text=f'"{identifier}"[tiab]',
                purpose=f"Known-ADC asset expansion: bare identifier {identifier!r} for asset {asset.asset_id}.",
                active=True,
            ))
        for suffix in SUFFIX_TEMPLATES:
            queries.append(dict(
                query_id=f"PUBMED_ASSETEXP_{asset.asset_id.upper()}_NAME_{suffix.upper()}",
                query_version=1,
                query_text=f'"{asset.canonical_name}"[tiab] AND {suffix}[tiab]',
                purpose=f"Known-ADC asset expansion: {asset.canonical_name!r} + {suffix!r} for asset {asset.asset_id}.",
                active=True,
            ))
    return queries


def europe_pmc_queries(assets: list[KnownADCAsset]) -> list[dict]:
    queries = []
    for asset in assets:
        for identifier in asset.identifiers():
            queries.append(dict(
                query_id=f"EPMC_ASSETEXP_{asset.asset_id.upper()}_{_slug(identifier)}",
                query_version=1,
                query_text=f'(TITLE:"{identifier}" OR ABSTRACT:"{identifier}")',
                purpose=f"Known-ADC asset expansion: bare identifier {identifier!r} for asset {asset.asset_id}.",
                active=True,
            ))
        for suffix in SUFFIX_TEMPLATES:
            queries.append(dict(
                query_id=f"EPMC_ASSETEXP_{asset.asset_id.upper()}_NAME_{suffix.upper()}",
                query_version=1,
                query_text=f'(TITLE:"{asset.canonical_name}" OR ABSTRACT:"{asset.canonical_name}") AND {suffix}',
                purpose=f"Known-ADC asset expansion: {asset.canonical_name!r} + {suffix!r} for asset {asset.asset_id}.",
                active=True,
            ))
    return queries


def wipo_queries(assets: list[KnownADCAsset]) -> list[dict]:
    """WO-prefixed only (pn=WO), same authority restriction as Job 08's own
    discovery queries. Title AND abstract, unlike EPO -- Job 08's own
    queries confirm this ti=/pn=WO combination is not affected by the
    title-search bug epo_queries.yaml documents for pn=EP."""
    queries = []
    for asset in assets:
        for identifier in asset.identifiers():
            queries.append(dict(
                query_id=f"WIPO_ASSETEXP_{asset.asset_id.upper()}_{_slug(identifier)}",
                query_version=1,
                query_text=f'pn=WO and (ti="{identifier}" or ab="{identifier}")',
                purpose=f"Known-ADC asset expansion: bare identifier {identifier!r} for asset {asset.asset_id}.",
                active=True,
            ))
    return queries


def epo_queries(assets: list[KnownADCAsset]) -> list[dict]:
    """EP-prefixed only (pn=EP), abstract-only -- same disclosed
    title-search limitation jobs/epo/job.py's own discovery queries
    already accept (EPO OPS 500s on 3+-effective-title-term queries
    restricted to pn=EP; ab= sidesteps it entirely rather than risking a
    per-asset failure)."""
    queries = []
    for asset in assets:
        for identifier in asset.identifiers():
            queries.append(dict(
                query_id=f"EPO_ASSETEXP_{asset.asset_id.upper()}_{_slug(identifier)}",
                query_version=1,
                query_text=f'pn=EP and ab="{identifier}"',
                purpose=f"Known-ADC asset expansion: bare identifier {identifier!r} for asset {asset.asset_id}.",
                active=True,
            ))
    return queries
