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
        dry_run=False, limit=None, resume=False, since=None, until=None, refresh=False,
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
    """Default-run efficiency behavior: once a publication_number succeeds,
    it is not refetched on a plain subsequent run (--refresh opts back in)."""
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
def test_third_consecutive_run_still_skips_without_fetch(tmp_path, monkeypatch):
    """Regression test for the round-1 bug: _resolved_publication_ids() must
    treat a "skipped_unchanged" most-recent-attempt as resolved too, or a
    publication falls back to "fresh" and gets needlessly refetched on the
    THIRD run (the second run's attempt row is skipped_unchanged, not
    success)."""
    _setup(tmp_path, monkeypatch)
    h = _hit()
    _register_ops(
        {'pn=WO and ab="antibody-drug conjugate"': [h]},
        {_docdb(h): _biblio_xml(h)},
    )
    WIPOJob().run(_base_args(tmp_path))  # run 1: success
    WIPOJob().run(_base_args(tmp_path))  # run 2: skipped_unchanged (fast path)

    responses.calls.reset()
    result3 = WIPOJob().run(_base_args(tmp_path))  # run 3: must still skip, not re-fetch

    assert result3.records_downloaded == 0
    assert result3.records_skipped_unchanged == 1
    biblio_calls = [c for c in responses.calls if "/publication/docdb/" in c.request.url]
    assert biblio_calls == []


@responses.activate
def test_refresh_flag_detects_changed_content_and_creates_new_version(tmp_path, monkeypatch):
    """OPS bibliographic data CAN change (corrections) -- --refresh must
    re-fetch an already-successful publication and version-bump on a
    genuine content change."""
    _setup(tmp_path, monkeypatch)
    h = _hit()
    _register_ops(
        {'pn=WO and ab="antibody-drug conjugate"': [h]},
        {_docdb(h): _biblio_xml(h, title="Original Title")},
    )
    WIPOJob().run(_base_args(tmp_path))

    responses.calls.reset()
    _register_ops(
        {'pn=WO and ab="antibody-drug conjugate"': [h]},
        {_docdb(h): _biblio_xml(h, title="Corrected Title")},
    )
    result = WIPOJob().run(_base_args(tmp_path, refresh=True))

    assert result.records_downloaded == 1
    biblio_calls = [c for c in responses.calls if "/publication/docdb/" in c.request.url]
    assert len(biblio_calls) == 1  # DID re-fetch under --refresh

    df = _manifest_df(tmp_path)
    matching = df[df["source_record_id"] == _pub_id(h)].sort_values("version")
    assert list(matching["version"]) == [1, 2]
    assert list(matching["title"]) == ["Original Title", "Corrected Title"]


@responses.activate
def test_refresh_flag_unchanged_content_stays_at_same_version(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    h = _hit()
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]}, {_docdb(h): _biblio_xml(h)})
    WIPOJob().run(_base_args(tmp_path))

    responses.calls.reset()
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]}, {_docdb(h): _biblio_xml(h)})
    result = WIPOJob().run(_base_args(tmp_path, refresh=True))

    assert result.records_downloaded == 0
    assert result.records_skipped_unchanged == 1
    biblio_calls = [c for c in responses.calls if "/publication/docdb/" in c.request.url]
    assert len(biblio_calls) == 1  # refresh DID check, just found no change
    df = _manifest_df(tmp_path)
    assert list(df[df["source_record_id"] == _pub_id(h)]["version"]) == [1]


@responses.activate
def test_raw_xml_persisted_before_parser_crash(tmp_path, monkeypatch):
    """Raw OPS bytes must be durable BEFORE parsing is attempted -- a
    parser crash must not erase the evidence that caused it."""
    _setup(tmp_path, monkeypatch)
    h = _hit()
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]}, {_docdb(h): _biblio_xml(h)})

    import jobs.wipo.job as job_module

    def _boom(_bytes):
        raise RuntimeError("simulated parser bug")

    monkeypatch.setattr(job_module, "parse_biblio_response", _boom)

    try:
        WIPOJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    raw_path = tmp_path / "DATA" / "raw" / "wipo" / _pub_id(h) / "v1.xml"
    assert raw_path.exists()
    assert raw_path.read_bytes() == _biblio_xml(h)

    attempts = _attempts_df(tmp_path)
    row = attempts[attempts["source_record_id"] == _pub_id(h)].iloc[0]
    assert row["status"] == "parse_failed"
    assert row["version"] == 1


@responses.activate
def test_raw_snapshot_version_survives_repeated_parse_failures_with_changing_content(tmp_path, monkeypatch):
    """Round-2 regression test: raw version numbering must be driven by a
    checkpoint namespace that updates unconditionally on every raw write,
    NOT by one that only updates on parse success -- otherwise two
    genuinely different raw contents fetched across two parse-failing runs
    would both compute version=1 and the second write would silently
    overwrite the first's raw evidence."""
    _setup(tmp_path, monkeypatch)
    h = _hit()

    import jobs.wipo.job as job_module

    def _boom(_bytes):
        raise RuntimeError("simulated parser bug")

    monkeypatch.setattr(job_module, "parse_biblio_response", _boom)

    xml_a = _biblio_xml(h, title="Content A")
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]}, {_docdb(h): xml_a})
    try:
        WIPOJob().run(_base_args(tmp_path))
    except RuntimeError:
        pass

    responses.reset()
    xml_b = _biblio_xml(h, title="Content B")
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]}, {_docdb(h): xml_b})
    monkeypatch.setattr(job_module, "parse_biblio_response", _boom)
    try:
        WIPOJob().run(_base_args(tmp_path))
    except RuntimeError:
        pass

    raw_dir = tmp_path / "DATA" / "raw" / "wipo" / _pub_id(h)
    assert (raw_dir / "v1.xml").read_bytes() == xml_a  # untouched, not overwritten by content B
    assert (raw_dir / "v2.xml").read_bytes() == xml_b

    attempts = _attempts_df(tmp_path)
    parse_failed_rows = attempts[attempts["status"] == "parse_failed"].sort_values("attempted_at")
    assert list(parse_failed_rows["version"]) == [1, 2]


@responses.activate
def test_raw_checkpoint_state_is_disk_durable_before_downstream_crash(tmp_path, monkeypatch):
    """Round-3 regression: RAW_NAMESPACE's checkpoint state must be saved
    to DISK immediately after each raw write, not just updated in the
    in-memory checkpoint dict -- otherwise an uncaught exception ANYWHERE
    downstream of the raw write (not just a caught parser error) leaves
    the on-disk checkpoint believing an older, smaller version number is
    current, and a later run recomputes the same version and overwrites
    a raw file that a crashed run already wrote."""
    _setup(tmp_path, monkeypatch)
    h = _hit()

    xml_a = _biblio_xml(h, title="Content A")
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]}, {_docdb(h): xml_a})
    WIPOJob().run(_base_args(tmp_path))  # run 1: succeeds normally -> v1 = A

    import jobs.wipo.job as job_module
    original_new_manifest_row = job_module.new_manifest_row

    def _boom(**_kwargs):
        raise RuntimeError("simulated uncaught downstream bug (not a parse failure)")

    responses.reset()
    xml_b = _biblio_xml(h, title="Content B")
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]}, {_docdb(h): xml_b})
    monkeypatch.setattr(job_module, "new_manifest_row", _boom)
    try:
        WIPOJob().run(_base_args(tmp_path, refresh=True))  # run 2: raw v2 written, THEN an uncaught crash
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    monkeypatch.setattr(job_module, "new_manifest_row", original_new_manifest_row)

    responses.reset()
    xml_c = _biblio_xml(h, title="Content C")
    _register_ops({'pn=WO and ab="antibody-drug conjugate"': [h]}, {_docdb(h): xml_c})
    WIPOJob().run(_base_args(tmp_path, refresh=True))  # run 3: must create v3, not overwrite v2

    raw_dir = tmp_path / "DATA" / "raw" / "wipo" / _pub_id(h)
    assert (raw_dir / "v1.xml").read_bytes() == xml_a
    assert (raw_dir / "v2.xml").read_bytes() == xml_b  # must survive run 2's crash untouched
    assert (raw_dir / "v3.xml").read_bytes() == xml_c


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
