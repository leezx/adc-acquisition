from pathlib import Path

import pytest

from jobs.who_ictrp.parser import normalize_registration_date, parse_export_file

EXPORT_TEMPLATE = """<?xml version='1.0' encoding='UTF-8' ?>
<Trials_downloaded_from_ICTRP>
  <Trial><Export_date>08/28/2026 20:14:44</Export_date>
    <Internal_Number>1
    </Internal_Number>
    <TrialID>{trial_id}
    </TrialID>
    <Public_title>{title}
    </Public_title>
    <Scientific_title>A phase 1 study
    </Scientific_title>
    <Acronym/>
    <Primary_sponsor>{sponsor}
    </Primary_sponsor>
    <Secondary_Sponsor/>
    <Source_Register>{source_register}
    </Source_Register>
    <web_address>{url}
    </web_address>
    <Recruitment_Status>Recruiting
    </Recruitment_Status>
    <other_records>{other_records}
    </other_records>
    <Phase>Phase 1
    </Phase>
    <Countries>United States
    </Countries>
    <Intervention>Drug: {intervention}
    </Intervention>
    <Condition>Solid tumors
    </Condition>
    <Date_registration3>{date_reg}
    </Date_registration3>
    <Last_Refreshed_on>24 August 2026
    </Last_Refreshed_on>
    <Target_size>100
    </Target_size>
    <Study_type>Interventional
    </Study_type>
  </Trial>
</Trials_downloaded_from_ICTRP>
"""


def _write_export(tmp_path, **overrides):
    defaults = dict(
        trial_id="NCT01234567", title="A study of Foo-ADC", sponsor="Example Pharma",
        source_register="ClinicalTrials.gov", url="https://clinicaltrials.gov/study/NCT01234567",
        other_records="No", intervention="Foo-ADC", date_reg="20260101",
    )
    defaults.update(overrides)
    path = tmp_path / "ICTRP-Results-20260828.xml"
    path.write_text(EXPORT_TEMPLATE.format(**defaults), encoding="utf-8")
    return path


def test_parse_export_file_reads_all_fields(tmp_path):
    path = _write_export(tmp_path)
    trials = parse_export_file(path)
    assert len(trials) == 1
    trial = trials[0]
    assert trial["TrialID"] == "NCT01234567"
    assert trial["Source_Register"] == "ClinicalTrials.gov"
    assert trial["Public_title"] == "A study of Foo-ADC"
    assert trial["Primary_sponsor"] == "Example Pharma"


def test_parse_export_file_empty_element_is_none_not_empty_string(tmp_path):
    path = _write_export(tmp_path)
    trials = parse_export_file(path)
    assert trials[0]["Secondary_Sponsor"] is None


def test_parse_export_file_rejects_wrong_root_element(tmp_path):
    path = tmp_path / "not_ictrp.xml"
    path.write_text("<?xml version='1.0' ?><SomethingElse></SomethingElse>", encoding="utf-8")
    with pytest.raises(ValueError, match="does not look like"):
        parse_export_file(path)


def test_normalize_registration_date_valid():
    assert normalize_registration_date("20260814") == "2026-08-14"


def test_normalize_registration_date_missing_or_malformed_returns_none():
    assert normalize_registration_date(None) is None
    assert normalize_registration_date("N/A") is None
    assert normalize_registration_date("2026-08") is None
