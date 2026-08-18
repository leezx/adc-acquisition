from jobs.known_adc_asset_expansion.asset_registry import KnownADCAsset
from jobs.known_adc_asset_expansion.query_templates import (
    epo_queries,
    europe_pmc_queries,
    pubmed_queries,
    uspto_queries,
    wipo_queries,
)


def _asset(asset_id="test_asset", canonical_name="Test Drug", aliases=None, dev_codes=None, ambiguous_identifiers=None):
    return KnownADCAsset(
        asset_id=asset_id, canonical_name=canonical_name, aliases=aliases or [], dev_codes=dev_codes or [],
        target="TEST_TARGET", company="Test Co", active=True,
        ambiguous_identifiers=ambiguous_identifiers or [],
    )


def test_ambiguous_identifier_is_qualified_with_canonical_name_pubmed():
    asset = _asset(aliases=["Polivy"], ambiguous_identifiers=["Polivy"])
    queries = pubmed_queries([asset])
    polivy_queries = [q for q in queries if '"Polivy"' in q["query_text"]]
    assert len(polivy_queries) == 1
    assert polivy_queries[0]["query_text"] == '"Polivy"[tiab] AND "Test Drug"[tiab]'


def test_non_ambiguous_identifier_stays_bare_pubmed():
    asset = _asset(aliases=["Polivy"], ambiguous_identifiers=[])  # not flagged ambiguous
    queries = pubmed_queries([asset])
    polivy_queries = [q for q in queries if "Polivy" in q["query_text"]]
    assert len(polivy_queries) == 1
    assert polivy_queries[0]["query_text"] == '"Polivy"[tiab]'  # bare, no qualifier


def test_ambiguous_identifier_qualified_across_all_bare_identifier_sources():
    asset = _asset(aliases=["Polivy"], ambiguous_identifiers=["Polivy"])
    europe_pmc_q = [q for q in europe_pmc_queries([asset]) if "Polivy" in q["query_text"]][0]
    wipo_q = [q for q in wipo_queries([asset]) if "Polivy" in q["query_text"]][0]
    epo_q = [q for q in epo_queries([asset]) if "Polivy" in q["query_text"]][0]
    uspto_q = [q for q in uspto_queries([asset]) if q["query_text"].startswith('"Polivy"')][0]

    assert "Test Drug" in europe_pmc_q["query_text"]
    assert "Test Drug" in wipo_q["query_text"]
    assert "Test Drug" in epo_q["query_text"]
    assert '"Polivy" AND "Test Drug"' == uspto_q["query_text"]


def test_ambiguous_identifier_query_id_still_deterministic_and_distinct():
    """The qualified query_text is still what query_id hashes -- changing
    canonical_name (or the identifier itself) still produces a new id, and
    the qualified query never collides with the unqualified form's id."""
    asset = _asset(aliases=["Polivy"], ambiguous_identifiers=["Polivy"])
    q1 = [q for q in pubmed_queries([asset]) if "Polivy" in q["query_text"]][0]

    asset_v2 = _asset(canonical_name="Renamed Drug", aliases=["Polivy"], ambiguous_identifiers=["Polivy"])
    q2 = [q for q in pubmed_queries([asset_v2]) if "Polivy" in q["query_text"]][0]

    assert q1["query_id"] != q2["query_id"]


def test_suffix_queries_unaffected_by_ambiguous_identifiers():
    """Suffix templates are always built from canonical_name, never a
    possibly-ambiguous alias/dev-code -- marking an alias ambiguous must
    not change suffix query behavior at all."""
    asset_plain = _asset(aliases=["Polivy"], ambiguous_identifiers=[])
    asset_marked = _asset(aliases=["Polivy"], ambiguous_identifiers=["Polivy"])
    suffix_plain = sorted(q["query_text"] for q in pubmed_queries([asset_plain]) if "patent" in q["query_text"])
    suffix_marked = sorted(q["query_text"] for q in pubmed_queries([asset_marked]) if "patent" in q["query_text"])
    assert suffix_plain == suffix_marked
