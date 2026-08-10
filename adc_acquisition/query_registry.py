"""Query provenance registry (Prompt.md section 20).

Every discovered record must be traceable back to the exact query that
discovered it. Each job keeps its own queries in a small YAML file
(e.g. configs/pubmed_queries.yaml) loaded through this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class QuerySpec:
    query_id: str
    query_version: int
    query_text: str
    purpose: str
    active: bool


def load_queries(path: Path) -> list[QuerySpec]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    queries = []
    seen_ids: set[str] = set()
    for entry in data.get("queries", []):
        spec = QuerySpec(
            query_id=entry["query_id"],
            query_version=entry["query_version"],
            query_text=entry["query_text"],
            purpose=entry.get("purpose", ""),
            active=entry.get("active", True),
        )
        if spec.query_id in seen_ids:
            raise ValueError(f"duplicate query_id in {path}: {spec.query_id}")
        seen_ids.add(spec.query_id)
        queries.append(spec)
    return queries


def active_queries(queries: list[QuerySpec]) -> list[QuerySpec]:
    return [q for q in queries if q.active]
