"""V1.1 PR #37: live Crossref conference-abstract discovery (ESMO/ASH/EHA/SABCS).

## Why this is a new pattern, not an extension of an existing job

- `jobs/crossref` (Job 04) is explicitly DOI-exact reconciliation, not
  discovery: it looks up DOIs already found by other jobs via
  `GET /works/{doi}`, and its own module docstring documents that
  Crossref's free-text search is unusable for unrestricted topic discovery
  (a bare title search across all of Crossref returned 860,937 hits, see
  configs/crossref_reconciliation_sources.yaml).
- `jobs/conference_abstract_corpus` passively reuses an AACR/ASCO corpus
  that was pre-computed by a workflow OUTSIDE this repo; it makes no live
  requests of its own at all.

This job is different: ESMO, ASH, EHA, and SABCS each publish their
congress abstracts as a SUPPLEMENT ISSUE of one specific, ISSN-identified
journal (ESMO -> Annals of Oncology; ASH -> Blood; EHA -> HemaSphere;
SABCS -> Cancer Research). Restricting Crossref's `query.bibliographic`
search to one journal's ISSN via `filter=issn:...` narrows the candidate
pool from "all of Crossref" to "one journal" -- categorically different in
scale/precision from the unrestricted search the reconciliation job's own
docstring warns against. Live-verified 2026-08-31 (see
configs/conference_crossref_search.yaml for the full per-conference
evidence and exact DOIs inspected).

## Container/ISSN match is not conference attribution

Every target journal also carries regular (non-congress) research
articles, and Cancer Research specifically carries AACR Annual Meeting AND
SABCS abstracts (and other congresses') side by side in the very same
supplement issues. Each conference in `configs/conference_crossref_search.yaml`
declares a `signature_type` (+ `signature_value` where needed) --
a deterministic, LOCALLY-applied structural check (see
jobs/conference_crossref_search/signatures.py) that confirms a candidate
actually belongs to THIS congress. A candidate that matches the
ISSN/query-term search but fails its conference's own signature is simply
out of scope for this job -- it is a different document, not a
low-relevance match to acquire-and-disclose the way this repo's other
"acquire broadly, filter downstream" jobs treat ADC-relevance imprecision.

## Discovery-ledger completeness (same lesson as WHO ICTRP/China CDE)

A single DOI can be returned by more than one `adc_query_terms` search
within the same conference (e.g. both "ADC" and "antibody-drug conjugate"
independently surface the same abstract). The manifest is correctly
content-deduped to one current snapshot per DOI, but the discovery ledger
retains EVERY real `(doi, query_id)` observation -- deduped only within a
single (conference, term) pagination sweep (to avoid double-counting a
term's own overlapping pages), never across terms or conferences.

## No secondary per-DOI fetch

Unlike `jobs/crossref`'s `GET /works/{doi}` (one request per DOI), this
job's `/works?` search response already contains full bibliographic
metadata (title, issue, page, container-title, publisher, published date)
for every hit -- there is no second network call per record.

## Round-1 fixes (reviewer-flagged)

**Effective query provenance.** `--since`/`--until` are real, live filters
sent to Crossref (see below) -- so two runs of the same conference/term
with DIFFERENT date windows are materially different queries. `query_id`/
`query_text` are now derived from the FULL effective query (term + ISSN +
date window), via `_effective_query_text`/`_effective_query_id`, so the
same query_id never maps to two different query_texts and a committed
run's provenance is reproducible from its own discovery ledger (previously,
query_id/query_text only encoded the term, silently conflating e.g. a
`--since 2016-01-01` run with a `--since 2022-01-01` run of the same
conference/term).

**EHA conference attribution.** The prior `issue_starts_with_s` signature
wrongly attributed every HemaSphere S-numbered supplement to EHA --
HemaSphere also publishes several OTHER societies' abstracts under the
same S-numbered supplement shape in the same congress year. Fixed:
`volume_issue_map`, an explicit (volume, issue) allowlist sourced from
Wiley's own EHA Congress abstract-book archive -- see
configs/conference_crossref_search.yaml's EHA entry for the full mapping
and citations.

## Round-2 fix (reviewer-flagged, PR #38): maintenance-cadence default window

`update_breadth`'s ordinary 14-day maintenance cadence calls every job
with NO `--since` at all. Without a source-level default, the first
ordinary cadence run after the V1.1 freeze baseline (`--since 2022-01-01`,
1,477 records) would silently become an undeclared full-history backfill
instead of an incremental maintenance run -- a materially different,
much larger effective query, with its own brand-new query_ids under PR
#37's own provenance design. Fixed: `configs/conference_crossref_search.yaml`
now declares `default_since`, and `run()` resolves
`effective_since = args.since or default_since`, used EVERYWHERE (the
Crossref filter, the effective query_text/query_id, the acquisition
report, and the reproduction command) -- so a plain, flag-less
`python -m adc_acquisition conference_crossref_search` is truly
equivalent to the committed frozen baseline, and `--since` remains a real
override for a deliberate future historical backfill. This lives in the
source's own config, not a special case in `update_breadth.py` (which
must stay source-agnostic per its own orchestrator design).

## Disclosed limitations

See configs/conference_crossref_search.yaml's own file header: (1)
`query.bibliographic` is relevance-ranked, not phrase/boolean, so recall
even within one journal is not guaranteed exhaustive (same shape as this
repo's existing ASCO Stage-1 disclosed limitation); (2) ASH's signature is
verified against the current "Supplement N" issue-labeling convention
(confirmed live back through 2018) -- older, differently-labeled ASH
annual-meeting abstracts are not captured this round; (3) EHA's
volume_issue_map must be manually extended for congress years beyond 2026.

## Scope: acquisition foundation only

Same boundary as every other job in this repo's V1.1 round: materializes
DOI + bibliographic + conference-attribution metadata only. No
target/payload/linker/candidate extraction here.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from jobs.conference_crossref_search.client import DEFAULT_ROWS, RATE_LIMIT, CrossrefSearchClient
from jobs.conference_crossref_search.report import build_report
from jobs.conference_crossref_search.signatures import matches_signature
from jobs.crossref.parser import parse_work

CONFIG_PATH = Path("configs/conference_crossref_search.yaml")
MAX_PAGES_PER_QUERY = 50  # safety cap; rows=100 => up to 5,000 records/term/conference before truncation is disclosed.

EXTRA_FIELDS = [
    "conference", "conference_year", "container_title", "publisher",
    "volume", "issue", "page", "conference_attribution_evidence",
]
DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]


@dataclass(frozen=True)
class ConferenceSpec:
    conference_id: str
    query_id_prefix: str
    query_version: int
    container_title: str
    issn: list[str]
    signature_type: str
    signature_value: str | list[str] | None
    active: bool
    purpose: str


def load_conference_specs(path: Path) -> tuple[list[ConferenceSpec], list[str], str | None]:
    """Returns (specs, terms, default_since). `default_since` (PR #38
    round-1 fix) is this SOURCE's own declared default acquisition window
    -- see this config file's own header for why: without it,
    `update_breadth`'s ordinary no-`--since` maintenance cadence would
    silently become an undeclared full-history backfill the first time it
    runs after the V1.1 freeze. Deliberately read here (source config),
    not hardcoded in job.py or special-cased in update_breadth.py, which
    must stay source-agnostic."""
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    specs = [ConferenceSpec(**entry) for entry in data.get("conferences", [])]
    terms = list(data.get("adc_query_terms", []))
    default_since = data.get("default_since")
    return specs, terms, default_since


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_note(conf: ConferenceSpec, message: dict, doi: str) -> str:
    return (
        f"signature={conf.signature_type}"
        f"{f'(value={conf.signature_value!r})' if conf.signature_value else ''}"
        f" issue={message.get('issue')!r} page={message.get('page')!r} doi={doi!r}"
    )


def _effective_query_text(term: str, conf: ConferenceSpec, since: str | None, until: str | None) -> str:
    """The FULL effective Crossref query this run actually issues --
    reviewer-flagged (round-1): `--since`/`--until` are real, live filters
    sent to Crossref (see this module's docstring), so two runs with
    different date windows are materially DIFFERENT queries and must never
    share a query_id/query_text -- otherwise the discovery ledger cannot
    tell a `--since 2016-01-01` run apart from a `--since 2022-01-01` run
    for the same conference/term, making a committed run's provenance
    unreproducible."""
    return (
        f'query.bibliographic="{term}" issn={"+".join(conf.issn)} '
        f'from-pub-date={since or "none"} until-pub-date={until or "none"}'
    )


def _effective_query_id(conf: ConferenceSpec, idx: int, effective_text: str) -> str:
    """Deterministically derived FROM the effective query text (same
    pattern as jobs/crossref's own --doi ad hoc lookup query_id) -- this
    guarantees the same query_id never maps to two materially different
    query_texts, and a differing date window always gets its own id."""
    digest = sha256_bytes(effective_text.encode("utf-8"))[:10]
    return f"{conf.query_id_prefix}_{idx + 1:03d}_{digest}"


class ConferenceCrossrefSearchJob(AcquisitionJob):
    name = "conference_crossref_search"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--config-file", type=str, default=str(CONFIG_PATH),
            help="Path to the conference/signature registry YAML.",
        )
        parser.add_argument(
            "--mailto", type=str, default=None,
            help="Contact email for Crossref's polite pool (also read from CROSSREF_CONTACT_EMAIL env var).",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        import os

        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        mailto = args.mailto or os.environ.get("CROSSREF_CONTACT_EMAIL")
        client = CrossrefSearchClient(RetryingClient(RateLimiter(RATE_LIMIT)), mailto=mailto)

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: every DOI is always content-hash-checked "
                "against the checkpoint regardless of when it was first discovered"
            )

        specs, terms, default_since = load_conference_specs(Path(args.config_file))
        active_specs = [s for s in specs if s.active]
        if not active_specs:
            raise RuntimeError(f"no active conferences in {args.config_file}")
        if not terms:
            raise RuntimeError(f"no adc_query_terms configured in {args.config_file}")

        # PR #38 round-1 fix: --since falls back to the source's own
        # declared default_since, never to "no lower bound at all" -- see
        # load_conference_specs()'s and configs/conference_crossref_search.yaml's
        # own docstrings. effective_since is used EVERYWHERE below (the
        # Crossref filter itself, the effective query_text/query_id, and
        # the acquisition report/reproduction command) so a plain
        # `--since`-less run is truly equivalent to the committed baseline,
        # not a silent full-history backfill.
        effective_since = args.since or default_since
        if args.since is None and default_since:
            result.notes.append(
                f"--since not given: falling back to this source's own default_since={default_since!r} "
                "(configs/conference_crossref_search.yaml) -- pass --since explicitly to override, "
                "e.g. for a deliberate historical backfill"
            )

        date_filters = []
        if effective_since:
            date_filters.append(f"from-pub-date:{effective_since}")
        if args.until:
            date_filters.append(f"until-pub-date:{args.until}")

        message_by_doi: dict[str, dict] = {}
        doi_first_query: dict[str, tuple[str, int, str]] = {}  # doi -> (query_id, query_version, query_text)
        doi_conference: dict[str, ConferenceSpec] = {}
        observations: list[tuple[str, str, int, str]] = []  # (doi, query_id, query_version, query_text)
        signature_rejected_counts: Counter = Counter()
        truncated_queries: list[str] = []

        for conf in active_specs:
            for idx, term in enumerate(terms):
                effective_text = _effective_query_text(term, conf, effective_since, args.until)
                query_id = _effective_query_id(conf, idx, effective_text)
                seen_this_query: set[str] = set()
                cursor = "*"
                filters = [f"issn:{i}" for i in conf.issn] + date_filters
                for page_num in range(MAX_PAGES_PER_QUERY):
                    try:
                        page = client.search(
                            query_bibliographic=term, filters=filters, cursor=cursor, rows=DEFAULT_ROWS,
                        )
                    except requests.RequestException as exc:
                        logger.error("conference=%s query=%s page fetch failed: %s", conf.conference_id, query_id, exc)
                        failure_logger.info("conference=%s query=%s error=%s", conf.conference_id, query_id, exc)
                        result.notes.append(f"{conf.conference_id}/{query_id}: page fetch failed after retries, stopped early: {exc}")
                        break

                    for message in page.items:
                        doi = message.get("DOI")
                        if not doi:
                            continue
                        if not matches_signature(message, conf.signature_type, conf.signature_value):
                            signature_rejected_counts[conf.conference_id] += 1
                            continue
                        message_by_doi[doi] = message
                        doi_conference[doi] = conf
                        if doi not in doi_first_query:
                            doi_first_query[doi] = (query_id, conf.query_version, effective_text)
                        if (doi, query_id) not in seen_this_query:
                            seen_this_query.add((doi, query_id))
                            observations.append((doi, query_id, conf.query_version, effective_text))

                    if not page.next_cursor or not page.items:
                        break
                    cursor = page.next_cursor
                    if page_num == MAX_PAGES_PER_QUERY - 1:
                        truncated_queries.append(f"{conf.conference_id}/{query_id}")

        all_ids = sorted(message_by_doi.keys())
        result.queries_run = len(active_specs) * len(terms)
        result.records_discovered = len(all_ids)

        if truncated_queries:
            result.notes.append(
                f"MAX_PAGES_PER_QUERY ({MAX_PAGES_PER_QUERY}) reached for: {', '.join(truncated_queries)} "
                "-- results truncated, not exhaustive for these query/conference pairs"
            )

        target_ids = all_ids[: args.limit] if args.limit else all_ids

        if args.dry_run:
            result.notes.append(f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} discovered DOIs")
            return result

        now = _now_iso()
        run_id = now

        manifest_path = output_dir / "manifests" / "conference_crossref_search.parquet"
        discovery_path = output_dir / "manifests" / "conference_crossref_search_discovery.parquet"
        attempts_path = output_dir / "manifests" / "conference_crossref_search_attempts.parquet"

        discovery_rows = [
            dict(
                source=self.name, source_record_id=doi, query_id=qid, query_version=qver,
                query_text=qtext, discovered_at=now, run_id=run_id,
            )
            for doi, qid, qver, qtext in observations
        ]
        append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        content_rows = []
        attempt_rows = []

        for doi in target_ids:
            message = message_by_doi[doi]
            conf = doi_conference[doi]
            query_id, query_version, query_text = doi_first_query[doi]
            parsed = parse_work(message)
            if parsed is None:
                continue

            raw_bytes = json.dumps(message, sort_keys=True).encode("utf-8")
            # `score` is Crossref's own per-QUERY relevance ranking for this
            # search call (verified live: identical repeated /works? queries
            # return slightly different floating-point `score` values for
            # the same DOI) -- it describes this run's search context, not
            # the record's own content, and must never leak into
            # content_hash the same way export_file_date/export_filename
            # were excluded for WHO ICTRP/China CDE (a stable score-free
            # snapshot is still written to raw_bytes for full-fidelity
            # debugging; only the version-bump decision excludes it).
            hashable = {k: v for k, v in message.items() if k != "score"}
            content_hash = sha256_bytes(json.dumps(hashable, sort_keys=True).encode("utf-8"))
            prior_state = checkpoint_store.get_record_state(checkpoint, doi)

            if prior_state and prior_state.get("content_hash") == content_hash:
                result.records_skipped_unchanged += 1
                version = prior_state["version"]
                status = "skipped_unchanged"
            else:
                version = (prior_state["version"] + 1) if prior_state else 1
                raw_dir = output_dir / "raw" / self.name / doi.replace("/", "_")
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"v{version}.json"
                raw_path.write_bytes(raw_bytes)
                checkpoint_store.set_record_state(checkpoint, doi, content_hash, version, now)
                result.records_downloaded += 1
                status = "success"
                published_date = parsed.published_date
                content_rows.append(
                    new_manifest_row(
                        extra_fields=EXTRA_FIELDS,
                        source=self.name,
                        source_record_id=doi,
                        source_record_type="conference_abstract",
                        title=parsed.title,
                        url=parsed.url or f"https://doi.org/{doi}",
                        publication_or_release_date=published_date,
                        retrieved_at=now,
                        query_id=query_id,
                        query_text=query_text,
                        raw_file_path=str(raw_path),
                        raw_format="json",
                        content_hash=content_hash,
                        download_status="success",
                        http_status=200,
                        license_or_access_note=f"Crossref bibliographic metadata (publisher={parsed.publisher}).",
                        parent_record_id=None,
                        version=version,
                        notes=None,
                        conference=conf.conference_id,
                        conference_year=(published_date or "")[:4] or None,
                        container_title=parsed.container_title,
                        publisher=parsed.publisher,
                        volume=message.get("volume"),
                        issue=message.get("issue"),
                        page=message.get("page"),
                        conference_attribution_evidence=_evidence_note(conf, message, doi),
                    )
                )

            attempt_rows.append(
                dict(
                    source=self.name, source_record_id=doi, run_id=run_id, attempted_at=now,
                    status=status, http_status=200, error=None, query_id=query_id, query_text=query_text,
                    content_hash=content_hash, version=version,
                )
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)
        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_text = build_report(
            result=result, manifest_df=manifest_df, all_ids=all_ids,
            active_specs=active_specs, terms=terms,
            signature_rejected_counts=signature_rejected_counts,
            output_dir=output_dir, since=effective_since, until=args.until,
        )
        report_path = output_dir.parent / "reports" / "acquisition" / f"{self.name}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
