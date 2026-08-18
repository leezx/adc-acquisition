"""Job 14: publication bioactivity evidence corpus (Prompt.md section 18,
"JOB 14", execution order section 29).

SECOND-PASS literature acquisition -- Prompt.md's input list for this job
is "PMIDs / PMCIDs / DOIs / known ADC aliases", not a new literature
search: Jobs 01 (PubMed), 02 (Europe PMC) and 04 (Crossref) already own
discovery. This job reconciles publications already materialized by those
three jobs' own manifests (latest version per record only -- the rule
established when Job 04/Crossref first had to consume another job's
manifest as input, reused again by Job 13) and, for each one, tries to
acquire a legally-accessible open-access copy likely to contain the
bioactivity measurements Prompt.md lists (IC50/EC50/DC50, tumor
inhibition, response rate, PK/PD, toxicity, ...). DO NOT perform final
structured extraction here (Prompt.md is explicit) -- this job only
acquires raw evidence. "known ADC aliases"-DRIVEN DISCOVERY IS DEFERRED
TO JOB 15 (known-ADC asset expansion) -- this job only works through
exact identifiers (DOI/PMCID/PMID) Jobs 01/02/04 already discovered, it
never searches by alias, so the two phases' scope never overlaps.

EXACT-IDENTIFIER COVERAGE (round-1 fix): the initial version of this job
only ever looked at each upstream record's `doi` field, silently dropping
every PubMed/Europe PMC record that has a PMID and/or PMCID but no DOI --
verified live against this repo's own real committed data that this is
NOT a theoretical edge case (8/20 PubMed records and 6/20 Europe PMC
records in the real demo set have no doi at all). Prompt.md's own input
list is explicitly PMIDs/PMCIDs/DOIs, not "DOIs only". Fixed with
EXACT-ID RESOLUTION, still purely reconciling identifiers Jobs 01/02
already discovered, never a new search:
  - a record with a doi          -> unchanged: Unpaywall OA lookup + fetch
  - a record with a pmcid (no doi) -> direct Europe PMC fullTextXML fetch
    by that pmcid (the exact same endpoint Job 02 itself uses for its own
    is_open_access records, jobs/europe_pmc/client.py's
    fetch_fulltext_xml) -- Job 02 might not have fetched it (e.g. its
    is_open_access flag was false at discovery time, or the record came
    from a different upstream query), so this is a genuinely separate
    acquisition attempt, not a guaranteed duplicate.
  - a record with ONLY a pmid (no doi, no pmcid) -> resolved via NCBI's
    own PMC ID Converter (https://www.ncbi.nlm.nih.gov/pmc/tools/id-converter-api/,
    exact PMID->PMCID/DOI lookup, batched once per run for every such
    pmid) BEFORE candidate identity is finalized; a resolved doi/pmcid
    routes into the paths above, an unresolvable pmid is `not_available`
    (a real negative -- NCBI has no PMC/DOI mapping for it -- retried
    every ordinary run in case that changes, never assumed permanent).
`_canonical_identity()` picks doi > pmcid > pmid (in that priority) as
each record's `source_record_id`/manifest key, AFTER resolution has had a
chance to upgrade a pmid-only mention to a doi/pmcid one.

MECHANISM, established from research before writing any code (explicitly
to avoid repeating Job 13's round-1 mistake of generalizing from a single
test point): Europe PMC (Job 02) already fetches full-text JATS XML, but
ONLY for records ITS OWN search queries discovered AND that are flagged
is_open_access with a pmcid -- verified live that the repo's actual
europe_pmc_fulltext.parquet currently has ZERO rows (none of the small
demo set happened to be OA), and that neither PubMed's nor Crossref's own
manifests fetch full text at all (grep-confirmed: their EXTRA_FIELDS are
bibliographic/abstract only). Unpaywall (https://unpaywall.org, live-
verified free API, 100,000 calls/day, keyed by DOI, metadata-only response
naming OA locations across publisher/repository/preprint hosts) closes a
GENUINELY separate gap: DOIs Job 02 never happened to discover at all, and
DOIs where Europe PMC's own is_open_access flag is false/absent but a
legal OA copy exists elsewhere (hybrid OA, institutional repository,
etc.). Its coverage is empirically NOT a subset of Europe PMC's OA subset.

Two-stage acquisition per DOI-identified record, mirroring Job 13's
"confirm absence is a real status, don't crash on network noise" shape:
(1) an Unpaywall lookup by DOI (metadata: is_oa, oa_status, an ordered
list of OA locations); (2) a content fetch of the actual bytes, trying
EVERY url a location offers (url_for_pdf, then url_for_landing_page, then
url, deduplicated) before moving to the next location in Unpaywall's own
order -- round-1 fix: the initial version only ever tried
`url_for_pdf or url`, so a location whose PDF link 403s a bot but whose
landing page still serves full text as HTML was wrongly treated as a
dead location and skipped entirely, even though Unpaywall's own data
format docs describe the landing page as a real, separate full-text
route, not just a metadata pointer.

TRUTHFUL not_available PROVENANCE (round-1 fix): the initial version
recorded EVERY not_available outcome with a hardcoded http_status=404,
conflating two different real states -- Unpaywall's DOI endpoint itself
returning HTTP 404 (this exact DOI is unknown to Unpaywall) vs. Unpaywall
returning HTTP 200 with is_oa=false or no usable OA location (a KNOWN
DOI that Unpaywall has confirmed currently has no legal OA copy). Fixed:
only a genuine lookup-level 404 is recorded with http_status=404; a 200
response with no usable OA copy is recorded with http_status=200 and a
distinct `error` value (`no_oa_copy` / `no_usable_oa_location`), so the
attempts ledger never fabricates an HTTP status that didn't happen.

publication_bioactivity_corpus.parquet is a content-version manifest keyed
by the record's canonical identity (doi, or `pmcid:PMCxxxx` when no doi is
known, or `pmid:NNNN` for a PMID NCBI could not resolve at all);
publication_bioactivity_corpus_attempts.parquet is its attempts ledger. No
discovery ledger -- same reasoning as Crossref/Job 13: the candidate list
is read directly from already-materialized upstream manifests, not
discovered via a live query of this job's own.

DEDUP AGAINST JOB 02: a pmcid whose Europe PMC full text is ALREADY
successfully materialized (europe_pmc_fulltext.parquet has a resolved row
for it -- checked DIRECTLY by pmcid, its own source_record_id there, not
via a doi round-trip) is excluded from this job's candidate set -- re-
downloading the same article's OA full text under a second table would be
pure duplication of Job 02's own work, the identical "don't re-acquire
what an existing job already legitimately has" precedent as Job 13's
USPTO exclusion. This is checked from real data (not assumed): the count
of excluded records is reported every run, and is currently 0 against
this repo's committed demo manifests (europe_pmc_fulltext.parquet has
zero rows there).

MATERIALIZATION mirrors Job 13's fully-hardened design: own `raw_records`
checkpoint namespace, skip-by-default once a record's fulltext is
successfully materialized requires the ledger's own most-recent status
already being resolved AND that resolved attempt's recorded version
matching the raw checkpoint's CURRENT version (a mismatch is
`pending_recovery`); `--refresh` opts a run into re-verifying already-
successful records (a re-run of the full acquisition path, since any of
Unpaywall's data, Europe PMC's OA flag, or the ID Converter's mapping
could have changed).

`--since`/`--until` filter candidate SELECTION client-side by each
upstream manifest's own `publication_or_release_date` (same as Job 13;
there's no new discovery here to filter). `--resume` is a no-op beyond
default behavior for the same reason as Crossref/Job 13: candidate
selection isn't windowed by any cursor.

query_id == source_record_id (one query per canonical identity, same
scheme as the artifact ids in Job 13); query_text is built by a single
shared `_query_text()` helper used by BOTH the fast-skip loop and the
real-fetch loop, so the same query_id never resolves to two different
query_text values across manifest/attempts -- the recurring provenance
bug Job 12's round-1 review first caught, then Job 13's round-1 review
caught again.

Every run's THIS-RUN outcome counts (success/skipped_unchanged/
not_available/failed) must sum to the number of records actually
attempted or fast-skipped this run -- same invariant as Job 13, applied
proactively. The report also breaks candidates down by identifier_type
(doi / pmcid / pmid_unresolved) and by how many pmid-only mentions were
successfully upgraded via the ID Converter, so "how much of Job 14's
candidate universe is actually addressable" is never hidden behind a
DOI-only count.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.html_utils import infer_raw_format
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.web_snapshot_client import WebSnapshotClient
from jobs.europe_pmc.client import RATE_LIMIT as EUROPE_PMC_RATE_LIMIT
from jobs.europe_pmc.client import EuropePMCClient
from jobs.publication_bioactivity_corpus.client import (
    IDCONV_RATE_LIMIT,
    RATE_LIMIT as UNPAYWALL_RATE_LIMIT,
    PMCIDConverterClient,
    UnpaywallClient,
)
from jobs.publication_bioactivity_corpus.report import build_report

PUBMED_MANIFEST_PATH = Path("DATA") / "manifests" / "pubmed.parquet"
EUROPE_PMC_MANIFEST_PATH = Path("DATA") / "manifests" / "europe_pmc.parquet"
CROSSREF_MANIFEST_PATH = Path("DATA") / "manifests" / "crossref.parquet"
EUROPE_PMC_FULLTEXT_MANIFEST_PATH = Path("DATA") / "manifests" / "europe_pmc_fulltext.parquet"

EXTRA_FIELDS = ["doi", "pmcid", "identifier_type", "oa_status", "host_type", "source_location_url", "upstream_sources"]
LICENSE_NOTE_UNPAYWALL = (
    "Unpaywall-identified legal open-access copy (host_type={host_type}, oa_status={oa_status}); "
    "publisher paywalls are never bypassed -- only Unpaywall-confirmed OA locations are fetched."
)
LICENSE_NOTE_EUROPE_PMC_DIRECT = (
    "Europe PMC open-access full text (JATS XML), fetched directly by PMCID -- exact-identifier "
    "acquisition of a record Job 01/02 already discovered, not a new literature search."
)

CONTENT_RATE_LIMIT = 0.5  # req/s -- same conservative default as Jobs 11/12's WebSnapshotClient (arbitrary, uncoordinated publisher/repository hosts).
RAW_NAMESPACE = "raw_records"

ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]

UNRESOLVED_STATUSES = {"failed", "not_available"}
RESOLVED_STATUSES = {"success", "skipped_unchanged"}

UPSTREAM_MANIFESTS = ("pubmed", "europe_pmc", "crossref")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_doi(doi: str) -> str:
    """DOIs are case-insensitive by specification (https://www.doi.org/doi_handbook/2_Numbering.html#2.4)
    -- verified live against this repo's OWN committed data: PubMed's
    manifest has doi=10.1007/BF01741596 for the same work Crossref's
    manifest records as doi=10.1007/bf01741596 (Crossref itself lowercases
    the doi field it returns). Without normalizing, this job would treat
    those as two different candidates and fetch/store the same OA article
    twice under two identity keys -- the exact "same entity, two
    spellings" conflation class this repo has hit before (release/query
    identity in Job 12, publication_number casing assumptions in Job 13)."""
    return doi.strip().lower()


def _normalize_pmcid(pmcid: str) -> str:
    p = pmcid.strip().upper()
    return p if p.startswith("PMC") else f"PMC{p}"


def _clean_str(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _canonical_identity(record: dict) -> str:
    """doi > pmcid > pmid, in that priority -- the SAME priority order
    used to pick which upstream identifier becomes this record's
    source_record_id/manifest key, applied AFTER PMID resolution has had a
    chance to upgrade a pmid-only mention to a doi/pmcid one."""
    if record.get("doi"):
        return record["doi"]
    if record.get("pmcid"):
        return f"pmcid:{record['pmcid']}"
    return f"pmid:{record['pmid']}"


def _identifier_type(record: dict) -> str:
    if record.get("doi"):
        return "doi"
    if record.get("pmcid"):
        return "pmcid"
    return "pmid_unresolved"


def _query_text(record: dict) -> str:
    """Single source of truth for this record's query_text -- used by
    BOTH the fast-skip loop and the real-fetch loop, so the same query_id
    never resolves to two different query_text values across
    manifest/attempts (the provenance bug Job 12's round-1 review caught,
    recurring at Job 13, guarded against proactively here)."""
    id_type = _identifier_type(record)
    if id_type == "doi":
        return f"Unpaywall OA lookup and content fetch for doi={record['doi']}"
    if id_type == "pmcid":
        return f"Europe PMC direct OA full-text fetch for pmcid={record['pmcid']}"
    return f"PMID resolution (NCBI PMC ID Converter) for pmid={record['pmid']} -- no DOI/PMCID available"


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None, content_hash: str | None = None,
    version: int | None = None,
) -> dict:
    return dict(
        source="publication_bioactivity_corpus", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _content_manifest_row(
    record: dict, source_record_id: str, oa_status: str | None, host_type: str | None, source_location_url: str | None,
    query_id: str, query_text: str, raw_path: Path, raw_format: str, content_hash: str, version: int, now: str,
    license_note: str,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="publication_bioactivity_corpus",
        source_record_id=source_record_id,
        source_record_type="oa_fulltext",
        title=f"OA full text: {source_record_id}",
        url=source_location_url,
        publication_or_release_date=None,
        retrieved_at=now,
        query_id=query_id,
        query_text=query_text,
        raw_file_path=str(raw_path),
        raw_format=raw_format,
        content_hash=content_hash,
        download_status="success",
        http_status=200,
        license_or_access_note=license_note,
        parent_record_id=None,
        version=version,
        notes=None,
        doi=record.get("doi"),
        pmcid=record.get("pmcid"),
        identifier_type=_identifier_type(record),
        oa_status=oa_status,
        host_type=host_type,
        source_location_url=source_location_url,
        upstream_sources=",".join(sorted(record["upstream_sources"])),
    )


def _latest_attempt_by_id(attempts_path: Path) -> dict[str, dict]:
    if not attempts_path.exists():
        return {}
    df = pd.read_parquet(attempts_path)
    if df.empty:
        return {}
    latest = df.sort_values("attempted_at").groupby("source_record_id", as_index=False).tail(1)
    return {
        row["source_record_id"]: {"status": row["status"], "version": row["version"], "content_hash": row["content_hash"]}
        for _, row in latest.iterrows()
    }


def _classify_ids(all_ids: list, latest_attempts: dict, checkpoint_store, checkpoint) -> tuple:
    """Same pattern as jobs/patent_bioactivity_corpus/job.py's
    _classify_artifact_ids: a resolved attempt (success/skipped_unchanged)
    is only safe to fast-skip if its own recorded version matches
    RAW_NAMESPACE's CURRENT version -- otherwise it's pending_recovery,
    routed through the ordinary per-item loop instead of trusted as a
    no-request skip."""
    resolved_ids: set = set()
    pending_recovery_ids: list = []
    for rid in all_ids:
        att = latest_attempts.get(rid)
        if not att or att["status"] not in RESOLVED_STATUSES:
            continue
        raw_state = checkpoint_store.get_record_state(checkpoint, rid, namespace=RAW_NAMESPACE)
        if raw_state is None:
            continue
        if att["version"] == raw_state["version"]:
            resolved_ids.add(rid)
        else:
            pending_recovery_ids.append(rid)
    return resolved_ids, sorted(pending_recovery_ids)


def _load_publication_mentions_from_manifest(manifest_path: Path, upstream_source: str, since: str | None, until: str | None) -> list[dict]:
    """Every record in an upstream job's manifest (Job 01/PubMed, Job 02/
    Europe PMC, or Job 04/Crossref) that carries AT LEAST ONE of
    doi/pmcid/pmid, latest version only, optionally date-filtered by
    --since/--until against that manifest's own publication_or_release_date.
    Unlike the initial version of this job, a record with no doi is NOT
    dropped here -- that was the round-1 bug (silently losing every
    PMID/PMCID-only record)."""
    if not manifest_path.exists():
        return []
    df = pd.read_parquet(manifest_path)
    if df.empty:
        return []
    latest = df.sort_values("version").groupby("source_record_id", as_index=False).tail(1)
    if since:
        latest = latest[latest["publication_or_release_date"].fillna("") >= since]
    if until:
        latest = latest[latest["publication_or_release_date"].fillna("9999-99-99") <= until]

    mentions = []
    has_pmid_col = "pmid" in latest.columns
    has_pmcid_col = "pmcid" in latest.columns
    has_doi_col = "doi" in latest.columns
    for _, row in latest.iterrows():
        raw_doi = _clean_str(row.get("doi")) if has_doi_col else None
        raw_pmcid = _clean_str(row.get("pmcid")) if has_pmcid_col else None
        raw_pmid = _clean_str(row.get("pmid")) if has_pmid_col else None
        doi = _normalize_doi(raw_doi) if raw_doi else None
        pmcid = _normalize_pmcid(raw_pmcid) if raw_pmcid else None
        pmid = raw_pmid
        if not doi and not pmcid and not pmid:
            continue  # no usable identifier at all -- nothing to acquire against
        mentions.append(dict(
            doi=doi, pmcid=pmcid, pmid=pmid,
            publication_or_release_date=row.get("publication_or_release_date"),
            upstream_source=upstream_source,
        ))
    return mentions


def _resolved_europe_pmc_pmcids(fulltext_manifest_path: Path) -> set:
    """pmcids whose Job 02 (Europe PMC) full text has already been
    successfully materialized at least once -- europe_pmc_fulltext.parquet
    only ever gains a content row on a successful fetch (an unchanged
    rerun doesn't write a new row, see jobs/europe_pmc/job.py's
    _process_fulltext), so any pmcid present there (its OWN
    source_record_id) has resolved full text. Checked DIRECTLY by pmcid --
    not via a doi round-trip, which could miss a match if either side's
    doi field is stale/missing even though the pmcid itself is a match."""
    if not fulltext_manifest_path.exists():
        return set()
    ft_df = pd.read_parquet(fulltext_manifest_path)
    if ft_df.empty:
        return set()
    return {_normalize_pmcid(str(p)) for p in ft_df["source_record_id"].dropna().unique()}


def _location_urls(location) -> list[str]:
    return location.candidate_urls()


def _fetch_oa_content(content_client: WebSnapshotClient, locations: list) -> tuple:
    """Try every url_for_pdf/url_for_landing_page/url a location offers
    (deduplicated, PDF first) before moving to the NEXT location in
    Unpaywall's own order -- round-1 fix: the initial version only ever
    tried url_for_pdf-or-url per location, so a location whose PDF link
    403s a bot but whose landing page still serves full text as HTML was
    wrongly treated as a dead location. Returns
    (content_bytes_or_None, location_or_None, url_or_None, content_type_or_None, fetch_errors)."""
    fetch_errors: list[str] = []
    for location in locations:
        for candidate_url in _location_urls(location):
            try:
                response = content_client.fetch(candidate_url)
            except requests.RequestException as exc:
                fetch_errors.append(f"{candidate_url}: {exc}")
                continue
            if response.status_code != 200 or not response.content:
                fetch_errors.append(f"{candidate_url}: HTTP {response.status_code}")
                continue
            return response.content, location, candidate_url, response.headers.get("Content-Type"), fetch_errors
    return None, None, None, None, fetch_errors


class PublicationBioactivityCorpusJob(AcquisitionJob):
    name = "publication_bioactivity_corpus"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--pubmed-manifest", type=str, default=str(PUBMED_MANIFEST_PATH),
            help="Path to Job 01 (PubMed)'s manifest to read candidates from.",
        )
        parser.add_argument(
            "--europe-pmc-manifest", type=str, default=str(EUROPE_PMC_MANIFEST_PATH),
            help="Path to Job 02 (Europe PMC)'s manifest to read candidates from.",
        )
        parser.add_argument(
            "--crossref-manifest", type=str, default=str(CROSSREF_MANIFEST_PATH),
            help="Path to Job 04 (Crossref)'s manifest to read candidates from.",
        )
        parser.add_argument(
            "--europe-pmc-fulltext-manifest", type=str, default=str(EUROPE_PMC_FULLTEXT_MANIFEST_PATH),
            help="Path to Job 02's full-text manifest, used only to exclude pmcids Job 02 already resolved.",
        )
        parser.add_argument(
            "--contact-email", type=str, default=None,
            help="Contact email for Unpaywall's API (also read from UNPAYWALL_CONTACT_EMAIL env var). "
            "Unpaywall rejects placeholder-looking addresses with HTTP 422.",
        )
        parser.add_argument(
            "--refresh", action="store_true",
            help=(
                "Re-run the full acquisition path for EVERY candidate record, including ones already "
                "successfully materialized, to pick up newly-available OA copies or corrected OA/ID-mapping "
                "status (run periodically, not on every incremental run)."
            ),
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        load_dotenv()
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        email = args.contact_email or os.environ.get("UNPAYWALL_CONTACT_EMAIL")
        if not email:
            raise RuntimeError(
                "UNPAYWALL_CONTACT_EMAIL (or --contact-email) must be set to a real-looking email address -- "
                "Unpaywall's API rejects placeholder addresses (e.g. test@example.com) with HTTP 422. "
                "Free, no registration required: https://unpaywall.org/products/api"
            )
        unpaywall_client = UnpaywallClient(RetryingClient(RateLimiter(UNPAYWALL_RATE_LIMIT)), email=email)
        content_client = WebSnapshotClient(RetryingClient(RateLimiter(CONTENT_RATE_LIMIT)))
        europe_pmc_client = EuropePMCClient(RetryingClient(RateLimiter(EUROPE_PMC_RATE_LIMIT)))
        idconv_client = PMCIDConverterClient(
            RetryingClient(RateLimiter(IDCONV_RATE_LIMIT)),
            tool=os.environ.get("NCBI_TOOL_NAME") or "adc-acquisition",
            email=os.environ.get("NCBI_CONTACT_EMAIL") or None,
        )

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: candidate selection isn't windowed by any "
                "cursor (every record in the upstream manifests is considered every run), so there's no "
                "separate incremental-window narrowing to do."
            )

        mentions = (
            _load_publication_mentions_from_manifest(Path(args.pubmed_manifest), "pubmed", args.since, args.until)
            + _load_publication_mentions_from_manifest(Path(args.europe_pmc_manifest), "europe_pmc", args.since, args.until)
            + _load_publication_mentions_from_manifest(Path(args.crossref_manifest), "crossref", args.since, args.until)
        )
        if not mentions:
            raise RuntimeError(
                f"no candidates (doi/pmcid/pmid) found in {args.pubmed_manifest}, {args.europe_pmc_manifest}, or "
                f"{args.crossref_manifest} (have Jobs 01/02/04 been run yet? or did --since/--until "
                "exclude everything?)"
            )

        candidates_by_source = Counter(m["upstream_source"] for m in mentions)

        # --- Exact-ID resolution: upgrade every pmid-only mention (no doi,
        # no pmcid) via NCBI's PMC ID Converter, batched once per run,
        # BEFORE canonical identity is assigned. This is reconciliation of
        # identifiers Jobs 01/02 already discovered, not a new search. ---
        pmid_only_pmids = sorted({m["pmid"] for m in mentions if not m["doi"] and not m["pmcid"] and m["pmid"]})
        pmid_candidates_total = len(pmid_only_pmids)
        idconv_results: dict = {}
        idconv_available = True
        if pmid_only_pmids:
            try:
                idconv_results = idconv_client.convert_batch(pmid_only_pmids)
            except requests.RequestException as exc:
                idconv_available = False
                logger.warning("PMC ID Converter batch lookup failed for %d pmids: %s", len(pmid_only_pmids), exc)
                result.notes.append(
                    f"PMC ID Converter lookup failed this run ({exc}) -- {len(pmid_only_pmids)} pmid-only "
                    "candidates could not even be checked for a DOI/PMCID mapping and are reported as failed, "
                    "not not_available, since resolution itself didn't complete."
                )

        pmid_resolved_to_doi = 0
        pmid_resolved_to_pmcid = 0
        for mention in mentions:
            if mention["doi"] or mention["pmcid"] or not mention["pmid"]:
                continue
            resolved = idconv_results.get(mention["pmid"])
            if not resolved:
                continue
            if resolved.doi:
                mention["doi"] = _normalize_doi(resolved.doi)
                pmid_resolved_to_doi += 1
            elif resolved.pmcid:
                mention["pmcid"] = _normalize_pmcid(resolved.pmcid)
                pmid_resolved_to_pmcid += 1

        # --- Merge mentions sharing the same canonical identity (post-resolution) ---
        record_by_id: dict[str, dict] = {}
        for mention in mentions:
            source_record_id = _canonical_identity(mention)
            record = record_by_id.setdefault(
                source_record_id,
                {"doi": None, "pmcid": None, "pmid": None, "upstream_sources": set(), "publication_or_release_date": None},
            )
            record["upstream_sources"].add(mention["upstream_source"])
            for field in ("doi", "pmcid", "pmid"):
                if not record[field] and mention[field]:
                    record[field] = mention[field]
            if not record["publication_or_release_date"] and mention["publication_or_release_date"]:
                record["publication_or_release_date"] = mention["publication_or_release_date"]

        resolved_pmcids = _resolved_europe_pmc_pmcids(Path(args.europe_pmc_fulltext_manifest))
        already_covered_count = sum(1 for r in record_by_id.values() if r["pmcid"] and r["pmcid"] in resolved_pmcids)
        all_ids = sorted(
            sid for sid, record in record_by_id.items()
            if not (record["pmcid"] and record["pmcid"] in resolved_pmcids)
        )

        result.queries_run = len(mentions)
        result.records_discovered = len(all_ids)

        attempts_path = output_dir / "manifests" / "publication_bioactivity_corpus_attempts.parquet"
        latest_attempts = _latest_attempt_by_id(attempts_path)
        unresolved_ids = {rid for rid, att in latest_attempts.items() if att["status"] in UNRESOLVED_STATUSES}

        resolved_ids, pending_recovery_ids = _classify_ids(all_ids, latest_attempts, checkpoint_store, checkpoint)
        pending_recovery_id_set = set(pending_recovery_ids)
        fresh_ids = sorted(
            rid for rid in all_ids
            if rid not in resolved_ids and rid not in unresolved_ids and rid not in pending_recovery_id_set
        )
        backlog_ids = sorted(rid for rid in all_ids if rid in unresolved_ids)
        already_skipped_ids = sorted(resolved_ids)

        if args.refresh:
            ordered_work = fresh_ids + backlog_ids + pending_recovery_ids + already_skipped_ids
            fast_skip_ids: list = []
        else:
            ordered_work = fresh_ids + backlog_ids + pending_recovery_ids
            fast_skip_ids = already_skipped_ids
        target_ids = ordered_work[: args.limit] if args.limit else ordered_work

        identifier_type_counts = Counter(_identifier_type(record_by_id[sid]) for sid in all_ids)

        if args.dry_run:
            candidates_by_source_str = ", ".join(f"{source}: {count}" for source, count in candidates_by_source.items())
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} candidate records "
                f"({candidates_by_source_str} upstream mentions, {already_covered_count} excluded as already "
                f"covered by Job 02's own resolved full text) -- "
                f"{identifier_type_counts.get('doi', 0)} doi-addressable, "
                f"{identifier_type_counts.get('pmcid', 0)} pmcid-addressable, "
                f"{pmid_resolved_to_doi + pmid_resolved_to_pmcid} of {pmid_candidates_total} pmid-only mentions "
                f"resolved via NCBI's ID Converter, {identifier_type_counts.get('pmid_unresolved', 0)} unresolved "
                f"identifier-only candidates "
                f"({len(fresh_ids)} never attempted, {len(backlog_ids)} unresolved retries, "
                f"{len(pending_recovery_ids)} pending recovery, "
                f"{len(fast_skip_ids)} already successful and skipped with no request"
                + (", 0 refresh re-checks (--refresh not set)" if not args.refresh else "")
                + ")"
            )
            return result

        now = _now_iso()
        run_id = now

        manifest_path = output_dir / "manifests" / "publication_bioactivity_corpus.parquet"
        content_rows = []
        attempt_rows = []
        not_available_this_run = 0
        outcome_counts: Counter = Counter()

        already_skipped_id_set = set(already_skipped_ids)

        for source_record_id in fast_skip_ids:
            result.records_skipped_unchanged += 1
            outcome_counts["skipped_unchanged"] += 1
            record = record_by_id[source_record_id]
            query_id = source_record_id
            query_text = _query_text(record)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id, namespace=RAW_NAMESPACE)
            attempt_rows.append(
                _record_row(
                    source_record_id, run_id, now, "skipped_unchanged", query_id, query_text,
                    content_hash=raw_prior_state["content_hash"] if raw_prior_state else None,
                    version=raw_prior_state["version"] if raw_prior_state else None,
                )
            )

        for source_record_id in target_ids:
            record = record_by_id[source_record_id]
            query_id = source_record_id
            query_text = _query_text(record)
            identifier_type = _identifier_type(record)

            if identifier_type == "pmid_unresolved":
                if not idconv_available:
                    result.records_failed += 1
                    outcome_counts["failed"] += 1
                    attempt_rows.append(
                        _record_row(source_record_id, run_id, now, "failed", query_id, query_text, error="id_converter_lookup_failed_this_run")
                    )
                else:
                    not_available_this_run += 1
                    outcome_counts["not_available"] += 1
                    attempt_rows.append(
                        _record_row(
                            source_record_id, run_id, now, "not_available", query_id, query_text,
                            error="pmid_not_resolvable_to_doi_or_pmcid",
                        )
                    )
                continue

            if identifier_type == "pmcid":
                try:
                    raw_bytes = europe_pmc_client.fetch_fulltext_xml(record["pmcid"])
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        logger.info("pmcid=%s: no OA full text available (Europe PMC 404)", record["pmcid"])
                        not_available_this_run += 1
                        outcome_counts["not_available"] += 1
                        attempt_rows.append(
                            _record_row(source_record_id, run_id, now, "not_available", query_id, query_text, http_status=404, error="europe_pmc_fulltext_not_found")
                        )
                        continue
                    logger.warning("pmcid=%s Europe PMC fetch failed: %s", record["pmcid"], exc)
                    failure_logger.info("pmcid=%s error=%s", record["pmcid"], exc)
                    result.records_failed += 1
                    outcome_counts["failed"] += 1
                    attempt_rows.append(_record_row(source_record_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                    continue
                except requests.RequestException as exc:
                    logger.warning("pmcid=%s Europe PMC fetch failed: %s", record["pmcid"], exc)
                    failure_logger.info("pmcid=%s error=%s", record["pmcid"], exc)
                    result.records_failed += 1
                    outcome_counts["failed"] += 1
                    attempt_rows.append(_record_row(source_record_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                    continue

                oa_status = None
                host_type = "europe_pmc"
                used_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{record['pmcid']}/fullTextXML"
                raw_format = "xml"
                license_note = LICENSE_NOTE_EUROPE_PMC_DIRECT
            else:  # doi
                try:
                    unpaywall_result = unpaywall_client.lookup(record["doi"])
                except requests.RequestException as exc:
                    logger.warning("doi=%s Unpaywall lookup failed: %s", record["doi"], exc)
                    failure_logger.info("doi=%s error=%s", record["doi"], exc)
                    result.records_failed += 1
                    outcome_counts["failed"] += 1
                    attempt_rows.append(_record_row(source_record_id, run_id, now, "failed", query_id, query_text, error=str(exc)))
                    continue

                if unpaywall_result is None:
                    # Unpaywall's DOI endpoint itself returned HTTP 404 -- this exact DOI is unknown to it.
                    logger.info("doi=%s: unknown to Unpaywall (HTTP 404)", record["doi"])
                    not_available_this_run += 1
                    outcome_counts["not_available"] += 1
                    attempt_rows.append(
                        _record_row(source_record_id, run_id, now, "not_available", query_id, query_text, http_status=404, error="unpaywall_doi_not_found")
                    )
                    continue
                if not unpaywall_result.is_oa:
                    logger.info("doi=%s: Unpaywall confirms no OA copy (oa_status=%s)", record["doi"], unpaywall_result.oa_status)
                    not_available_this_run += 1
                    outcome_counts["not_available"] += 1
                    attempt_rows.append(
                        _record_row(source_record_id, run_id, now, "not_available", query_id, query_text, http_status=200, error="no_oa_copy")
                    )
                    continue
                if not any(loc.candidate_urls() for loc in unpaywall_result.locations):
                    logger.info("doi=%s: Unpaywall says is_oa but offers no usable location URL", record["doi"])
                    not_available_this_run += 1
                    outcome_counts["not_available"] += 1
                    attempt_rows.append(
                        _record_row(source_record_id, run_id, now, "not_available", query_id, query_text, http_status=200, error="no_usable_oa_location")
                    )
                    continue

                raw_bytes, used_location, used_url, used_content_type, fetch_errors = _fetch_oa_content(content_client, unpaywall_result.locations)
                if raw_bytes is None:
                    error = "; ".join(fetch_errors[:3]) or "no fetchable OA location URL"
                    logger.warning("doi=%s: Unpaywall confirmed an OA copy but content fetch failed: %s", record["doi"], error)
                    failure_logger.info("doi=%s error=%s", record["doi"], error)
                    result.records_failed += 1
                    outcome_counts["failed"] += 1
                    attempt_rows.append(_record_row(source_record_id, run_id, now, "failed", query_id, query_text, error=error))
                    continue

                oa_status = unpaywall_result.oa_status
                host_type = used_location.host_type
                raw_format = infer_raw_format(used_content_type, used_url)
                license_note = LICENSE_NOTE_UNPAYWALL.format(host_type=host_type, oa_status=oa_status)

            content_hash = sha256_bytes(raw_bytes)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id, namespace=RAW_NAMESPACE)
            raw_dir = output_dir / "raw" / "publication_bioactivity_corpus" / source_record_id.replace("/", "_").replace(":", "_")

            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                version = raw_prior_state["version"]
                raw_path = raw_dir / f"v{version}.{raw_format}"
                if source_record_id in already_skipped_id_set:
                    result.records_skipped_unchanged += 1
                    outcome_counts["skipped_unchanged"] += 1
                    attempt_rows.append(
                        _record_row(source_record_id, run_id, now, "skipped_unchanged", query_id, query_text, content_hash=content_hash, version=version)
                    )
                    continue
                # Else: fresh/backlog/pending_recovery whose content
                # happens to match a PRIOR fetch that was never
                # successfully materialized -- fall through and recover,
                # reusing the existing raw file rather than rewriting it.
            else:
                version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.{raw_format}"
                raw_path.write_bytes(raw_bytes)
                checkpoint_store.set_record_state(checkpoint, source_record_id, content_hash, version, now, namespace=RAW_NAMESPACE)
                checkpoint_store.save(checkpoint)

            result.records_downloaded += 1
            outcome_counts["success"] += 1
            attempt_rows.append(
                _record_row(source_record_id, run_id, now, "success", query_id, query_text, content_hash=content_hash, version=version)
            )
            content_rows.append(
                _content_manifest_row(
                    record, source_record_id, oa_status, host_type, used_url, query_id, query_text,
                    raw_path, raw_format, content_hash, version, now, license_note,
                )
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        total_outcomes = result.records_downloaded + result.records_skipped_unchanged + not_available_this_run + result.records_failed
        result.notes.append(
            f"this run: {result.records_downloaded} success, {result.records_skipped_unchanged} skipped_unchanged, "
            f"{not_available_this_run} not_available, {result.records_failed} failed "
            f"({total_outcomes} total attempted/fast-skipped outcomes)."
        )
        if already_covered_count:
            result.notes.append(
                f"{already_covered_count} candidate records excluded: already covered by Job 02's own resolved "
                "Europe PMC full text (avoiding pure duplication of that job's work)."
            )
        if pmid_candidates_total:
            result.notes.append(
                f"{pmid_resolved_to_doi + pmid_resolved_to_pmcid} of {pmid_candidates_total} pmid-only upstream "
                f"mentions resolved via NCBI's PMC ID Converter ({pmid_resolved_to_doi} to a doi, "
                f"{pmid_resolved_to_pmcid} to a pmcid)."
            )

        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / "publication_bioactivity_corpus.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(
                result, manifest_df, all_ids, fresh_ids, backlog_ids, pending_recovery_ids, fast_skip_ids,
                candidates_by_source, outcome_counts, not_available_this_run, already_covered_count,
                identifier_type_counts, pmid_candidates_total, pmid_resolved_to_doi, pmid_resolved_to_pmcid,
            ),
            encoding="utf-8",
        )

        return result
