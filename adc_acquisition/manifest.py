"""Universal manifest contract (Prompt.md section 3).

Every source job writes rows with this common column set, plus whatever
source-specific columns it needs. We deliberately do NOT force every field
from every source into one shared schema — that would destroy information
(e.g. an `nct_id` column has no meaning for a PubMed manifest). Each source's
manifest parquet file gets COMMON_FIELDS plus that source's own extra fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

# Minimum common fields every manifest row must have (Prompt.md section 3).
COMMON_FIELDS: list[str] = [
    "source",
    "source_record_id",
    "source_record_type",
    "title",
    "url",
    "publication_or_release_date",
    "retrieved_at",
    "query_id",
    "query_text",
    "raw_file_path",
    "raw_format",
    "content_hash",
    "download_status",
    "http_status",
    "license_or_access_note",
    "parent_record_id",
    "version",
    "notes",
]

# Natural key for upsert/versioning: same source_record_id can appear with
# multiple versions over time (Prompt.md section 23); never overwrite a row
# in place, only add a new version row.
MANIFEST_KEY_FIELDS = ("source", "source_record_id", "version")


def new_manifest_row(extra_fields: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Build one manifest row, validating that all COMMON_FIELDS are present
    (as None if genuinely inapplicable) and rejecting unknown columns that
    aren't declared in extra_fields."""
    allowed = set(COMMON_FIELDS) | set(extra_fields or [])
    unknown = set(kwargs) - allowed
    if unknown:
        raise ValueError(f"unknown manifest fields not declared in extra_fields: {sorted(unknown)}")
    row = {field: kwargs.get(field) for field in COMMON_FIELDS}
    for field in extra_fields or []:
        row[field] = kwargs.get(field)
    return row


def write_manifest(rows: list[dict[str, Any]], path: Path, extra_fields: list[str] | None = None) -> pd.DataFrame:
    """Upsert rows into a manifest parquet file, keyed by MANIFEST_KEY_FIELDS.

    New rows with the same key replace existing ones (e.g. a re-run that
    picks up a corrected download_status); a genuinely new content version
    must get a bumped `version` value from the caller, which makes it a
    distinct key and therefore an additional row, not a replacement.
    """
    columns = COMMON_FIELDS + list(extra_fields or [])
    new_df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)

    path = Path(path)
    if path.exists():
        existing_df = pd.read_parquet(path)
        # Tolerate manifests written before extra_fields were added.
        for col in columns:
            if col not in existing_df.columns:
                existing_df[col] = None
        combined = pd.concat([existing_df[columns], new_df[columns]], ignore_index=True)
    else:
        combined = new_df

    if not combined.empty:
        combined = combined.drop_duplicates(subset=list(MANIFEST_KEY_FIELDS), keep="last")
        combined = combined.sort_values(by=["source_record_id", "version"]).reset_index(drop=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return combined
