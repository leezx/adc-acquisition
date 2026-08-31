"""Parsing for WHO ICTRP's manually-exported "Export results to XML" file.

Root element `<Trials_downloaded_from_ICTRP>`, one `<Trial>` child per
trial. Every leaf field is a simple text node (verified against a real
292-trial export dated 2026-08-28) -- no nested structure to walk beyond
one level. `<TrialID>` is WHO ICTRP's own cross-registry identifier: for a
ClinicalTrials.gov-sourced trial it IS the NCT number; for every other
`Source_Register` (EU Clinical Trials Register / Clinical Trials
Information System / JPRN / ChiCTR / CTRI / ISRCTN / ANZCTR / NL-OMON /
REBEC / REPEC, all observed in the real export) it's that registry's own
native trial id -- confirmed unique across all 292 real trials, used
directly as `source_record_id`.

Every text node in the real export carries leading/trailing whitespace
(WHO's own XML formatting, e.g. `<Acronym/>` for empty vs.
`<Internal_Number>16045974\n    </Internal_Number>` for populated) --
every field access strips it; an empty/self-closing element normalizes to
`None`, never an empty string, so a manifest column's "not stated" and
"stated but blank" are never confused.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

# Every leaf field this job materializes, verified present in the real
# export's schema (a field this repo doesn't use, e.g. Inclusion_Criteria's
# full free text, is deliberately left unread -- not needed for asset/
# trial-identity purposes, and Job 03/ClinicalTrials.gov already carries
# the full CT.gov-side record for any NCT-sourced trial).
_FIELDS = [
    "TrialID", "Source_Register", "Public_title", "Scientific_title",
    "Primary_sponsor", "Secondary_Sponsor", "Phase", "Recruitment_Status",
    "Countries", "Intervention", "Condition", "web_address",
    "Date_registration3", "Last_Refreshed_on", "Target_size", "Study_type",
    "other_records",
]


def _text(trial: ET.Element, tag: str) -> str | None:
    value = trial.findtext(tag)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def parse_trial(trial: ET.Element) -> dict:
    return {field: _text(trial, field) for field in _FIELDS}


def parse_export_file(path: Path) -> list[dict]:
    """Returns every `<Trial>` in one export file as a plain dict. Raises
    on a file that isn't this export shape (e.g. a wrong/corrupted
    download) rather than silently returning an empty list, matching
    every other job's "fail loud on a bad external input" precedent."""
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "Trials_downloaded_from_ICTRP":
        raise ValueError(
            f"{path} does not look like a WHO ICTRP 'Export results to XML' file "
            f"(root element is <{root.tag}>, expected <Trials_downloaded_from_ICTRP>)"
        )
    return [parse_trial(t) for t in root.findall("Trial")]


def normalize_registration_date(value: str | None) -> str | None:
    """Date_registration3 is already YYYYMMDD (verified against the real
    export, e.g. "20260814") -- reshape to YYYY-MM-DD for
    publication_or_release_date's convention elsewhere in this repo. An
    unparseable or missing value returns None rather than a guess."""
    if not value or len(value) != 8 or not value.isdigit():
        return None
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
