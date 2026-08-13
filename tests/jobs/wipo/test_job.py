import argparse
import re
from urllib.parse import parse_qs, urlparse

import pandas as pd
import responses

from jobs.wipo.client import OPS_AUTH_URL, OPS_SEARCH_URL
from jobs.wipo.job import WIPOJob

QUERIES_YAML = """
queries:
  - query_id: WIPO_TEST_PHRASE
    query_version: 1
    query_text: 'pn=WO and ab="antibody-drug conjugate"'
    purpose: test
    active: true
"""

TWO_QUERY_YAML = """
queries:
  - query_id: WIPO_TEST_A
    query_version: 1
    query_text: 'pn=WO and ab=alpha'
    purpose: test
    active: true
  - query_id: WIPO_TEST_B
    query_version: 3
    query_text: 'pn=WO and ab=beta'
    purpose: test
    active: true
"""


def _hit(country="WO", doc_number="2026000001", kind="A1", family_id="1"):
    return {"country": country, "doc_number": doc_number, "kind": kind, "family_id": family_id}


def _pub_id(h):
    return f"{h['country']}{h['doc_number']}{h['kind']}"


def _docdb(h):
    return f"{h['country']}.{h['doc_number']}.{h['kind']}"


def _search_xml(hits, total):
    entries = "".join(
        f'<ops:publication-reference family-id="{h["family_id"]}">'
        f'<document-id document-id-type="docdb">'
        f'<country>{h["country"]}</country><doc-number>{h["doc_number"]}</doc-number><kind>{h["kind"]}</kind>'
        f"</document-id></ops:publication-reference>"
        for h in hits
    )
    return (
        '<?xml version="1.0"?>'
        '<ops:world-patent-data xmlns="http://www.epo.org/exchange" xmlns:ops="http://ops.epo.org">'
        f'<ops:biblio-search total-result-count="{total}"><ops:search-result>{entries}</ops:search-result></ops:biblio-search>'
        "</ops:world-patent-data>"
    ).encode()


def _biblio_xml(h, title="A Title", abstract_text="An abstract."):
    return (
        '<?xml version="1.0"?>'
        '<ops:world-patent-data xmlns="http://www.epo.org/exchange" xmlns:ops="http://ops.epo.org">'
        "<exchange-documents>"
        f'<exchange-document family-id="{h["family_id"]}" country="{h["country"]}" doc-number="{h["doc_number"]}" kind="{h["kind"]}">'
        "<bibliographic-data>"
        '<application-reference doc-id="1"><document-id document-id-type="epodoc">'
        "<doc-number>WOAPP1</doc-number><date>20200101</date></document-id></application-reference>"
        '<priority-claims><priority-claim sequence="1" kind="national"><document-id document-id-type="epodoc">'
        "<doc-number>US1P</doc-number><date>20190101</date></document-id></priority-claim></priority-claims>"
        f'<invention-title lang="en">{title}</invention-title>'
        "<parties><applicants><applicant sequence=\"1\" data-format=\"original\">"
        "<applicant-name><name>Test Applicant</name></applicant-name></applicant></applicants>"
        "<inventors><inventor sequence=\"1\" data-format=\"original\">"
        "<inventor-name><name>Test Inventor</name></inventor-name></inventor></inventors></parties>"
        "</bibliographic-data>"
        f'<abstract lang="en"><p>{abstract_text}</p></abstract>'
        "</exchange-document></exchange-documents></ops:world-patent-data>"
    ).encode()


def _register_ops(query_to_hits: dict, biblio_by_docdb: dict | None = None):
    biblio_by_docdb = biblio_by_docdb or {}
    responses.add(responses.POST, OPS_AUTH_URL, json={"access_token": "tok-123", "expires_in": 1199})

    def _search_callback(request):
        qs = parse_qs(urlparse(request.url).query)
        q = qs.get("q", [""])[0]
        rng = qs.get("Range", ["1-100"])[0]
        begin, end = (int(x) for x in rng.split("-"))
        hits = query_to_hits.get(q, [])
        page = hits[begin - 1 : end]
        return (200, {}, _search_xml(page, total=len(hits)))

    responses.add_callback(responses.GET, OPS_SEARCH_URL, callback=_search_callback)

    def _biblio_callback(request):
        docdb = request.url.rsplit("/publication/docdb/", 1)[1].rsplit("/biblio", 1)[0]
        xml = biblio_by_docdb.get(docdb)
        if xml is None:
            return (404, {}, '<fault><code>SERVER.EntityNotFound</code></fault>')
        return (200, {}, xml)

    responses.add_callback(
        responses.GET,
        re.compile(r"https://ops\.epo\.org/3\.2/rest-services/published-data/publication/docdb/.*"),
        callback=_biblio_callback,
    )


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None,
        output=str(tmp_path / "DATA"), queries_file=str(tmp_path / "queries.yaml"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch, queries_yaml=QUERIES_YAML):
    (tmp_path / "queries.yaml").write_text(queries_yaml)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPS_CONSUMER_KEY", "key")
    monkeypatch.setenv("OPS_CONSUMER_SECRET", "secret")
    import jobs.wipo.job as job_module
    monkeypatch.setattr(job_module, "SEARCH_RATE_LIMIT", 1000)
    monkeypatch.setattr(job_module, "BIBLIO_RATE_LIMIT", 1000)


def _manifest_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "wipo.parquet")


def _attempts_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "wipo_attempts.parquet")


@responses.activate
def test_dry_run_discovers_but_does_not_download(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    h = _hit()
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]})

    result = WIPOJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 1
    assert result.records_downloaded == 0
    assert not (tmp_path / "DATA" / "manifests" / "wipo.parquet").exists()


@responses.activate
def test_full_run_writes_manifest_discovery_and_attempts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    h = _hit()
    _register_ops(
        {'pn=WO and ab="antibody-drug conjugate"': [h]},
        {_docdb(h): _biblio_xml(h, title="CD26 ADC")},
    )

    result = WIPOJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["source_record_id"] == _pub_id(h)
    assert df.iloc[0]["title"] == "CD26 ADC"
    assert df.iloc[0]["application_number"] == "WOAPP1"
    assert df.iloc[0]["applicants"] == ["Test Applicant"]

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "wipo_discovery.parquet")
    assert discovery_df.iloc[0]["source_record_id"] == _pub_id(h)
    assert discovery_df.iloc[0]["query_id"] == "WIPO_TEST_PHRASE"


@responses.activate
def test_already_successful_publication_skipped_without_ops_request(tmp_path, monkeypatch):
    """WIPO's core deliberate deviation: once a publication_number succeeds,
    it must never be re-fetched (biblio data is treated as immutable)."""
    _setup(tmp_path, monkeypatch)
    h = _hit()
    _register_ops(
        {'pn=WO and ab="antibody-drug conjugate"': [h]},
        {_docdb(h): _biblio_xml(h)},
    )
    WIPOJob().run(_base_args(tmp_path))

    responses.calls.reset()
    result2 = WIPOJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 0
    assert result2.records_skipped_unchanged == 1
    biblio_calls = [c for c in responses.calls if "/publication/docdb/" in c.request.url]
    assert biblio_calls == []  # no OPS request at all for the already-successful publication


@responses.activate
def test_failed_publication_retried_on_next_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    h = _hit()
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]})  # no biblio registered -> 404

    result1 = WIPOJob().run(_base_args(tmp_path))
    assert result1.records_failed == 1

    responses.calls.reset()
    _register_ops(
        {'pn=WO and ab="antibody-drug conjugate"': [h]},
        {_docdb(h): _biblio_xml(h)},
    )
    result2 = WIPOJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 1  # retried despite no --resume flag, since it's unresolved


@responses.activate
def test_limit_prioritizes_fresh_over_backlog(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, queries_yaml=TWO_QUERY_YAML)
    old_failed = _hit(doc_number="2020000001", family_id="10")
    _register_ops({"pn=WO and ab=alpha": [old_failed], "pn=WO and ab=beta": []})
    WIPOJob().run(_base_args(tmp_path))  # old_failed fails (no biblio registered)

    responses.calls.reset()
    new_fresh = _hit(doc_number="2026000002", family_id="20")
    _register_ops(
        {"pn=WO and ab=alpha": [old_failed, new_fresh], "pn=WO and ab=beta": []},
        {_docdb(new_fresh): _biblio_xml(new_fresh)},
    )
    result = WIPOJob().run(_base_args(tmp_path, limit=1))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert _pub_id(new_fresh) in set(df["source_record_id"])  # fresh got the single --limit slot
    assert _pub_id(old_failed) not in set(df["source_record_id"])  # backlog didn't starve it out


@responses.activate
def test_since_until_apply_as_server_side_cql_filter(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    h = _hit()
    query_with_date = 'pn=WO and ab="antibody-drug conjugate" and pd within "20200101,20201231"'
    _register_ops({query_with_date: [h]}, {_docdb(h): _biblio_xml(h)})

    result = WIPOJob().run(_base_args(tmp_path, since="2020-01-01", until="2020-12-31"))

    assert result.records_discovered == 1
    search_calls = [c for c in responses.calls if c.request.url.startswith(OPS_SEARCH_URL)]
    assert 'pd within "20200101,20201231"' in search_calls[0].request.params["q"]


@responses.activate
def test_query_version_from_registry_propagates_not_hardcoded(tmp_path, monkeypatch):
    """WIPO_TEST_B is registered at query_version 3 (not 1) -- if the code
    hardcoded query_version instead of reading it from the registry, this
    would fail."""
    _setup(tmp_path, monkeypatch, queries_yaml=TWO_QUERY_YAML)
    h = _hit()
    _register_ops({"pn=WO and ab=alpha": [], "pn=WO and ab=beta": [h]}, {_docdb(h): _biblio_xml(h)})

    WIPOJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "wipo_discovery.parquet")
    row = discovery_df[discovery_df["query_id"] == "WIPO_TEST_B"].iloc[0]
    assert row["query_version"] == 3


@responses.activate
def test_multiple_queries_each_get_their_own_discovery_row(tmp_path, monkeypatch):
    """Never collapse multi-query provenance -- a publication discovered by
    two queries gets two discovery ledger rows, one manifest row."""
    _setup(tmp_path, monkeypatch, queries_yaml=TWO_QUERY_YAML)
    h = _hit()
    _register_ops({"pn=WO and ab=alpha": [h], "pn=WO and ab=beta": [h]}, {_docdb(h): _biblio_xml(h)})

    WIPOJob().run(_base_args(tmp_path))

    discovery_df = pd.read_parquet(tmp_path / "DATA" / "manifests" / "wipo_discovery.parquet")
    matching = discovery_df[discovery_df["source_record_id"] == _pub_id(h)]
    assert len(matching) == 2
    assert set(matching["query_id"]) == {"WIPO_TEST_A", "WIPO_TEST_B"}
    assert len(_manifest_df(tmp_path)) == 1


@responses.activate
def test_empty_result_set_produces_empty_manifest_without_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': []})

    result = WIPOJob().run(_base_args(tmp_path))

    assert result.records_discovered == 0
    assert result.records_downloaded == 0
