"""Job 01: PubMed acquisition (Prompt.md section 5).

Three separate tables come out of a run, deliberately not merged:

- pubmed.parquet            content-version manifest — one row per evidence
                             snapshot that was actually materialized (Prompt.md
                             section 3/23). `version` is a content-snapshot
                             concept here; a failed fetch has no content, so
                             it must never appear in this table or occupy a
                             version slot (doing so let a later failure
                             overwrite an earlier successful snapshot at the
                             same key — the bug this module now avoids).
- pubmed_discovery.parquet  append-only ledger: every (pmid, query) hit, every
                             run. A record found by 3 queries keeps all 3 rows
                             here forever, even though the content manifest
                             above only carries one "primary" query_id per
                             Prompt.md section 3's single-valued contract.
- pubmed_attempts.parquet   append-only ledger: every fetch attempt (success/
                             skipped_unchanged/failed), every run. This is
                             where failures live and stay auditable, without
                             ever touching evidence-snapshot state.

Together with DATA/checkpoints/pubmed.json (source_record_id -> content_hash/
version), these are the index that makes a monthly `--resume` run cheap: look
up each newly-discovered PMID in the checkpoint to know instantly whether it's
new, unchanged, or changed, without re-deriving that from the ledgers.

BUG FIX (2026-09-01): two active queries' true hit counts grew past NCBI
ESearch's own hard 9,999-record pagination ceiling ("'retstart' cannot be
larger than 9998"). A query past that ceiling returns HTTP 200 with a
MALFORMED JSON error body (a literal, unescaped newline inside the ERROR
string), which crashed `response.json()` uncaught and aborted the ENTIRE
job -- since discovery is purely in-memory until after all queries finish
(see run()), this lost 100% of that run's PubMed acquisition, not just the
oversized queries. See NCBI_ESEARCH_MAX_RETSTART in run() -- pagination now
stops at the ceiling and discloses the truncation (job.py's result.notes +
report.py's "Known coverage gaps") instead of crashing.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.http_utils import RateLimiter, RetryingClient
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.query_registry import active_queries, load_queries
from jobs.pubmed.client import EFETCH_BATCH_SIZE, RATE_LIMIT_WITH_KEY, RATE_LIMIT_WITHOUT_KEY, PubMedClient
from jobs.pubmed.parser import parse_pubmed_articleset
from jobs.pubmed.report import build_report

QUERIES_PATH = Path("configs/pubmed_queries.yaml")
EXTRA_FIELDS = ["pmid", "pmcid", "doi", "abstract", "authors", "journal", "publication_types", "mesh_terms"]
DEFAULT_ESEARCH_PAGE_SIZE = 200
# NCBI's own documented ESearch ceiling (live-verified 2026-09-01, see this
# module's run() for the full incident): "'retstart' cannot be larger than
# 9998. For PubMed, ESearch can only retrieve the first 9,999 records
# matching the query." Never request a retstart beyond this.
NCBI_ESEARCH_MAX_RETSTART = 9998
LICENSE_NOTE = "NCBI PubMed metadata, public domain indexing record."

DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_ncbi_date(date_str: str | None) -> str | None:
    """Convert our CLI convention YYYY-MM-DD to NCBI's YYYY/MM/DD."""
    if not date_str:
        return None
    return date_str.replace("-", "/")


def _attempt_row(
    pmid: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    http_status: int | None = None, error: str | None = None,
    content_hash: str | None = None, version: int | None = None,
) -> dict:
    return dict(
        source="pubmed", source_record_id=pmid, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=http_status, error=error,
        query_id=query_id, query_text=query_text, content_hash=content_hash, version=version,
    )


class PubMedJob(AcquisitionJob):
    name = "pubmed"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--queries-file",
            type=str,
            default=str(QUERIES_PATH),
            help="Path to the PubMed query registry YAML.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        load_dotenv()
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        since = args.since
        if args.resume and not since:
            since = checkpoint.get("last_success_max_date")

        queries = active_queries(load_queries(Path(args.queries_file)))
        if not queries:
            raise RuntimeError(f"no active queries found in {args.queries_file}")
        query_by_id = {q.query_id: q for q in queries}

        api_key = os.environ.get("NCBI_API_KEY") or None
        tool = os.environ.get("NCBI_TOOL_NAME") or "adc-acquisition"
        email = os.environ.get("NCBI_CONTACT_EMAIL") or None
        rate = RATE_LIMIT_WITH_KEY if api_key else RATE_LIMIT_WITHOUT_KEY
        http_client = RetryingClient(RateLimiter(rate))
        client = PubMedClient(http_client, api_key=api_key, tool=tool, email=email)

        mindate = _to_ncbi_date(since)
        maxdate = _to_ncbi_date(args.until)

        # --- Discovery: run every active query, paginate, track provenance ---
        pmid_first_query: dict[str, tuple[str, str]] = {}
        pmid_query_hits: dict[str, set[str]] = defaultdict(set)
        query_id_counts: Counter = Counter()
        truncated_queries: list[tuple[str, int]] = []  # (query_id, true total count)
        for query in queries:
            retstart = 0
            hits_for_query = 0
            while True:
                page = client.esearch(
                    term=query.query_text,
                    retstart=retstart,
                    retmax=DEFAULT_ESEARCH_PAGE_SIZE,
                    mindate=mindate,
                    maxdate=maxdate,
                )
                for pmid in page.idlist:
                    pmid_query_hits[pmid].add(query.query_id)
                    if pmid not in pmid_first_query:
                        pmid_first_query[pmid] = (query.query_id, query.query_text)
                hits_for_query += len(page.idlist)
                retstart += DEFAULT_ESEARCH_PAGE_SIZE
                # With --limit set we only need enough discovered PMIDs to
                # satisfy it; paginating a 10k-hit query to exhaustion just
                # to throw away everything past the first page would waste
                # dozens of API calls for a 20-record smoke test. Without
                # --limit (a real full/incremental run) we page to exhaustion.
                enough_for_limit = args.limit and len(pmid_first_query) >= args.limit
                # NCBI's ESearch API hard-caps retstart at
                # NCBI_ESEARCH_MAX_RETSTART -- live-verified 2026-09-01:
                # "'retstart' cannot be larger than 9998. For PubMed, ESearch
                # can only retrieve the first 9,999 records matching the
                # query." A query whose real hit count exceeds this returns
                # HTTP 200 with a MALFORMED JSON error body (a literal,
                # unescaped newline byte inside the ERROR string), which
                # crashed response.json() uncaught and aborted the entire
                # job -- not a transient network issue, 100% reproducible
                # for any query whose count exceeds the ceiling. Never
                # request a retstart past it; disclose the truncation
                # instead (NCBI's own docs point to EDirect/history-based
                # batching as the real fix for >9,999-hit queries -- out of
                # scope for this job's simple esearch pagination).
                if retstart > NCBI_ESEARCH_MAX_RETSTART and retstart < page.count:
                    truncated_queries.append((query.query_id, page.count))
                    break
                if retstart >= page.count or not page.idlist or enough_for_limit:
                    break
            query_id_counts[query.query_id] = hits_for_query
            logger.info("query %s (%s): %d hits (of %d total)", query.query_id, query.query_text, hits_for_query, page.count)

        all_pmids = list(pmid_first_query.keys())
        duplicate_pmids = {pmid for pmid, qids in pmid_query_hits.items() if len(qids) > 1}

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        result.queries_run = len(queries)
        for query_id, true_count in truncated_queries:
            logger.warning(
                "query %s: NCBI ESearch retstart ceiling reached, %d of %d true hits discovered "
                "(records beyond retstart=%d are structurally unreachable via this endpoint)",
                query_id, min(true_count, NCBI_ESEARCH_MAX_RETSTART + DEFAULT_ESEARCH_PAGE_SIZE), true_count,
                NCBI_ESEARCH_MAX_RETSTART,
            )
            result.notes.append(
                f"{query_id}: NCBI ESearch retstart ceiling (9,999 records) reached -- this query has "
                f"{true_count} true hits, only records up to retstart={NCBI_ESEARCH_MAX_RETSTART} were "
                "discovered this run, NOT a full query result. See NCBI's own EDirect/history-based "
                "batching docs (https://www.ncbi.nlm.nih.gov/books/NBK25499/) for a future fix if this "
                "query's uncovered tail matters."
            )
        result.records_discovered = len(all_pmids)
        result.notes.append(
            "used NCBI api_key (rate limit 9 req/s)" if api_key else "no NCBI api_key configured (rate limit 2.8 req/s)"
        )
        if args.limit:
            result.notes.append(
                "discovery pagination was capped by --limit; per-query hit counts reflect only the "
                "pages actually fetched, not each query's true total corpus size"
            )

        # Deterministic ordering so --limit is reproducible across runs.
        all_pmids.sort(key=int)
        target_pmids = all_pmids[: args.limit] if args.limit else all_pmids

        if args.dry_run:
            result.notes.append(f"dry-run: would fetch {len(target_pmids)} of {len(all_pmids)} discovered PMIDs")
            return result

        now = _now_iso()
        run_id = now  # one acquisition run == one timestamp; unique enough for ledger provenance.

        manifest_path = output_dir / "manifests" / "pubmed.parquet"
        discovery_path = output_dir / "manifests" / "pubmed_discovery.parquet"
        attempts_path = output_dir / "manifests" / "pubmed_attempts.parquet"

        # Discovery ledger covers every PMID this run's esearch calls found,
        # for every query that found it — independent of --limit, since
        # discovery happened regardless of whether we go on to fetch content.
        discovery_rows = [
            dict(
                source="pubmed",
                source_record_id=pmid,
                query_id=query_by_id[query_id].query_id,
                query_version=query_by_id[query_id].query_version,
                query_text=query_by_id[query_id].query_text,
                discovered_at=now,
                run_id=run_id,
            )
            for pmid, query_ids in pmid_query_hits.items()
            for query_id in sorted(query_ids)
        ]
        append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)

        content_rows = []
        attempt_rows = []

        for batch_start in range(0, len(target_pmids), EFETCH_BATCH_SIZE):
            batch = target_pmids[batch_start : batch_start + EFETCH_BATCH_SIZE]
            try:
                raw_xml = client.efetch_raw_xml(batch)
                articles = parse_pubmed_articleset(raw_xml)
            except Exception as exc:  # noqa: BLE001 — a whole-batch failure must not crash the run
                logger.error("batch efetch failed for %d PMIDs: %s", len(batch), exc)
                for pmid in batch:
                    failure_logger.info("pmid=%s error=%s", pmid, exc)
                    result.records_failed += 1
                    query_id, query_text = pmid_first_query[pmid]
                    attempt_rows.append(_attempt_row(pmid, run_id, now, "failed", query_id, query_text, error=str(exc)))
                continue

            fetched_pmids = {a.pmid for a in articles}
            for pmid in batch:
                if pmid not in fetched_pmids:
                    logger.warning("pmid=%s missing from efetch batch response", pmid)
                    failure_logger.info("pmid=%s error=missing_from_batch_response", pmid)
                    result.records_failed += 1
                    query_id, query_text = pmid_first_query[pmid]
                    attempt_rows.append(
                        _attempt_row(pmid, run_id, now, "failed", query_id, query_text, error="missing_from_batch_response")
                    )

            for article in articles:
                pmid = article.pmid
                if pmid not in pmid_first_query:
                    # efetch can occasionally return a PMID we didn't request
                    # in this batch (e.g. a merged record); don't fabricate
                    # provenance for it.
                    continue
                query_id, query_text = pmid_first_query[pmid]
                content_hash = sha256_bytes(article.raw_xml)
                prior_state = checkpoint_store.get_record_state(checkpoint, pmid)

                if prior_state and prior_state.get("content_hash") == content_hash:
                    # Unchanged: the existing content-version row already on
                    # disk is correct as-is. Do not re-append it — this run
                    # produced no new evidence snapshot, only a successful
                    # check that nothing changed, which belongs in the
                    # attempts ledger, not the content manifest.
                    result.records_skipped_unchanged += 1
                    version = prior_state["version"]
                    status = "skipped_unchanged"
                else:
                    version = (prior_state["version"] + 1) if prior_state else 1
                    raw_dir = output_dir / "raw" / "pubmed" / pmid
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    raw_path = raw_dir / f"v{version}.xml"
                    raw_path.write_bytes(article.raw_xml)
                    checkpoint_store.set_record_state(checkpoint, pmid, content_hash, version, now)
                    result.records_downloaded += 1
                    status = "success"
                    content_rows.append(
                        new_manifest_row(
                            extra_fields=EXTRA_FIELDS,
                            source="pubmed",
                            source_record_id=pmid,
                            source_record_type="journal_article",
                            title=article.title,
                            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                            publication_or_release_date=article.publication_date,
                            retrieved_at=now,
                            query_id=query_id,
                            query_text=query_text,
                            raw_file_path=str(raw_path),
                            raw_format="xml",
                            content_hash=content_hash,
                            download_status=status,
                            http_status=200,
                            license_or_access_note=LICENSE_NOTE,
                            parent_record_id=None,
                            version=version,
                            notes=None,
                            pmid=pmid,
                            pmcid=article.pmcid,
                            doi=article.doi,
                            abstract=article.abstract,
                            authors=article.authors,
                            journal=article.journal,
                            publication_types=article.publication_types,
                            mesh_terms=article.mesh_terms,
                        )
                    )

                attempt_rows.append(
                    _attempt_row(pmid, run_id, now, status, query_id, query_text, http_status=200, content_hash=content_hash, version=version)
                )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        checkpoint["last_run_at"] = now
        if not result.records_failed:
            checkpoint["last_success_max_date"] = args.until or now[:10]
        checkpoint_store.save(checkpoint)

        report_text = build_report(
            result=result,
            manifest_df=manifest_df,
            queries=queries,
            query_id_counts=query_id_counts,
            unique_pmids=set(all_pmids),
            duplicate_pmids=duplicate_pmids,
            since=since,
            until=args.until,
        )
        # reports/ is a sibling of DATA/ (Prompt.md section 2), scoped to
        # wherever --output pointed — otherwise a scratch/test run with a
        # different --output would silently clobber the real report.
        report_path = output_dir.parent / "reports" / "acquisition" / "pubmed.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
