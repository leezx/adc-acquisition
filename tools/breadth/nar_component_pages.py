"""Lightweight parsing of NAR ADCdb's component entity pages (Antigens,
Targets, Antibodies, Payloads, Linkers), read-only against the external
vault (see reports/validation/BREADTH_PLAN.md Part 1).

Established by direct inspection of the vault (2026-08-20): every one of
these pages carries the SAME YAML frontmatter (id/name/entity_type/
source_url) and the SAME "## ADCdb Links" section listing backlinks to
other entities -- this is the reliable, universal part, present on all
316 Antigens / 52 Targets / 1,380 Antibodies / 521 Payloads / 587 Linkers
files. A majority (but not all: 283/316, 45/52, 1187/1380, 444/521,
494/587 respectively) additionally carry a "## General Information"
markdown table with per-type structured fields (e.g. "Antigen Name" /
"Gene Name" / "Synonym" for an Antigen page); the rest fall back to an
unstructured "## Extracted Page Text" scrape with no parseable table --
those pages still contribute id/name/backlinks, just with the extra
structured fields left blank. This matches Part 16's "lightweight
breadth-oriented index, partial information is fine" scope for this
phase -- deeper extraction of the unstructured fallback pages is
explicitly deferred, not attempted here.

`Targets/` (the payload mechanism-of-action target, e.g. TOP1, BCL2L1 --
NOT the antibody-binding antigen) is the one component type whose ADCdb
Links section backlinks to ADCs via bare "ADC Info" URLs (an adc_id
embedded in the link, not an [[ADCs/Name|Name]] wikilink) rather than a
named wikilink -- so its backlink names are unavailable, only counts and
adc_ids. This is a genuine schema asymmetry in the external vault, not a
parsing bug; documented here rather than worked around.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

WIKILINK_RE = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
ADC_INFO_URL_RE = re.compile(r"\[ADC Info\]\([^)]*?/details/([A-Za-z0-9]+)\)")
TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|?\s*$")


@dataclass
class ComponentPage:
    entity_id: str
    canonical_name: str
    entity_type: str
    source_url: str
    fields: dict[str, str] = field(default_factory=dict)
    adc_backlink_names: list[str] = field(default_factory=list)  # named wikilinks (Antigens/Payloads/Linkers/Antibodies)
    adc_backlink_ids: list[str] = field(default_factory=list)  # bare adc_id-only backlinks (Targets)


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}
    return {k: str(v) for k, v in data.items()}


def _parse_general_info_table(lines: list[str]) -> dict[str, str]:
    """Same tolerant table parser as compare_nar_adcdb.py's
    _parse_general_info_table, duplicated here (not imported) because it
    operates on a generic "## General Information" header shared by every
    component page type, independent of the ADC-page-specific fields that
    module's own copy is tuned around."""
    fields_out: dict[str, str] = {}
    in_table = False
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if line.startswith("## General Information"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                if fields_out:
                    break
                continue
            m = TABLE_ROW_RE.match(line)
            if not m:
                continue
            field_name, value = m.group(1).strip(), m.group(2).strip()
            if field_name in ("Field", "------") or set(field_name) == {"-"}:
                continue
            fields_out[field_name] = value
    return fields_out


def parse_component_page(path: Path, entity_type: str) -> ComponentPage:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm = _parse_frontmatter(text)
    page = ComponentPage(
        entity_id=fm.get("id", ""),
        canonical_name=fm.get("name", path.stem),
        entity_type=entity_type,
        source_url=fm.get("source_url", ""),
    )
    links_idx = text.find("## ADCdb Links")
    if links_idx != -1:
        next_section = text.find("\n## ", links_idx + 1)
        links_block = text[links_idx: next_section if next_section != -1 else None]
        for target, label in WIKILINK_RE.findall(links_block):
            if target.startswith("ADCs/"):
                page.adc_backlink_names.append(label.strip())
        for adc_id in ADC_INFO_URL_RE.findall(links_block):
            page.adc_backlink_ids.append(adc_id.strip())
    page.fields = _parse_general_info_table(text.splitlines())
    return page


def load_component_pages(vault_root: Path, subdir: str, entity_type: str) -> list[ComponentPage]:
    directory = vault_root / subdir
    if not directory.is_dir():
        return []
    return [parse_component_page(p, entity_type) for p in sorted(directory.glob("*.md"))]
