from adc_acquisition.company_registry import load_companies


def test_load_companies_from_real_registry():
    companies = load_companies("configs/company_registry.yaml")
    assert len(companies) >= 8
    assert all(c.company_id for c in companies)


def test_load_companies_ignores_unknown_job_specific_fields(tmp_path):
    """A job that only reads a subset of fields (e.g. SEC reading ciks)
    must not break when the registry gains fields another job needs (e.g.
    pipeline_urls) -- unknown YAML keys are silently dropped, not passed
    through to raise a TypeError."""
    path = tmp_path / "registry.yaml"
    path.write_text(
        """
companies:
  - company_id: acme
    canonical_name: Acme Inc.
    ciks: ["0000000001"]
    some_future_field_no_job_reads_yet: "should be ignored, not raise"
"""
    )
    companies = load_companies(path)
    assert len(companies) == 1
    assert companies[0].company_id == "acme"
    assert companies[0].ciks == ["0000000001"]


def test_load_companies_defaults_for_fields_not_present():
    path_text = """
companies:
  - company_id: minimal
    canonical_name: Minimal Inc.
"""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "registry.yaml"
        path.write_text(path_text)
        companies = load_companies(path)

    assert companies[0].ciks == []
    assert companies[0].pipeline_urls == []
    assert companies[0].active is True
    assert companies[0].investor_relations_url is None
    assert companies[0].parent_company_id is None


def test_load_companies_reads_parent_company_id(tmp_path):
    """An acquired company records ITS OWN acquirer's company_id
    structurally, not just in free-text notes -- lets downstream audit
    tooling resolve 'this asset's real current owner' without parsing
    prose."""
    path = tmp_path / "registry.yaml"
    path.write_text(
        """
companies:
  - company_id: acme_sub
    canonical_name: Acme Subsidiary Inc.
    parent_company_id: acme_parent
  - company_id: acme_parent
    canonical_name: Acme Parent Inc.
"""
    )
    companies = {c.company_id: c for c in load_companies(path)}
    assert companies["acme_sub"].parent_company_id == "acme_parent"
    assert companies["acme_parent"].parent_company_id is None
