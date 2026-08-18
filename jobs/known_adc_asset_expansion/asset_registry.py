"""Known-ADC asset registry loader (Prompt.md section 19, Job 15).

Same "curated YAML, loaded once" pattern as adc_acquisition/company_registry.py
(used only by this job, so kept local rather than promoted to
adc_acquisition/ — promote it if a second job ever needs the same asset
list)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class KnownADCAsset:
    asset_id: str
    canonical_name: str
    aliases: list[str]
    dev_codes: list[str]
    target: str | None
    company: str | None
    active: bool

    def identifiers(self) -> list[str]:
        """Every distinct string worth searching for verbatim (canonical
        name first, then aliases, then dev codes) — deduplicated but
        order-preserving, since literature/patents may use only a dev
        code, only a brand name, or the INN name, never assume one
        implies the others are also searched."""
        seen: set[str] = set()
        ordered: list[str] = []
        for identifier in [self.canonical_name, *self.aliases, *self.dev_codes]:
            if identifier not in seen:
                seen.add(identifier)
                ordered.append(identifier)
        return ordered


def load_known_adc_assets(path: Path) -> list[KnownADCAsset]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    assets = []
    seen_ids: set[str] = set()
    for entry in data.get("assets", []):
        asset = KnownADCAsset(
            asset_id=entry["asset_id"],
            canonical_name=entry["canonical_name"],
            aliases=list(entry.get("aliases") or []),
            dev_codes=list(entry.get("dev_codes") or []),
            target=entry.get("target"),
            company=entry.get("company"),
            active=entry.get("active", True),
        )
        if asset.asset_id in seen_ids:
            raise ValueError(f"duplicate asset_id in {path}: {asset.asset_id}")
        seen_ids.add(asset.asset_id)
        assets.append(asset)
    return assets


def active_assets(assets: list[KnownADCAsset]) -> list[KnownADCAsset]:
    return [a for a in assets if a.active]
