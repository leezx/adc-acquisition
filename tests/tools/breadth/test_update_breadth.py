import sys

import pandas as pd

from tools.breadth.update_breadth import (
    DeltaResult,
    JobRunOutcome,
    _tier_for_row,
    build_delta_markdown,
    diff_snapshots,
    main as update_breadth_main,
    make_delta_dir,
    read_feasibility_snapshot,
    run_acquisition_stage,
    run_derivation_stage,
)


def _df(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def test_diff_snapshots_detects_new_row_by_natural_key():
    before = {"adc_candidates.tsv": _df([{"entity_id": "A1", "canonical_label": "Existing"}])}
    after = {"adc_candidates.tsv": _df([
        {"entity_id": "A1", "canonical_label": "Existing"},
        {"entity_id": "A2", "canonical_label": "Brand New"},
    ])}
    new_rows, deepened, status_changes = diff_snapshots(before, after)
    assert len(new_rows["adc_candidates.tsv"]) == 1
    assert new_rows["adc_candidates.tsv"][0]["entity_id"] == "A2"
    assert "adc_candidates.tsv" not in deepened
    assert status_changes == {}


def test_diff_snapshots_no_change_produces_no_new_rows():
    same = {"adc_candidates.tsv": _df([{"entity_id": "A1", "canonical_label": "Existing"}])}
    new_rows, deepened, status_changes = diff_snapshots(same, same)
    assert new_rows == {}
    assert deepened == {}
    assert status_changes == {}


def test_diff_snapshots_detects_evidence_deepened_not_as_new_row():
    """An existing entity whose evidence_count grew must be reported as
    'deepened', never miscounted as a new-entity event."""
    before = {"adc_platforms.tsv": _df([{"entity_id": "P1", "evidence_count": "3", "status": "OBSERVED"}])}
    after = {"adc_platforms.tsv": _df([{"entity_id": "P1", "evidence_count": "5", "status": "OBSERVED"}])}
    new_rows, deepened, _ = diff_snapshots(before, after)
    assert new_rows == {}
    assert deepened["adc_platforms.tsv"] == [(("P1",), 3, 5)]


def test_diff_snapshots_composite_key_for_target_indication():
    before = {"target_indication_feasibility.tsv": _df([])}
    after = {"target_indication_feasibility.tsv": _df([
        {"target_entity_id": "T1", "indication": "Breast cancer", "supporting_asset_count": "2"},
    ])}
    new_rows, _, _ = diff_snapshots(before, after)
    assert len(new_rows["target_indication_feasibility.tsv"]) == 1


def test_diff_snapshots_detects_status_upgrade_on_existing_candidate_not_as_new_row():
    """Exact regression scenario from the reviewer: a persistent candidate_id
    (Phase 5a design) does NOT change when its evidence strengthens, and
    candidate_queue.tsv has no count column -- so a NEEDS_REVIEW ->
    AUTO_HIGH_CONFIDENCE promotion is invisible to both new-row detection
    and count-based 'deepened' detection. status_changes is the only
    mechanism that can see it, and it must be surfaced as a Tier A upgrade."""
    before = {"candidate_queue.tsv": _df([{
        "candidate_id": "X", "candidate_label": "Conference-only Candidate",
        "source": "conference_abstract_corpus", "confidence": "0.4",
        "validation_status": "NEEDS_REVIEW", "modality_classification": "ADC",
    }])}
    after = {"candidate_queue.tsv": _df([{
        "candidate_id": "X", "candidate_label": "Conference-only Candidate",
        "source": "conference_abstract_corpus;clinicaltrials", "confidence": "0.8",
        "validation_status": "AUTO_HIGH_CONFIDENCE", "modality_classification": "ADC",
    }])}
    new_rows, deepened, status_changes = diff_snapshots(before, after)
    assert new_rows == {}  # NOT a new entity -- same persistent candidate_id
    assert deepened == {}
    changes = status_changes["candidate_queue.tsv"]
    by_field = {c["field"]: c for c in changes}
    assert by_field["validation_status"]["before"] == "NEEDS_REVIEW"
    assert by_field["validation_status"]["after"] == "AUTO_HIGH_CONFIDENCE"
    assert by_field["validation_status"]["tier_a_upgrade"] is True
    assert "source" in by_field
    assert "confidence" in by_field
    assert by_field["confidence"]["tier_a_upgrade"] is False  # only validation_status/status drive tier A


def test_diff_snapshots_status_change_ignores_unwatched_free_text_fields():
    before = {"candidate_queue.tsv": _df([{
        "candidate_id": "X", "candidate_label": "Foo", "context": "old sentence",
        "source": "s1", "confidence": "0.5", "validation_status": "NEEDS_REVIEW",
        "modality_classification": "ADC",
    }])}
    after = {"candidate_queue.tsv": _df([{
        "candidate_id": "X", "candidate_label": "Foo", "context": "brand new sentence text",
        "source": "s1", "confidence": "0.5", "validation_status": "NEEDS_REVIEW",
        "modality_classification": "ADC",
    }])}
    _, _, status_changes = diff_snapshots(before, after)
    assert status_changes == {}  # `context` is not a watched decision-relevant field


def test_diff_snapshots_detects_new_catalog_asset():
    """PR #33: a brand-new asset_id in adc_asset_universe.tsv is a new-
    entity event, tiered by its catalog_status."""
    before = {"adc_asset_universe.tsv": _df([{"asset_id": "NAR_1", "canonical_name": "Existing", "catalog_status": "REFERENCE_CONFIRMED"}])}
    after = {"adc_asset_universe.tsv": _df([
        {"asset_id": "NAR_1", "canonical_name": "Existing", "catalog_status": "REFERENCE_CONFIRMED"},
        {"asset_id": "OURS_2", "canonical_name": "Brand New Asset", "catalog_status": "NEEDS_REVIEW"},
    ])}
    new_rows, deepened, status_changes = diff_snapshots(before, after)
    assert len(new_rows["adc_asset_universe.tsv"]) == 1
    new_row = new_rows["adc_asset_universe.tsv"][0]
    assert new_row["asset_id"] == "OURS_2"
    assert new_row["_tier"] == "B"  # NEEDS_REVIEW
    assert "adc_asset_universe.tsv" not in deepened
    assert status_changes == {}


def test_diff_snapshots_detects_catalog_status_upgrade_as_tier_a():
    """Exact reviewer scenario this wiring exists for: an OURS-only asset
    (persistent asset_id, per candidate_id_for_name()'s stability
    contract) whose catalog_status is independently upgraded into
    MULTISOURCE_CONFIRMED -- e.g. after the round-2 compound-identifier
    fix resolved a candidate against its NAR row -- must surface as a
    Tier A upgrade, not a new row (the asset_id itself never changes)."""
    before = {"adc_asset_universe.tsv": _df([
        {"asset_id": "OURS_1", "canonical_name": "REGN5093-M114", "catalog_status": "NEEDS_REVIEW",
         "adc_scope": "PRESUMED_ADC", "sources": "europe_pmc", "aliases": "", "development_codes": "",
         "nct_ids": "", "highest_stage": "", "development_status": ""},
    ])}
    after = {"adc_asset_universe.tsv": _df([
        {"asset_id": "OURS_1", "canonical_name": "REGN5093-M114", "catalog_status": "MULTISOURCE_CONFIRMED",
         "adc_scope": "PRESUMED_ADC", "sources": "clinicaltrials; europe_pmc", "aliases": "", "development_codes": "",
         "nct_ids": "NCT04982224", "highest_stage": "Phase2", "development_status": "Phase 1/2"},
    ])}
    new_rows, deepened, status_changes = diff_snapshots(before, after)
    assert new_rows == {}
    assert deepened == {}
    changes = status_changes["adc_asset_universe.tsv"]
    by_field = {c["field"]: c for c in changes}
    assert by_field["catalog_status"]["before"] == "NEEDS_REVIEW"
    assert by_field["catalog_status"]["after"] == "MULTISOURCE_CONFIRMED"
    assert by_field["catalog_status"]["tier_a_upgrade"] is True
    assert by_field["sources"]["tier_a_upgrade"] is False  # a new evidence source, not a confirmation-tier upgrade
    assert "nct_ids" in by_field  # a newly-added NCT id
    assert "highest_stage" in by_field  # a clinical-stage advance


def test_diff_snapshots_detects_alias_merge_and_adc_scope_change():
    """PR #32's alias/dev-code crosswalk merges an evidence into an
    existing asset's own aliases/development_codes fields -- must be
    visible as a status change, and an independently-resolved adc_scope
    must be tracked separately from catalog_status."""
    before = {"adc_asset_universe.tsv": _df([
        {"asset_id": "OURS_3", "canonical_name": "Glembatumumab vedotin", "catalog_status": "SINGLE_STRONG_SOURCE",
         "adc_scope": "REFERENCE_UNCLASSIFIED", "sources": "conference_abstract_corpus", "aliases": "",
         "development_codes": "", "nct_ids": "", "highest_stage": "", "development_status": ""},
    ])}
    after = {"adc_asset_universe.tsv": _df([
        {"asset_id": "OURS_3", "canonical_name": "Glembatumumab vedotin", "catalog_status": "SINGLE_STRONG_SOURCE",
         "adc_scope": "PRESUMED_ADC", "sources": "conference_abstract_corpus", "aliases": "",
         "development_codes": "CDX-011", "nct_ids": "", "highest_stage": "", "development_status": ""},
    ])}
    _, _, status_changes = diff_snapshots(before, after)
    by_field = {c["field"]: c for c in status_changes["adc_asset_universe.tsv"]}
    assert by_field["development_codes"]["after"] == "CDX-011"  # alias/dev-code crosswalk merge
    assert by_field["adc_scope"]["before"] == "REFERENCE_UNCLASSIFIED"
    assert by_field["adc_scope"]["after"] == "PRESUMED_ADC"
    assert "catalog_status" not in by_field  # unchanged in this scenario


def test_tier_for_row_candidate_queue_promoted_is_tier_a():
    assert _tier_for_row("candidate_queue.tsv", {"validation_status": "PROMOTED"}) == "A"
    assert _tier_for_row("candidate_queue.tsv", {"validation_status": "AUTO_HIGH_CONFIDENCE"}) == "A"
    assert _tier_for_row("candidate_queue.tsv", {"validation_status": "NEEDS_REVIEW"}) == "B"


def test_tier_for_row_component_status_ladder():
    assert _tier_for_row("adc_platforms.tsv", {"status": "VALIDATED"}) == "A"
    assert _tier_for_row("adc_platforms.tsv", {"status": "OBSERVED"}) == "B"
    assert _tier_for_row("adc_payloads.tsv", {"status": "INFERRED"}) == "C"


def test_tier_for_row_adc_candidates_always_tier_a():
    assert _tier_for_row("adc_candidates.tsv", {"status": "VALIDATED"}) == "A"


def test_tier_for_row_indications_is_tier_c():
    assert _tier_for_row("adc_indications.tsv", {"indication": "Breast cancer"}) == "C"


def test_tier_for_row_catalog_status_ladder():
    """PR #33: adc_asset_universe.tsv is tiered by catalog_status (PR
    #30's evidence-strength axis), not by adc_scope."""
    assert _tier_for_row("adc_asset_universe.tsv", {"catalog_status": "REFERENCE_CONFIRMED"}) == "A"
    assert _tier_for_row("adc_asset_universe.tsv", {"catalog_status": "MULTISOURCE_CONFIRMED"}) == "A"
    assert _tier_for_row("adc_asset_universe.tsv", {"catalog_status": "SINGLE_STRONG_SOURCE"}) == "B"
    assert _tier_for_row("adc_asset_universe.tsv", {"catalog_status": "NEEDS_REVIEW"}) == "B"
    assert _tier_for_row("adc_asset_universe.tsv", {"catalog_status": "EXCLUDED_ADJACENT_MODALITY"}) == "C"


def test_read_feasibility_snapshot_missing_files_returns_empty_frames(tmp_path):
    snapshot = read_feasibility_snapshot(tmp_path)
    assert all(df.empty for df in snapshot.values())
    assert "adc_candidates.tsv" in snapshot
    assert "adc_asset_universe.tsv" not in snapshot  # catalog_dir not passed -- not tracked


def test_read_feasibility_snapshot_includes_catalog_dir_when_given(tmp_path):
    feasibility_dir = tmp_path / "feasibility"
    catalog_dir = tmp_path / "catalog"
    feasibility_dir.mkdir()
    catalog_dir.mkdir()
    (catalog_dir / "adc_asset_universe.tsv").write_text("asset_id\tcanonical_name\nA1\tFoo\n", encoding="utf-8")

    snapshot = read_feasibility_snapshot(feasibility_dir, catalog_dir)
    assert "adc_asset_universe.tsv" in snapshot
    assert list(snapshot["adc_asset_universe.tsv"]["asset_id"]) == ["A1"]


def test_make_delta_dir_never_overwrites_same_day(tmp_path):
    first = make_delta_dir(tmp_path, "2026-08-24")
    second = make_delta_dir(tmp_path, "2026-08-24")
    third = make_delta_dir(tmp_path, "2026-08-24")
    assert first != second != third
    assert first.exists() and second.exists() and third.exists()
    assert second.name == "2026-08-24_run2"
    assert third.name == "2026-08-24_run3"


def test_run_acquisition_stage_isolates_one_jobs_failure_from_others(tmp_path, monkeypatch):
    """One job's failure must not prevent other jobs from being attempted
    -- Prompt.md section 31's 'must not create coupling' extends to
    failure isolation (Gate 5's 'visible/retryable failures')."""
    import subprocess

    calls = []

    def fake_run(cmd, cwd, capture_output, text):
        job_name = cmd[3]
        calls.append(job_name)
        if job_name == "pubmed":
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    outcomes = run_acquisition_stage(["pubmed", "europe_pmc", "crossref"], tmp_path)

    assert calls == ["pubmed", "europe_pmc", "crossref"]  # all three attempted despite pubmed failing
    by_name = {o.name: o for o in outcomes}
    assert by_name["pubmed"].ok is False
    assert by_name["pubmed"].returncode == 1
    assert by_name["europe_pmc"].ok is True
    assert by_name["crossref"].ok is True


def test_run_derivation_stage_skips_downstream_steps_after_a_failure(tmp_path, monkeypatch):
    """Derivation is a fixed dependency chain, not independent siblings --
    if candidate_queue.py fails, feasibility_entities.py,
    component_coverage_audit.py, and build_adc_asset_universe.py (PR #33)
    must NOT run against its stale output."""
    import subprocess

    calls = []

    def fake_run(cmd, cwd, capture_output, text):
        script = cmd[1]
        calls.append(script)
        if "candidate_queue.py" in script:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    outcomes = run_derivation_stage(tmp_path, tmp_path, tmp_path)

    assert len(calls) == 1  # only candidate_queue.py was actually invoked
    by_name = {o.name: o for o in outcomes}
    assert by_name["candidate_queue"].ok is False
    assert by_name["candidate_queue"].skipped is False
    assert by_name["feasibility_entities"].skipped is True
    assert by_name["feasibility_entities"].ok is False
    assert by_name["component_coverage_audit"].skipped is True
    assert by_name["component_coverage_audit"].ok is False
    assert by_name["build_adc_asset_universe"].skipped is True
    assert by_name["build_adc_asset_universe"].ok is False


def test_run_derivation_stage_all_steps_run_when_none_fail(tmp_path, monkeypatch):
    import subprocess

    calls = []

    def fake_run(cmd, cwd, capture_output, text):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    outcomes = run_derivation_stage(tmp_path, tmp_path, tmp_path)

    assert len(calls) == 4
    assert all(o.ok and not o.skipped for o in outcomes)
    assert [o.name for o in outcomes] == [
        "candidate_queue", "feasibility_entities", "component_coverage_audit", "build_adc_asset_universe",
    ]
    catalog_cmd = calls[3]
    assert "build_adc_asset_universe.py" in catalog_cmd[1]
    assert "--nar-dir" in catalog_cmd
    assert str(tmp_path / "adc_asset_universe.tsv") in catalog_cmd
    assert str(tmp_path / "adc_clinical_development.tsv") in catalog_cmd


def test_main_incomplete_derivation_returns_nonzero_and_skips_entity_diff(tmp_path, monkeypatch):
    """Partial derivation must never be diffed against the pre-run snapshot
    as if it were a complete re-derivation -- DELTA_STATUS must say so and
    main() must return nonzero (cron/automation visibility)."""
    import subprocess

    feasibility_dir = tmp_path / "feasibility"
    feasibility_dir.mkdir()
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    delta_output = tmp_path / "delta"

    def fake_run(cmd, cwd, capture_output, text):
        script = cmd[1]
        if "candidate_queue.py" in script:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [
        "update_breadth.py", "--skip-acquisition",
        "--data-dir", str(tmp_path), "--feasibility-dir", str(feasibility_dir),
        "--catalog-dir", str(catalog_dir), "--delta-output", str(delta_output),
    ])

    rc = update_breadth_main()
    assert rc == 1

    delta_dirs = list(delta_output.iterdir())
    assert len(delta_dirs) == 1
    md = (delta_dirs[0] / "ADC_BREADTH_DELTA.md").read_text()
    assert "DELTA_STATUS: INCOMPLETE_DERIVATION" in md
    assert "SKIPPED_UPSTREAM_FAILURE" in md


def test_build_delta_markdown_incomplete_derivation_omits_entity_sections():
    result = DeltaResult(
        run_started_at="2026-08-25T00:00:00Z",
        job_outcomes=[],
        derivation_outcomes=[
            JobRunOutcome(name="candidate_queue", ok=False, returncode=1, tail_stdout="", tail_stderr="boom"),
            JobRunOutcome(name="feasibility_entities", ok=False, returncode=-2, tail_stdout="", tail_stderr="SKIPPED_UPSTREAM_FAILURE", skipped=True),
        ],
        delta_status="INCOMPLETE_DERIVATION",
    )
    md = build_delta_markdown(result)
    assert "DELTA_STATUS: INCOMPLETE_DERIVATION" in md
    assert "SKIPPED_UPSTREAM_FAILURE" in md
    assert "New entities this run" not in md


def test_build_delta_markdown_reports_tiers_and_failures():
    result = DeltaResult(
        run_started_at="2026-08-24T00:00:00Z",
        job_outcomes=[
            JobRunOutcome(name="pubmed", ok=False, returncode=1, tail_stdout="", tail_stderr="boom"),
            JobRunOutcome(name="europe_pmc", ok=True, returncode=0, tail_stdout="ok", tail_stderr=""),
        ],
        derivation_outcomes=[JobRunOutcome(name="candidate_queue", ok=True, returncode=0, tail_stdout="", tail_stderr="")],
        new_rows_by_table={
            "adc_candidates.tsv": [{"entity_id": "A2", "canonical_label": "Brand New", "_tier": "A"}],
            "adc_platforms.tsv": [{"entity_id": "P2", "canonical_label": "NewPlatform", "_tier": "B"}],
        },
        deepened_by_table={"adc_payloads.tsv": [(("PAY1",), 3, 5)]},
        status_changes_by_table={
            "candidate_queue.tsv": [
                {"key": ("X",), "field": "validation_status", "before": "NEEDS_REVIEW", "after": "AUTO_HIGH_CONFIDENCE", "tier_a_upgrade": True},
                {"key": ("X",), "field": "source", "before": "conference", "after": "conference;clinicaltrials", "tier_a_upgrade": False},
            ],
        },
    )
    md = build_delta_markdown(result)
    assert "Tier A" in md
    assert "Brand New" in md
    assert "NewPlatform" in md
    assert "pubmed: FAILED (exit 1)" in md
    assert "europe_pmc: OK" in md
    assert "adc_payloads.tsv" in md  # deepened section
    assert "Status / confidence upgrades" in md
    assert "NEEDS_REVIEW" in md and "AUTO_HIGH_CONFIDENCE" in md
    upgrades_section = md.split("Status / confidence upgrades")[1].split("## All status/field changes")[0]
    assert "validation_status" in upgrades_section
    assert "source" not in upgrades_section  # non-upgrade change must NOT appear in the upgrades subsection


def test_main_unknown_job_name_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["update_breadth.py", "--jobs", "not_a_real_job", "--data-dir", str(tmp_path)])
    try:
        update_breadth_main()
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "unknown job name" in str(exc)
