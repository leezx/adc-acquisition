"""Job 01: PubMed acquisition (Prompt.md section 5)."""

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
from adc_acquisition.manifest import new_manifest_row, write_manifest
from adc_acquisition.query_registry import active_queries, load_queries
from jobs.pubmed.client import EFETCH_BATCH_SIZE, RATE_LIMIT_WITH_KEY, RATE_LIMIT_WITHOUT_KEY, PubMedClient
from jobs.pubmed.parser import parse_pubmed_articleset
from jobs.pubmed.report import build_report

QUERIES_PATH = Path("configs/pubmed_queries.yaml")
EXTRA_FIELDS = ["pmid", "pmcid", "doi", "abstract", "authors", "journal", "publication_types", "mesh_terms"]
DEFAULT_ESEARCH_PAGE_SIZE = 200
LICENSE_NOTE = "NCBI PubMed metadata, public domain indexing record."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_ncbi_date(date_str: str | None) -> str | None:
    """Convert our CLI convention YYYY-MM-DD to NCBI's YYYY/MM/DD."""
    if not date_str:
        return None
    return date_str.replace("-", "/")


def _failed_row(pmid: str, query_id: str, query_text: str, now: str, reason: str) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="pubmed",
        source_record_id=pmid,
        source_record_type="journal_article",
        title=None,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        publication_or_release_date=None,
        retrieved_at=now,
        query_id=query_id,
        query_text=query_text,
        raw_file_path=None,
        raw_format="xml",
        content_hash=None,
        download_status="failed",
        http_status=None,
        license_or_access_note=LICENSE_NOTE,
        parent_record_id=None,
        version=1,
        notes=reason,
        pmid=pmid,
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
                if retstart >= page.count or not page.idlist or enough_for_limit:
                    break
            query_id_counts[query.query_id] = hits_for_query
            logger.info("query %s (%s): %d hits (of %d total)", query.query_id, query.query_text, hits_for_query, page.count)

        all_pmids = list(pmid_first_query.keys())
        duplicate_pmids = {pmid for pmid, qids in pmid_query_hits.items() if len(qids) > 1}

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        result.queries_run = len(queries)
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

        manifest_path = output_dir / "manifests" / "pubmed.parquet"
        rows = []
        now = _now_iso()

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
                    rows.append(_failed_row(pmid, query_id, query_text, now, str(exc)))
                continue

            fetched_pmids = {a.pmid for a in articles}
            for pmid in batch:
                if pmid not in fetched_pmids:
                    logger.warning("pmid=%s missing from efetch batch response", pmid)
                    failure_logger.info("pmid=%s error=missing_from_batch_response", pmid)
                    result.records_failed += 1
                    query_id, query_text = pmid_first_query[pmid]
                    rows.append(_failed_row(pmid, query_id, query_text, now, "missing_from_batch_response"))

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
                    result.records_skipped_unchanged += 1
                    version = prior_state["version"]
                    raw_path = output_dir / "raw" / "pubmed" / pmid / f"v{version}.xml"
                    download_status = "skipped_unchanged"
                else:
                    version = (prior_state["version"] + 1) if prior_state else 1
                    raw_dir = output_dir / "raw" / "pubmed" / pmid
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    raw_path = raw_dir / f"v{version}.xml"
                    raw_path.write_bytes(article.raw_xml)
                    checkpoint_store.set_record_state(checkpoint, pmid, content_hash, version, now)
                    result.records_downloaded += 1
                    download_status = "success"

                rows.append(
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
                        download_status=download_status,
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

        manifest_df = write_manifest(rows, manifest_path, extra_fields=EXTRA_FIELDS)
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
        report_path = Path("reports/acquisition/pubmed.md")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

        return result
