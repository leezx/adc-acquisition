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
)


def _df(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def test_diff_snapshots_detects_new_row_by_natural_key():
    before = {"adc_candidates.tsv": _df([{"entity_id": "A1", "canonical_label": "Existing"}])}
    after = {"adc_candidates.tsv": _df([
        {"entity_id": "A1", "canonical_label": "Existing"},
        {"entity_id": "A2", "canonical_label": "Brand New"},
    ])}
    new_rows, deepened = diff_snapshots(before, after)
    assert len(new_rows["adc_candidates.tsv"]) == 1
    assert new_rows["adc_candidates.tsv"][0]["entity_id"] == "A2"
    assert "adc_candidates.tsv" not in deepened


def test_diff_snapshots_no_change_produces_no_new_rows():
    same = {"adc_candidates.tsv": _df([{"entity_id": "A1", "canonical_label": "Existing"}])}
    new_rows, deepened = diff_snapshots(same, same)
    assert new_rows == {}
    assert deepened == {}


def test_diff_snapshots_detects_evidence_deepened_not_as_new_row():
    """An existing entity whose evidence_count grew must be reported as
    'deepened', never miscounted as a new-entity event."""
    before = {"adc_platforms.tsv": _df([{"entity_id": "P1", "evidence_count": "3", "status": "OBSERVED"}])}
    after = {"adc_platforms.tsv": _df([{"entity_id": "P1", "evidence_count": "5", "status": "OBSERVED"}])}
    new_rows, deepened = diff_snapshots(before, after)
    assert new_rows == {}
    assert deepened["adc_platforms.tsv"] == [(("P1",), 3, 5)]


def test_diff_snapshots_composite_key_for_target_indication():
    before = {"target_indication_feasibility.tsv": _df([])}
    after = {"target_indication_feasibility.tsv": _df([
        {"target_entity_id": "T1", "indication": "Breast cancer", "supporting_asset_count": "2"},
    ])}
    new_rows, _ = diff_snapshots(before, after)
    assert len(new_rows["target_indication_feasibility.tsv"]) == 1


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


def test_read_feasibility_snapshot_missing_files_returns_empty_frames(tmp_path):
    snapshot = read_feasibility_snapshot(tmp_path)
    assert all(df.empty for df in snapshot.values())
    assert "adc_candidates.tsv" in snapshot


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
    )
    md = build_delta_markdown(result)
    assert "Tier A" in md
    assert "Brand New" in md
    assert "NewPlatform" in md
    assert "pubmed: FAILED (exit 1)" in md
    assert "europe_pmc: OK" in md
    assert "adc_payloads.tsv" in md  # deepened section


def test_main_unknown_job_name_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["update_breadth.py", "--jobs", "not_a_real_job", "--data-dir", str(tmp_path)])
    try:
        update_breadth_main()
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "unknown job name" in str(exc)
