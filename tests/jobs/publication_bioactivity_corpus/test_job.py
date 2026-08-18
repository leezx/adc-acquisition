import argparse

import pandas as pd
import responses

from adc_acquisition import http_utils
from adc_acquisition.manifest import new_manifest_row, write_manifest
from jobs.publication_bioactivity_corpus.job import PublicationBioactivityCorpusJob, _query_text

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
IDCONV_BASE = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

PUBMED_EXTRA_FIELDS = ["pmid", "pmcid", "doi", "abstract", "authors", "journal", "publication_types", "mesh_terms"]
EPMC_EXTRA_FIELDS = ["epmc_source", "epmc_id", "pmid", "pmcid", "doi", "abstract", "journal", "is_open_access", "license", "in_pmc"]
CROSSREF_EXTRA_FIELDS = ["doi", "authors", "publisher", "container_title", "work_type", "published_date", "license_url", "references", "abstract"]


def _pubmed_row(pmid, doi=None, pmcid=None, pub_date="2026-01-01", version=1):
    return new_manifest_row(
        extra_fields=PUBMED_EXTRA_FIELDS,
        source="pubmed", source_record_id=pmid, source_record_type="literature_record",
        title=f"Title for {pmid}", url=None, publication_or_release_date=pub_date,
        retrieved_at="2026-01-01T00:00:00+00:00", query_id="PUBMED_TEST", query_text="q",
        raw_file_path="/dev/null", raw_format="xml", content_hash="deadbeef",
        download_status="success", http_status=200, license_or_access_note="test",
        parent_record_id=None, version=version, notes=None,
        pmid=pmid, pmcid=pmcid, doi=doi, abstract=None, authors=[], journal=None,
        publication_types=[], mesh_terms=[],
    )


def _europe_pmc_row(source_record_id, doi, pmcid=None, is_open_access=False, pub_date="2026-01-01", version=1):
    return new_manifest_row(
        extra_fields=EPMC_EXTRA_FIELDS,
        source="europe_pmc", source_record_id=source_record_id, source_record_type="literature_record",
        title=f"Title for {source_record_id}", url=None, publication_or_release_date=pub_date,
        retrieved_at="2026-01-01T00:00:00+00:00", query_id="EPMC_TEST", query_text="q",
        raw_file_path="/dev/null", raw_format="json", content_hash="deadbeef",
        download_status="success", http_status=200, license_or_access_note="test",
        parent_record_id=None, version=version, notes=None,
        epmc_source="MED", epmc_id=source_record_id.split(":")[-1], pmid=None, pmcid=pmcid, doi=doi,
        abstract=None, journal=None, is_open_access=is_open_access, license=None, in_pmc=bool(pmcid),
    )


def _crossref_row(doi, pub_date="2026-01-01", version=1):
    return new_manifest_row(
        extra_fields=CROSSREF_EXTRA_FIELDS,
        source="crossref", source_record_id=doi, source_record_type="crossref_work",
        title=f"Title for {doi}", url=None, publication_or_release_date=pub_date,
        retrieved_at="2026-01-01T00:00:00+00:00", query_id="CROSSREF_TEST", query_text="q",
        raw_file_path="/dev/null", raw_format="json", content_hash="deadbeef",
        download_status="success", http_status=200, license_or_access_note="test",
        parent_record_id=None, version=version, notes=None,
        doi=doi, authors=[], publisher="Test Publisher", container_title=None,
        work_type="journal-article", published_date=pub_date, license_url=None, references=[], abstract=None,
    )


def _fulltext_row(pmcid, parent_record_id, version=1):
    return new_manifest_row(
        source="europe_pmc", source_record_id=pmcid, source_record_type="fulltext_jats_xml",
        title=None, url=None, publication_or_release_date=None,
        retrieved_at="2026-01-01T00:00:00+00:00", query_id=None, query_text=None,
        raw_file_path="/dev/null", raw_format="xml", content_hash="deadbeef",
        download_status="success", http_status=200, license_or_access_note="test",
        parent_record_id=parent_record_id, version=version, notes=None,
    )


def _base_args(tmp_path, **overrides):
    defaults = dict(
        dry_run=False, limit=None, resume=False, since=None, until=None, refresh=False,
        output=str(tmp_path / "DATA"),
        pubmed_manifest=str(tmp_path / "DATA" / "manifests" / "pubmed.parquet"),
        europe_pmc_manifest=str(tmp_path / "DATA" / "manifests" / "europe_pmc.parquet"),
        crossref_manifest=str(tmp_path / "DATA" / "manifests" / "crossref.parquet"),
        europe_pmc_fulltext_manifest=str(tmp_path / "DATA" / "manifests" / "europe_pmc_fulltext.parquet"),
        contact_email="test-runner@adc-acquisition-tests.org",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _setup(tmp_path, monkeypatch, pubmed_rows=None, europe_pmc_rows=None, crossref_rows=None, fulltext_rows=None):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UNPAYWALL_CONTACT_EMAIL", "test-runner@adc-acquisition-tests.org")
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)
    manifests_dir = tmp_path / "DATA" / "manifests"
    if pubmed_rows:
        write_manifest(pubmed_rows, manifests_dir / "pubmed.parquet", extra_fields=PUBMED_EXTRA_FIELDS)
    if europe_pmc_rows:
        write_manifest(europe_pmc_rows, manifests_dir / "europe_pmc.parquet", extra_fields=EPMC_EXTRA_FIELDS)
    if crossref_rows:
        write_manifest(crossref_rows, manifests_dir / "crossref.parquet", extra_fields=CROSSREF_EXTRA_FIELDS)
    if fulltext_rows:
        write_manifest(fulltext_rows, manifests_dir / "europe_pmc_fulltext.parquet")


def _mock_unpaywall(doi, is_oa=True, oa_status="gold", locations=None, status=200):
    if locations is None:
        locations = [{"host_type": "publisher", "url": f"https://example.org/{doi}.pdf", "url_for_pdf": f"https://example.org/{doi}.pdf"}]
    body = {
        "doi": doi, "is_oa": is_oa, "oa_status": oa_status,
        "best_oa_location": locations[0] if locations else None,
        "oa_locations": locations,
    }
    responses.add(responses.GET, f"{UNPAYWALL_BASE}/{doi}", json=body, status=status)


def _mock_unpaywall_404(doi):
    responses.add(responses.GET, f"{UNPAYWALL_BASE}/{doi}", json={"message": "not found"}, status=404)


def _mock_content(url, body=b"<html>full text</html>", status=200, content_type="text/html"):
    responses.add(responses.GET, url, body=body, status=status, content_type=content_type)


def _mock_idconv(records, status=200):
    """records: [{"pmid": "555", "pmcid": "PMC1", "doi": "10.1/x"}] or
    [{"pmid": "888", "status": "error", "errmsg": "..."}]. Builds NCBI's
    REAL response shape (live-verified 2026-08-18): `pmid` comes back as
    a JSON int, and `requested-id` echoes the original string we sent --
    every test using this helper exercises the exact int/string mismatch
    this job's client had to fix after a live run surfaced it."""
    built = []
    for r in records:
        entry = {"pmid": int(r["pmid"]), "requested-id": r["pmid"]}
        if r.get("status") == "error":
            entry["status"] = "error"
            entry["errmsg"] = r.get("errmsg", "not found")
        else:
            entry["pmcid"] = r.get("pmcid")
            entry["doi"] = r.get("doi")
        built.append(entry)
    responses.add(responses.GET, IDCONV_BASE, json={"status": "ok", "records": built}, status=status)


def _mock_europe_pmc_fulltext(pmcid, body=b"<article>full text</article>", status=200):
    responses.add(responses.GET, f"{EUROPEPMC_BASE}/{pmcid}/fullTextXML", body=body, status=status, content_type="application/xml")


def _manifest_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "publication_bioactivity_corpus.parquet")


def _attempts_df(tmp_path):
    return pd.read_parquet(tmp_path / "DATA" / "manifests" / "publication_bioactivity_corpus_attempts.parquet")


@responses.activate
def test_dry_run_does_not_request(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row("10.1000/abc")])

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path, dry_run=True))

    assert result.dry_run is True
    assert result.records_discovered == 1
    assert not (tmp_path / "DATA" / "manifests" / "publication_bioactivity_corpus.parquet").exists()
    assert len(responses.calls) == 0


@responses.activate
def test_full_run_writes_manifest_and_attempts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row("10.1000/abc")])
    _mock_unpaywall("10.1000/abc")
    _mock_content("https://example.org/10.1000/abc.pdf", body=b"%PDF-1.4 content", content_type="application/pdf")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert set(df["doi"]) == {"10.1000/abc"}
    assert set(df["upstream_sources"]) == {"crossref"}
    assert set(df["raw_format"]) == {"pdf"}
    assert set(df["version"]) == {1}

    attempts = _attempts_df(tmp_path)
    assert set(attempts["status"]) == {"success"}

    report_text = (tmp_path / "reports" / "acquisition" / "publication_bioactivity_corpus.md").read_text()
    assert "Publication Bioactivity Evidence Corpus (Job 14)" in report_text


@responses.activate
def test_no_oa_location_is_not_available(tmp_path, monkeypatch):
    """Round-1 fix: Unpaywall returning HTTP 200 with is_oa=false is a
    KNOWN doi with a confirmed negative -- must NOT be recorded with a
    fabricated http_status=404 (that never happened; the lookup itself
    succeeded)."""
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row("10.1000/closed")])
    _mock_unpaywall("10.1000/closed", is_oa=False, oa_status="closed", locations=[])

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    assert result.records_failed == 0
    attempts = _attempts_df(tmp_path)
    assert set(attempts["status"]) == {"not_available"}
    row = attempts.iloc[0]
    assert row["http_status"] == 200  # the Unpaywall lookup itself succeeded
    assert row["error"] == "no_oa_copy"


@responses.activate
def test_oa_true_but_no_usable_location_is_not_available_with_truthful_status(tmp_path, monkeypatch):
    """Round-1 fix: is_oa=true but zero usable location URLs is a
    distinct not_available case from is_oa=false -- also http_status=200
    (the lookup succeeded), with its own distinguishing error value."""
    doi = "10.1000/nolocation"
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row(doi)])
    _mock_unpaywall(doi, is_oa=True, oa_status="green", locations=[])

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    attempts = _attempts_df(tmp_path)
    row = attempts.iloc[0]
    assert row["status"] == "not_available"
    assert row["http_status"] == 200
    assert row["error"] == "no_usable_oa_location"


@responses.activate
def test_doi_unknown_to_unpaywall_is_not_available(tmp_path, monkeypatch):
    """Round-1 fix: this is the ONLY not_available case where http_status
    is truthfully 404 -- Unpaywall's own DOI endpoint returned 404."""
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row("10.1000/unknown")])
    _mock_unpaywall_404("10.1000/unknown")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    attempts = _attempts_df(tmp_path)
    assert set(attempts["status"]) == {"not_available"}
    row = attempts.iloc[0]
    assert row["http_status"] == 404
    assert row["error"] == "unpaywall_doi_not_found"


@responses.activate
def test_not_available_is_retried_not_treated_as_permanent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row("10.1000/abc")])
    _mock_unpaywall("10.1000/abc", is_oa=False, oa_status="closed", locations=[])
    result1 = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))
    assert result1.records_failed == 0
    attempts1 = _attempts_df(tmp_path)
    assert set(attempts1["status"]) == {"not_available"}

    responses.reset()
    _mock_unpaywall("10.1000/abc", is_oa=True, oa_status="gold")
    _mock_content("https://example.org/10.1000/abc.pdf")
    result2 = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result2.records_downloaded == 1


@responses.activate
def test_falls_back_to_next_location_when_first_fetch_fails(tmp_path, monkeypatch):
    """Job 13's round-1 lesson applied here: don't trust only the single
    'best' OA location -- a landing page can block a bot while a
    repository mirror of the same work succeeds."""
    doi = "10.1000/fallback"
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row(doi)])
    locations = [
        {"host_type": "publisher", "url": "https://publisher.example/blocked.pdf", "url_for_pdf": "https://publisher.example/blocked.pdf"},
        {"host_type": "repository", "url": "https://repo.example/mirror.pdf", "url_for_pdf": "https://repo.example/mirror.pdf"},
    ]
    _mock_unpaywall(doi, locations=locations)
    responses.add(responses.GET, "https://publisher.example/blocked.pdf", status=403)
    _mock_content("https://repo.example/mirror.pdf", body=b"%PDF-1.4 mirror content", content_type="application/pdf")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["source_location_url"] == "https://repo.example/mirror.pdf"
    assert df.iloc[0]["host_type"] == "repository"


@responses.activate
def test_location_landing_page_fallback_when_pdf_blocked(tmp_path, monkeypatch):
    """Round-1 fix: within a SINGLE location, a blocked url_for_pdf must
    fall back to that SAME location's url_for_landing_page before this
    job moves on to a different location entirely -- Unpaywall's own data
    format docs describe the landing page as a real full-text route, not
    just a metadata pointer."""
    doi = "10.1000/landingpage"
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row(doi)])
    locations = [{
        "host_type": "publisher",
        "url_for_pdf": "https://publisher.example/blocked.pdf",
        "url_for_landing_page": "https://publisher.example/article.html",
        "url": "https://publisher.example/blocked.pdf",
    }]
    _mock_unpaywall(doi, locations=locations)
    responses.add(responses.GET, "https://publisher.example/blocked.pdf", status=403)
    _mock_content("https://publisher.example/article.html", body=b"<html>full text article</html>")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["source_location_url"] == "https://publisher.example/article.html"
    assert df.iloc[0]["host_type"] == "publisher"  # same location, not a fallback to a different one


@responses.activate
def test_all_locations_fail_is_failed_not_not_available(tmp_path, monkeypatch):
    doi = "10.1000/allfail"
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row(doi)])
    _mock_unpaywall(doi, locations=[{"host_type": "publisher", "url": "https://publisher.example/x.pdf", "url_for_pdf": "https://publisher.example/x.pdf"}])
    responses.add(responses.GET, "https://publisher.example/x.pdf", status=403)

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    assert result.records_failed == 1
    attempts = _attempts_df(tmp_path)
    assert set(attempts["status"]) == {"failed"}


@responses.activate
def test_ordinary_run_skips_without_request(tmp_path, monkeypatch):
    doi = "10.1000/abc"
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row(doi)])
    _mock_unpaywall(doi)
    _mock_content("https://example.org/10.1000/abc.pdf")
    PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    responses.reset()
    # Deliberately no mocks registered -- an ordinary rerun must make zero
    # requests for an already-resolved DOI.
    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    assert result.records_skipped_unchanged == 1
    df = _manifest_df(tmp_path)
    assert set(df["version"]) == {1}


@responses.activate
def test_refresh_reverifies_and_detects_new_location(tmp_path, monkeypatch):
    doi = "10.1000/abc"
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row(doi)])
    _mock_unpaywall(doi)
    _mock_content("https://example.org/10.1000/abc.pdf", body=b"v1 content")
    PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    responses.reset()
    _mock_unpaywall(doi, oa_status="hybrid")
    _mock_content("https://example.org/10.1000/abc.pdf", body=b"v2 corrected content")
    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path, refresh=True))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert sorted(df["version"]) == [1, 2]


@responses.activate
def test_dois_from_multiple_upstream_manifests_deduped(tmp_path, monkeypatch):
    doi = "10.1000/shared"
    _setup(
        tmp_path, monkeypatch,
        pubmed_rows=[_pubmed_row("PMID1", doi)],
        crossref_rows=[_crossref_row(doi)],
    )
    _mock_unpaywall(doi)
    _mock_content("https://example.org/10.1000/shared.pdf")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1  # deduped across pubmed + crossref
    assert result.queries_run == 2  # 2 upstream mentions
    df = _manifest_df(tmp_path)
    assert set(df["upstream_sources"]) == {"crossref,pubmed"}


@responses.activate
def test_doi_case_variants_across_manifests_are_deduped(tmp_path, monkeypatch):
    """Live-verified against this repo's own real data: PubMed can record
    a DOI as 10.1007/BF01741596 while Crossref records the identical work
    as 10.1007/bf01741596 (Crossref lowercases the doi field it returns).
    DOIs are case-insensitive by spec -- these must collapse into ONE
    candidate, not be fetched/stored twice."""
    _setup(
        tmp_path, monkeypatch,
        pubmed_rows=[_pubmed_row("PMID1", "10.1007/BF01741596")],
        crossref_rows=[_crossref_row("10.1007/bf01741596")],
    )
    _mock_unpaywall("10.1007/bf01741596")
    _mock_content("https://example.org/10.1007/bf01741596.pdf")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1
    assert len(responses.calls) == 2  # exactly one Unpaywall lookup + one content fetch, not two of each
    df = _manifest_df(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["doi"] == "10.1007/bf01741596"
    assert set(df.iloc[0]["upstream_sources"].split(",")) == {"crossref", "pubmed"}


@responses.activate
def test_doi_already_covered_by_europe_pmc_fulltext_is_excluded(tmp_path, monkeypatch):
    doi = "10.1000/covered"
    _setup(
        tmp_path, monkeypatch,
        crossref_rows=[_crossref_row(doi), _crossref_row("10.1000/notcovered")],
        europe_pmc_rows=[_europe_pmc_row("MED:1", doi, pmcid="PMC111", is_open_access=True)],
        fulltext_rows=[_fulltext_row("PMC111", "MED:1")],
    )
    _mock_unpaywall("10.1000/notcovered")
    _mock_content("https://example.org/10.1000/notcovered.pdf")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_discovered == 1  # only the not-covered DOI
    df = _manifest_df(tmp_path)
    assert set(df["doi"]) == {"10.1000/notcovered"}
    assert any("excluded" in n and "1 candidate" in n for n in result.notes)


@responses.activate
def test_since_until_filters_candidates(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, crossref_rows=[
        _crossref_row("10.1000/new", pub_date="2026-01-01"),
        _crossref_row("10.1000/old", pub_date="2020-01-01"),
    ])
    _mock_unpaywall("10.1000/new")
    _mock_content("https://example.org/10.1000/new.pdf")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path, since="2025-01-01"))

    assert result.queries_run == 1
    df = _manifest_df(tmp_path)
    assert set(df["doi"]) == {"10.1000/new"}


@responses.activate
def test_no_candidates_raises_clear_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    try:
        PublicationBioactivityCorpusJob().run(_base_args(tmp_path))
        raised = False
    except RuntimeError:
        raised = True
    assert raised


def test_missing_contact_email_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNPAYWALL_CONTACT_EMAIL", raising=False)
    # load_dotenv() walks up from jobs/publication_bioactivity_corpus/job.py's
    # location (not cwd), so it would otherwise find this real repo's .env
    # and reintroduce the var (same quirk documented in tests/jobs/sec/test_job.py).
    import jobs.publication_bioactivity_corpus.job as job_module
    monkeypatch.setattr(job_module, "load_dotenv", lambda: None)
    write_manifest([_crossref_row("10.1000/abc")], tmp_path / "DATA" / "manifests" / "crossref.parquet", extra_fields=CROSSREF_EXTRA_FIELDS)

    try:
        PublicationBioactivityCorpusJob().run(_base_args(tmp_path, contact_email=None))
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "UNPAYWALL_CONTACT_EMAIL" in str(exc)


@responses.activate
def test_query_text_consistent_between_fast_skip_and_fetch(tmp_path, monkeypatch):
    doi = "10.1000/abc"
    _setup(tmp_path, monkeypatch, crossref_rows=[_crossref_row(doi)])
    _mock_unpaywall(doi)
    _mock_content("https://example.org/10.1000/abc.pdf")
    PublicationBioactivityCorpusJob().run(_base_args(tmp_path))
    attempts_run1 = _attempts_df(tmp_path)
    query_text_run1 = attempts_run1.set_index("source_record_id")["query_text"].to_dict()[doi]

    responses.reset()
    PublicationBioactivityCorpusJob().run(_base_args(tmp_path))  # ordinary rerun -- fast-skip path
    attempts_run2 = _attempts_df(tmp_path)
    skipped = attempts_run2[attempts_run2["status"] == "skipped_unchanged"]
    query_text_run2 = skipped.set_index("source_record_id")["query_text"].to_dict()[doi]

    assert query_text_run2 == query_text_run1 == _query_text({"doi": doi})


@responses.activate
def test_pmcid_only_record_fetches_directly_from_europe_pmc(tmp_path, monkeypatch):
    """Round-1 P1 fix: a PubMed record with a PMID and PMCID but NO DOI
    must not be silently dropped -- it's fetched directly from Europe
    PMC's own fullTextXML endpoint by pmcid, no Unpaywall lookup at all."""
    _setup(tmp_path, monkeypatch, pubmed_rows=[_pubmed_row("PMID1", doi=None, pmcid="PMC999")])
    _mock_europe_pmc_fulltext("PMC999", body=b"<article>full text</article>")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["source_record_id"] == "pmcid:PMC999"
    assert df.iloc[0]["identifier_type"] == "pmcid"
    assert df.iloc[0]["pmcid"] == "PMC999"
    assert df.iloc[0]["doi"] is None
    attempts = _attempts_df(tmp_path)
    assert set(attempts["status"]) == {"success"}
    assert not any("unpaywall.org" in call.request.url for call in responses.calls)


@responses.activate
def test_pmcid_fulltext_404_is_not_available_with_truthful_status(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, pubmed_rows=[_pubmed_row("PMID2", doi=None, pmcid="PMC404")])
    responses.add(responses.GET, f"{EUROPEPMC_BASE}/PMC404/fullTextXML", status=404)

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    attempts = _attempts_df(tmp_path)
    row = attempts.iloc[0]
    assert row["status"] == "not_available"
    assert row["http_status"] == 404
    assert row["error"] == "europe_pmc_fulltext_not_found"


@responses.activate
def test_pmid_only_record_resolved_via_id_converter_routes_to_doi_path(tmp_path, monkeypatch):
    """Round-1 P1 fix: a PMID-only record (no doi, no pmcid) is resolved
    via NCBI's PMC ID Converter (exact-identifier reconciliation, not a
    new search) BEFORE candidate identity is finalized; a resolved doi
    routes it into the existing Unpaywall path."""
    _setup(tmp_path, monkeypatch, pubmed_rows=[_pubmed_row("555", doi=None, pmcid=None)])
    _mock_idconv([{"pmid": "555", "pmcid": None, "doi": "10.1000/resolved"}])
    _mock_unpaywall("10.1000/resolved")
    _mock_content("https://example.org/10.1000/resolved.pdf")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["source_record_id"] == "10.1000/resolved"
    assert df.iloc[0]["identifier_type"] == "doi"
    assert any("resolved via NCBI" in n for n in result.notes)


@responses.activate
def test_pmid_only_record_resolved_to_pmcid_routes_to_europe_pmc_path(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, pubmed_rows=[_pubmed_row("777", doi=None, pmcid=None)])
    _mock_idconv([{"pmid": "777", "pmcid": "PMC7777", "doi": None}])
    _mock_europe_pmc_fulltext("PMC7777")

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 1
    df = _manifest_df(tmp_path)
    assert df.iloc[0]["identifier_type"] == "pmcid"
    assert df.iloc[0]["pmcid"] == "PMC7777"


@responses.activate
def test_pmid_unresolvable_is_not_available_without_fake_http_status(tmp_path, monkeypatch):
    """NCBI having no PMC/DOI mapping for a pmid is a genuine negative --
    must not be recorded with a fabricated HTTP status of any kind."""
    _setup(tmp_path, monkeypatch, pubmed_rows=[_pubmed_row("888", doi=None, pmcid=None)])
    _mock_idconv([{"pmid": "888", "status": "error", "errmsg": "pmid not found"}])

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_downloaded == 0
    attempts = _attempts_df(tmp_path)
    row = attempts.iloc[0]
    assert row["status"] == "not_available"
    assert pd.isna(row["http_status"])
    assert row["error"] == "pmid_not_resolvable_to_doi_or_pmcid"


@responses.activate
def test_id_converter_failure_is_failed_not_not_available(tmp_path, monkeypatch):
    """A transient failure of the ID Converter batch call itself (this
    job couldn't even complete the lookup) must be `failed`, not
    `not_available` -- not_available is reserved for a confirmed
    negative, which this run never actually got to confirm."""
    _setup(tmp_path, monkeypatch, pubmed_rows=[_pubmed_row("999", doi=None, pmcid=None)])
    responses.add(responses.GET, IDCONV_BASE, status=500)

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_failed == 1
    attempts = _attempts_df(tmp_path)
    row = attempts.iloc[0]
    assert row["status"] == "failed"
    assert row["error"] == "id_converter_lookup_failed_this_run"
    assert any("PMC ID Converter lookup failed" in n for n in result.notes)


@responses.activate
def test_pmid_only_candidate_not_silently_dropped_from_candidate_universe(tmp_path, monkeypatch):
    """Direct regression test for the round-1 blocker itself: mixing a
    doi-addressable record with a pmid-only (no doi, no pmcid) record
    must discover BOTH, not just the doi-addressable one."""
    _setup(
        tmp_path, monkeypatch,
        pubmed_rows=[_pubmed_row("111", doi="10.1000/hasdoi"), _pubmed_row("222", doi=None, pmcid=None)],
    )
    _mock_unpaywall("10.1000/hasdoi")
    _mock_content("https://example.org/10.1000/hasdoi.pdf")
    _mock_idconv([{"pmid": "222", "status": "error", "errmsg": "pmid not found"}])

    result = PublicationBioactivityCorpusJob().run(_base_args(tmp_path))

    assert result.records_discovered == 2
    assert result.records_downloaded == 1
    attempts = _attempts_df(tmp_path)
    assert set(attempts["status"]) == {"success", "not_available"}
