import pytest

from adc_acquisition.query_registry import active_queries, load_queries


def test_load_queries_from_real_pubmed_config():
    queries = load_queries("configs/pubmed_queries.yaml")
    assert len(queries) >= 4
    assert all(q.query_id.startswith("PUBMED_ADC_") for q in queries)


def test_active_queries_filters_inactive(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text(
        """
queries:
  - query_id: A
    query_version: 1
    query_text: "x"
    purpose: p
    active: true
  - query_id: B
    query_version: 1
    query_text: "y"
    purpose: p
    active: false
"""
    )
    queries = load_queries(path)
    assert len(queries) == 2
    assert [q.query_id for q in active_queries(queries)] == ["A"]


def test_duplicate_query_id_raises(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text(
        """
queries:
  - query_id: A
    query_version: 1
    query_text: "x"
    purpose: p
    active: true
  - query_id: A
    query_version: 2
    query_text: "y"
    purpose: p
    active: true
"""
    )
    with pytest.raises(ValueError):
        load_queries(path)
