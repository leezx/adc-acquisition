"""Shared company registry (configs/company_registry.yaml), used by every
job keyed on a curated list of ADC-relevant pharma/biotech companies (Job
05/SEC, Job 07/company pipeline pages, and eventually Job 08/company press
releases) — one company can have fields relevant to some jobs and not
others (e.g. `ciks` only matters to SEC, `pipeline_urls` only to the
pipeline job), so this single dataclass carries the union of all of them
rather than each job defining its own narrower, incompatible `Company`
shape. A job that doesn't need a field simply doesn't read it; a company
with no meaningful value for a job-specific field (e.g. `pipeline_urls: []`
for a company with no standalone pipeline page, `ciks: []` for a company
never registered separately with SEC) just leaves it empty, which each
job's own filtering already treats as "nothing to do for this company."

`load_companies` also tolerates and drops any YAML key that isn't a
recognized field, so this file can keep gaining new job-specific fields
over time without ever needing InputValidationError-style lockstep
changes to every job's loader.
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


_KNOWN_FIELDS = {f.name for f in fields(Company)}


def load_companies(path: Path) -> list[Company]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [
        Company(**{k: v for k, v in entry.items() if k in _KNOWN_FIELDS})
        for entry in data.get("companies", [])
    ]
