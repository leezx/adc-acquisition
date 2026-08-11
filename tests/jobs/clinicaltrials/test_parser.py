from jobs.clinicaltrials.parser import parse_study

FULL_STUDY = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT05798156",
            "briefTitle": "Brief Title",
            "officialTitle": "Official Title",
        },
        "statusModule": {
            "overallStatus": "ACTIVE_NOT_RECRUITING",
            "studyFirstPostDateStruct": {"date": "2019-12-15", "type": "ACTUAL"},
            "startDateStruct": {"date": "2023-03-20", "type": "ACTUAL"},
            "primaryCompletionDateStruct": {"date": "2025-04-12", "type": "ACTUAL"},
            "completionDateStruct": {"date": "2028-02-28", "type": "ESTIMATED"},
            "lastUpdatePostDateStruct": {"date": "2026-04-08", "type": "ACTUAL"},
        },
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "Lead Sponsor Inc", "class": "OTHER"},
            "collaborators": [{"name": "Collab A", "class": "OTHER"}, {"name": "Collab B", "class": "INDUSTRY"}],
        },
        "conditionsModule": {"conditions": ["Aggressive B-cell Lymphoma"]},
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE2"],
            "enrollmentInfo": {"count": 125, "type": "ACTUAL"},
        },
        "armsInterventionsModule": {
            "interventions": [
                {"type": "DRUG", "name": "Glofitamab"},
                {"type": "DRUG", "name": "Polatuzumab Vedotin"},
            ]
        },
        "outcomesModule": {
            "primaryOutcomes": [{"measure": "PFS rate", "timeFrame": "12 months"}],
            "secondaryOutcomes": [{"measure": "OS", "timeFrame": "54 months"}, {"measure": "EFS"}],
        },
        "contactsLocationsModule": {
            "locations": [
                {"facility": "Some Hospital", "city": "Berlin", "country": "Germany"},
                {"city": "Vienna", "country": "Austria"},  # missing facility
            ]
        },
        "referencesModule": {"references": [{"citation": "Smith et al 2020", "pmid": "12345"}]},
    }
}

MINIMAL_STUDY = {"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}}


def test_parses_full_study():
    parsed = parse_study(FULL_STUDY)
    assert parsed.nct_id == "NCT05798156"
    assert parsed.brief_title == "Brief Title"
    assert parsed.official_title == "Official Title"
    assert parsed.study_type == "INTERVENTIONAL"
    assert parsed.phases == ["PHASE2"]
    assert parsed.overall_status == "ACTIVE_NOT_RECRUITING"
    assert parsed.conditions == ["Aggressive B-cell Lymphoma"]
    assert parsed.intervention_names == ["Glofitamab", "Polatuzumab Vedotin"]
    assert parsed.lead_sponsor == "Lead Sponsor Inc"
    assert parsed.collaborators == ["Collab A", "Collab B"]
    assert parsed.enrollment == 125
    assert parsed.enrollment_type == "ACTUAL"
    assert parsed.study_first_post_date == "2019-12-15"
    assert parsed.start_date == "2023-03-20"
    assert parsed.primary_completion_date == "2025-04-12"
    assert parsed.completion_date == "2028-02-28"
    assert parsed.primary_outcomes == ["PFS rate"]
    assert parsed.secondary_outcomes == ["OS", "EFS"]
    assert parsed.locations == ["Some Hospital, Berlin, Germany", "Vienna, Austria"]
    assert parsed.references == ["Smith et al 2020"]
    assert parsed.last_update_date == "2026-04-08"


def test_minimal_study_has_defaults_for_missing_modules():
    parsed = parse_study(MINIMAL_STUDY)
    assert parsed.nct_id == "NCT00000001"
    assert parsed.brief_title is None
    assert parsed.phases == []
    assert parsed.conditions == []
    assert parsed.intervention_names == []
    assert parsed.collaborators == []
    assert parsed.enrollment is None
    assert parsed.primary_outcomes == []
    assert parsed.locations == []
    assert parsed.references == []


def test_missing_protocol_section_returns_none():
    assert parse_study({}) is None


def test_missing_nct_id_returns_none():
    assert parse_study({"protocolSection": {"identificationModule": {}}}) is None


def test_study_first_post_date_and_start_date_are_distinct_fields():
    """Reviewer acceptance scenario: startDate, studyFirstPostDate, and
    lastUpdatePostDate must never collapse into the same value."""
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT1"},
            "statusModule": {
                "studyFirstPostDateStruct": {"date": "2019-12-15"},
                "startDateStruct": {"date": "2020-03-01"},
                "lastUpdatePostDateStruct": {"date": "2024-06-01"},
            },
        }
    }
    parsed = parse_study(study)
    assert parsed.study_first_post_date == "2019-12-15"
    assert parsed.start_date == "2020-03-01"
    assert parsed.last_update_date == "2024-06-01"


def test_reference_without_citation_falls_back_to_pmid():
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT1"},
            "referencesModule": {"references": [{"pmid": "999"}, {}]},
        }
    }
    parsed = parse_study(study)
    assert parsed.references == ["999"]
