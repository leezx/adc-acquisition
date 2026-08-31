"""Shared company registry (configs/company_registry.yaml), used by every
job keyed on a curated list of ADC-relevant pharma/biotech companies (Job
05/SEC, Job 11/company pipeline pages, Job 12/company press releases) —
one company can have fields relevant to some jobs and not others (e.g.
`ciks` only matters to SEC, `pipeline_urls` only to the pipeline job,
`press_release_template` only to the press-release job), so this single
dataclass carries the union of all of them rather than each job defining
its own narrower, incompatible `Company` shape. A job that doesn't need a
field simply doesn't read it; a company with no meaningful value for a
job-specific field (e.g. `pipeline_urls: []` for a company with no
standalone pipeline page, `ciks: []` for a company never registered
separately with SEC) just leaves it empty, which each job's own filtering
already treats as "nothing to do for this company."

`load_companies` also tolerates and drops any YAML key that isn't a
recognized field, so this file can keep gaining new job-specific fields
over time without ever needing InputValidationError-style lockstep
changes to every job's loader.

EXTENDED for the company scientific-presentation source (BREADTH_PLAN.md
Phase 5, Part 7) on 2026-08-24: `presentations_url`/`presentations_template`.
Live-verified this is NOT always the same domain as `official_domain` or
`investor_relations_url` -- ADC Therapeutics' scientific-presentations
archive lives on adctmedical.com (a separate medical-affairs microsite),
not adctherapeutics.com. jobs/company_scientific_presentations/job.py's
own official-domain check is therefore anchored to `presentations_url`'s
OWN host, never to `official_domain` -- see that job's module docstring.

EXTENDED for the company-registry expansion (source-coverage expansion,
2026-08-28): `parent_company_id`. An acquired/absorbed company (e.g.
Seagen, ImmunoGen, Mersana -- already in this registry with
`pipeline_urls: []` and a free-text note pointing at the acquirer) now
gets that relationship recorded STRUCTURALLY too, not only in prose --
`parent_company_id` names another entry's own `company_id` whose pipeline
page is where this company's former ADC assets now actually appear.
`None` (the default) means "not acquired, or acquirer not itself in this
registry yet." This is read-only annotation for downstream audit tooling
(`tools/validation/company_registry_gap_analysis.py`'s
`PHASE1_PLUS_COMPANY_UNIVERSE.tsv` output) -- no acquisition job
currently branches on it; it does not change any job's own behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Company:
    company_id: str
    canonical_name: str
    ciks: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    tickers: list = field(default_factory=list)
    active: bool = True
    notes: str | None = None
    official_domain: str | None = None
    pipeline_urls: list = field(default_factory=list)
    investor_relations_url: str | None = None
    press_release_url: str | None = None
    press_release_template: str | None = None
    presentations_url: str | None = None
    presentations_template: str | None = None
    parent_company_id: str | None = None


_KNOWN_FIELDS = {f.name for f in fields(Company)}


def load_companies(path: Path) -> list[Company]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [
        Company(**{k: v for k, v in entry.items() if k in _KNOWN_FIELDS})
        for entry in data.get("companies", [])
    ]
