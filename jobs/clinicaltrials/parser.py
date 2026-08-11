"""Normalize one ClinicalTrials.gov v2 study record.

Like Europe PMC's core result, this is already structured JSON — no XML
tree to walk. Every lookup is defensive: a trial record can legitimately be
missing almost any given module (e.g. a very new record with no outcomes
module yet), and one missing field must never crash the batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedStudy:
    nct_id: str
    brief_title: str | None
    official_title: str | None
    study_type: str | None
    phases: list[str] = field(default_factory=list)
    overall_status: str | None = None
    conditions: list[str] = field(default_factory=list)
    intervention_names: list[str] = field(default_factory=list)
    lead_sponsor: str | None = None
    collaborators: list[str] = field(default_factory=list)
    enrollment: int | None = None
    enrollment_type: str | None = None
    start_date: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None
    primary_outcomes: list[str] = field(default_factory=list)
    secondary_outcomes: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    last_update_date: str | None = None


def _outcome_measures(outcomes: list[dict] | None) -> list[str]:
    if not outcomes:
        return []
    return [o["measure"] for o in outcomes if o.get("measure")]


def _location_strings(locations: list[dict] | None) -> list[str]:
    if not locations:
        return []
    result = []
    for loc in locations:
        parts = [loc.get("facility"), loc.get("city"), loc.get("country")]
        text = ", ".join(p for p in parts if p)
        if text:
            result.append(text)
    return result


def _reference_strings(references: list[dict] | None) -> list[str]:
    if not references:
        return []
    result = []
    for ref in references:
        citation = ref.get("citation") or ref.get("pmid")
        if citation:
            result.append(str(citation))
    return result


def parse_study(raw_result: dict[str, Any]) -> ParsedStudy | None:
    protocol = raw_result.get("protocolSection")
    if not protocol:
        return None
    identification = protocol.get("identificationModule") or {}
    nct_id = identification.get("nctId")
    if not nct_id:
        return None

    status = protocol.get("statusModule") or {}
    sponsor_collab = protocol.get("sponsorCollaboratorsModule") or {}
    design = protocol.get("designModule") or {}
    conditions_module = protocol.get("conditionsModule") or {}
    arms_interventions = protocol.get("armsInterventionsModule") or {}
    outcomes = protocol.get("outcomesModule") or {}
    contacts_locations = protocol.get("contactsLocationsModule") or {}
    references_module = protocol.get("referencesModule") or {}

    enrollment_info = design.get("enrollmentInfo") or {}
    lead_sponsor = sponsor_collab.get("leadSponsor") or {}

    return ParsedStudy(
        nct_id=nct_id,
        brief_title=identification.get("briefTitle"),
        official_title=identification.get("officialTitle"),
        study_type=design.get("studyType"),
        phases=list(design.get("phases") or []),
        overall_status=status.get("overallStatus"),
        conditions=list(conditions_module.get("conditions") or []),
        intervention_names=[i["name"] for i in (arms_interventions.get("interventions") or []) if i.get("name")],
        lead_sponsor=lead_sponsor.get("name"),
        collaborators=[c["name"] for c in (sponsor_collab.get("collaborators") or []) if c.get("name")],
        enrollment=enrollment_info.get("count"),
        enrollment_type=enrollment_info.get("type"),
        start_date=(status.get("startDateStruct") or {}).get("date"),
        primary_completion_date=(status.get("primaryCompletionDateStruct") or {}).get("date"),
        completion_date=(status.get("completionDateStruct") or {}).get("date"),
        primary_outcomes=_outcome_measures(outcomes.get("primaryOutcomes")),
        secondary_outcomes=_outcome_measures(outcomes.get("secondaryOutcomes")),
        locations=_location_strings(contacts_locations.get("locations")),
        references=_reference_strings(references_module.get("references")),
        last_update_date=(status.get("lastUpdatePostDateStruct") or {}).get("date"),
    )
