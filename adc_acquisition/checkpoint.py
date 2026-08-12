"""Per-job checkpoint state so runs are restartable and incremental.

Stored as one JSON file per job under DATA/checkpoints/<job_name>.json.
Tracks, per source_record_id, the content hash of the last-downloaded
version — this is what lets a job skip re-downloading unchanged records
(Prompt.md section 4) and detect changed records for versioning
(Prompt.md section 23) instead of overwriting.

A job that acquires more than one kind of content-versioned artifact for the
same underlying record (e.g. Europe PMC's metadata JSON *and* its open-access
full-text XML) tracks each artifact type in its own `namespace` — same
checkpoint file, same (content_hash, version) shape, just keyed separately so
one artifact's state never collides with or gets overwritten by another's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_NAMESPACE = "records"


class CheckpointStore:
    def __init__(self, job_name: str, output_dir: Path):
        self.job_name = job_name
        self.path = Path(output_dir) / "checkpoints" / f"{job_name}.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "job": self.job_name,
                "last_run_at": None,
                "last_success_max_date": None,
                "records": {},
            }
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp_path.replace(self.path)

    def get_record_state(
        self, checkpoint: dict[str, Any], source_record_id: str, namespace: str = DEFAULT_NAMESPACE
    ) -> dict[str, Any] | None:
        return checkpoint.get(namespace, {}).get(source_record_id)

    def set_record_state(
        self,
        checkpoint: dict[str, Any],
        source_record_id: str,
        content_hash: str,
        version: int,
        last_seen_at: str,
        namespace: str = DEFAULT_NAMESPACE,
        extra: dict[str, Any] | None = None,
    ) -> None:
        state = {
            "content_hash": content_hash,
            "version": version,
            "last_seen_at": last_seen_at,
        }
        if extra:
            state.update(extra)
        checkpoint.setdefault(namespace, {})[source_record_id] = state
