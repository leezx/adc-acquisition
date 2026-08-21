"""Conference abstract corpus acquisition (BREADTH_PLAN.md Phase 4, Part 6).

NOT a Prompt.md job (Prompt.md's job list stops at Job 15) -- this is the
first source added under the breadth-layer initiative
(reports/validation/BREADTH_PLAN.md), which found zero conference sources
anywhere in this repo's baseline. Prompt.md's own priority ordering for the
breadth layer explicitly puts AACR ahead of ASCO/ESMO, since preclinical/
early-seed ADCs most often surface first in AACR abstracts.

REUSE, NOT RE-SCRAPE (Part 6's explicit instruction: "search this project
and local data for reusable historical corpora before any new download").
This job does not talk to AACR/ASCO/Crossref at all. It reads an
already-materialized local historical corpus that a separate, external
workflow (REPOS/aacr-abstract-workflow, confirmed by reading that workflow's
own scripts, not assumed) built by querying Crossref for each meeting's DOI
prefix and applying an ADC-keyword filter -- see
configs/conference_abstract_corpus_queries.yaml for the exact, verified
filter text per source, including each filter's disclosed limitation
(AACR's is title-only; ASCO's is title+abstract).

That external corpus lives OUTSIDE this repo and outside the Claude Code
project directory entirely, at a path this job never writes to -- same
read-only-external-vault discipline already established for the NAR ADCdb
vault used by tools/breadth/. Configurable via --corpus-root or the
CONFERENCE_ABSTRACT_CORPUS_DIR env var; if the directory doesn't exist this
job raises immediately rather than silently reporting zero records (the
same "fail loud on a missing external dependency" precedent as
publication_bioactivity_corpus's UNPAYWALL_CONTACT_EMAIL check).

Three tables, same shape as every other job in this repo:
- conference_abstract_corpus.parquet            content-version manifest
- conference_abstract_corpus_discovery.parquet  append-only (record, query)
  ledger -- genuinely needed here, NOT a Crossref/publication_bioactivity_
  corpus-style "no discovery ledger" job, because unlike those two jobs this
  one's candidate set is NOT read from another adc-acquisition job's own
  manifest; it comes from a source-external corpus this job newly makes
  legible to configs/*_queries.yaml / query_registry, so Phase 1's locked
  broad-recall provenance rule can recognize it as a genuine broad-discovery
  source in a later re-benchmark.
- conference_abstract_corpus_attempts.parquet   append-only attempts ledger

Year discovery is a GLOB over {AACR,ASCO}_Abstracts/{SOURCE}_*_ADC/
adc_abstracts.json, not a hardcoded year range -- so a future re-run of the
external workflow that adds a new year's folder is picked up automatically,
without a code change here (relevant for Phase 6's twice-monthly delta).

SCHEMA DIVERGENCE ACROSS YEARS, verified by reading the real files, not
assumed uniform: AACR's 2016-2025 folders carry full Crossref metadata
(doi, published_online/published_print date-parts, container_title, ...);
AACR's 2026 folder (PROCEEDINGS-PDF-EXTRACTED, ahead of Crossref indexing
at capture time) has NO doi field at all for 307 of its 344 records --
those become source_record_id=f"aacr:{year}:{record_id}" instead of a doi
key, and get no publication_or_release_date (not fabricated). ASCO's schema
is uniform across all years (every record has a doi, from the JCO
supplement DOI prefix used to query Crossref in the first place).

CANONICAL IDENTITY: doi (normalized lowercase/stripped, same convention as
jobs/publication_bioactivity_corpus/job.py's _normalize_doi) when present,
else f"{conference.lower()}:{year}:{record_id}" using each source's own
native per-year identifier (AACR's abstract_number, ASCO's absId) --
verified unique within (source, year) against the real corpus, not assumed.

MATERIALIZATION: each record's own normalized JSON (not the network -- there
is none here) is written to DATA/raw/conference_abstract_corpus/<id>/vN.json
and content-hashed. UNLIKE every network-fetch job in this repo, this job
recomputes and compares that hash against the checkpoint (RAW_NAMESPACE) on
EVERY run for EVERY record, never trusting a prior attempts-ledger
"success" status without rechecking -- because here there is no expensive
network call being saved by skipping that recheck; the record is already
fully loaded in memory from the local file read _load_all_records just did.
A first version of this job DID reuse Job 13/14's attempts-ledger-trust
fast-skip pattern and silently missed a corpus file the external workflow
corrected between runs, caught by test_content_change_bumps_version, not by
inspection -- fixed by always trusting the checkpoint's own content_hash
directly instead.

DELIBERATELY NOT DONE THIS PHASE (Part 16 scope discipline): no target/
payload/linker/candidate extraction from this corpus's title/abstract text
-- that is Phase 5's job (extending tools/breadth/candidate_queue.py and
feasibility_entities.py to a second text source). This job's only claim is
"this abstract, with this text, was findable in this historical corpus by
this query" -- the same acquisition/extraction boundary already drawn for
every other job in this repo.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.query_registry import active_queries, load_queries
from jobs.conference_abstract_corpus.report import build_report

QUERIES_PATH = Path("configs/conference_abstract_corpus_queries.yaml")
CORPUS_ROOT_ENV = "CONFERENCE_ABSTRACT_CORPUS_DIR"
DEFAULT_CORPUS_ROOT = Path("/Volumes/Stelligen_SSD/Stelligen/Zhixins-KB/2.Biotech/5.ADC_Expert")

EXTRA_FIELDS = ["doi", "conference", "conference_year", "record_id", "authors", "abstract"]
LICENSE_NOTE = (
    "Meeting abstract metadata/text as recorded in a pre-existing local historical corpus "
    "(built externally via Crossref DOI metadata and/or proceedings-PDF extraction, filtered "
    "by an ADC-keyword regex -- see configs/conference_abstract_corpus_queries.yaml for the "
    "verified filter text); this job did not scrape AACR/ASCO/Crossref itself."
)

RAW_NAMESPACE = "raw_records"
DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]

YEAR_DIR_RE = re.compile(r"_([0-9]{4})_ADC$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_doi(doi: str) -> str:
    """Same convention as jobs/publication_bioactivity_corpus/job.py's
    _normalize_doi -- DOIs are case-insensitive by specification, and this
    corpus's own AACR/ASCO records are not consistently cased (Crossref
    itself lowercases the doi field it returns, but not every caller does)."""
    return doi.strip().lower()


def _crossref_date_parts_to_iso(value) -> str | None:
    """AACR's published_online/published_print fields are Crossref's own
    {"date-parts": [[Y, M, D]]} shape (verified against the real files) --
    an empty dict ({}) means Crossref had no date for that field, not a
    parse failure."""
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not parts or not parts[0]:
        return None
    p = parts[0]
    if len(p) < 1 or not p[0]:
        return None
    year = p[0]
    month = p[1] if len(p) > 1 and p[1] else 1
    day = p[2] if len(p) > 2 and p[2] else 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _normalize_loose_date(value: str | None) -> str | None:
    """ASCO's publication_date is a plain string but NOT zero-padded (e.g.
    "2020-5-20") -- verified against the real files. Zero-pad so
    --since/--until string comparison against YYYY-MM-DD works correctly."""
    if not value:
        return None
    parts = value.split("-")
    if len(parts) != 3:
        return value
    try:
        y, m, d = (int(p) for p in parts)
    except ValueError:
        return value
    return f"{y:04d}-{m:02d}-{d:02d}"


def _find_year_files(corpus_root: Path, conference: str) -> list[tuple[int, Path]]:
    """Glob for {conference}_Abstracts/{conference}_<year>_ADC/adc_abstracts.json
    rather than a hardcoded year range, so a future re-run of the external
    workflow that adds a new year's folder is picked up with no code change."""
    pattern = str(corpus_root / f"{conference}_Abstracts" / f"{conference}_*_ADC" / "adc_abstracts.json")
    found = []
    for path_str in sorted(glob.glob(pattern)):
        path = Path(path_str)
        m = YEAR_DIR_RE.search(path.parent.name)
        if not m:
            continue  # defensive: a folder that doesn't match the expected naming isn't a year we can attribute
        found.append((int(m.group(1)), path))
    return found


def _load_aacr_records(path: Path, year: int) -> list[dict]:
    raw_records = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in raw_records:
        raw_doi = r.get("doi")
        doi = _normalize_doi(raw_doi) if raw_doi else None
        pub_date = _crossref_date_parts_to_iso(r.get("published_print")) or _crossref_date_parts_to_iso(r.get("published_online"))
        out.append(dict(
            conference="AACR", year=year, record_id=str(r.get("abstract_number") or r.get("presentation_id") or ""),
            doi=doi, title=r.get("title") or "", authors=list(r.get("authors") or []),
            abstract=r.get("abstract_text") or None,
            url=r.get("crossref_url") or r.get("aacrjournals_url") or (f"https://doi.org/{doi}" if doi else None),
            publication_or_release_date=pub_date, raw=r,
        ))
    return out


def _load_asco_records(path: Path, year: int) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in data.get("records", []):
        raw_doi = r.get("doi")
        doi = _normalize_doi(raw_doi) if raw_doi else None
        out.append(dict(
            conference="ASCO", year=year, record_id=str(r.get("absId") or ""),
            doi=doi, title=r.get("title") or "", authors=list(r.get("authors") or []),
            abstract=r.get("abstract") or None,
            url=r.get("source_url") or (f"https://doi.org/{doi}" if doi else None),
            publication_or_release_date=_normalize_loose_date(r.get("publication_date")), raw=r,
        ))
    return out


LOADERS = {"AACR": _load_aacr_records, "ASCO": _load_asco_records}
QUERY_ID_BY_CONFERENCE = {"AACR": "CONFERENCE_AACR_001", "ASCO": "CONFERENCE_ASCO_001"}


def _canonical_identity(record: dict) -> str:
    if record["doi"]:
        return record["doi"]
    return f"{record['conference'].lower()}:{record['year']}:{record['record_id']}"


def _query_text_for(conference: str, queries_by_id: dict) -> str:
    return queries_by_id[QUERY_ID_BY_CONFERENCE[conference]].query_text


def _load_all_records(corpus_root: Path, since: str | None, until: str | None) -> tuple[list[dict], dict[str, dict], Counter]:
    """Returns (ordered records, record_by_id, per-conference year-file count).
    Records sharing a canonical identity (possible if the same DOI appears
    both under a doi key and, extremely unlikely, is ever re-listed) keep
    the FIRST one seen (sorted conference, year, record_id order) -- this
    corpus is externally deduplicated per-year already, verified live
    (no duplicate record_id within a (conference, year) pair)."""
    all_records: list[dict] = []
    year_file_counts: Counter = Counter()
    for conference, loader in LOADERS.items():
        for year, path in _find_year_files(corpus_root, conference):
            year_file_counts[conference] += 1
            all_records.extend(loader(path, year))

    all_records.sort(key=lambda r: (r["conference"], r["year"], r["record_id"]))

    if since:
        all_records = [r for r in all_records if (r["publication_or_release_date"] or "") >= since]
    if until:
        all_records = [r for r in all_records if (r["publication_or_release_date"] or "9999-99-99") <= until]

    record_by_id: dict[str, dict] = {}
    for record in all_records:
        sid = _canonical_identity(record)
        record_by_id.setdefault(sid, record)

    return all_records, record_by_id, year_file_counts


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    error: str | None = None, content_hash: str | None = None, version: int | None = None,
) -> dict:
    return dict(
        source="conference_abstract_corpus", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=None, error=error, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _content_manifest_row(
    record: dict, source_record_id: str, query_id: str, query_text: str, raw_path: Path,
    content_hash: str, version: int, now: str,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="conference_abstract_corpus", source_record_id=source_record_id, source_record_type="conference_abstract",
        title=record["title"], url=record["url"], publication_or_release_date=record["publication_or_release_date"],
        retrieved_at=now, query_id=query_id, query_text=query_text,
        raw_file_path=str(raw_path), raw_format="json", content_hash=content_hash,
        download_status="success", http_status=None, license_or_access_note=LICENSE_NOTE,
        parent_record_id=None, version=version, notes=None,
        doi=record["doi"], conference=record["conference"], conference_year=record["year"],
        record_id=record["record_id"], authors=record["authors"], abstract=record["abstract"],
    )


class ConferenceAbstractCorpusJob(AcquisitionJob):
    name = "conference_abstract_corpus"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--corpus-root", type=str, default=None,
            help=(
                "Root directory of the pre-existing local AACR/ASCO abstract corpus "
                f"(expects {{AACR,ASCO}}_Abstracts/ subdirectories). Falls back to the "
                f"{CORPUS_ROOT_ENV} env var, then a hardcoded default path."
            ),
        )
        parser.add_argument(
            "--queries-file", type=str, default=str(QUERIES_PATH),
            help="Path to the query registry documenting the external filter's provenance.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        corpus_root = Path(args.corpus_root or os.environ.get(CORPUS_ROOT_ENV) or DEFAULT_CORPUS_ROOT)
        if not corpus_root.exists():
            raise RuntimeError(
                f"conference abstract corpus root not found at {corpus_root} -- this job reuses a "
                "pre-existing LOCAL historical corpus (BREADTH_PLAN.md Phase 4, Part 6) rather than "
                "scraping AACR/ASCO itself, so it cannot proceed without that directory mounted. "
                f"Pass --corpus-root, or set the {CORPUS_ROOT_ENV} env var."
            )

        queries = load_queries(Path(args.queries_file))
        queries_by_id = {q.query_id: q for q in active_queries(queries)}
        for conference, expected_query_id in QUERY_ID_BY_CONFERENCE.items():
            if expected_query_id not in queries_by_id:
                raise RuntimeError(f"{args.queries_file} is missing required active query_id={expected_query_id}")

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: this job globs the full corpus root every "
                "run (cheap local file reads, no paginated remote query to resume from a cursor)."
            )

        all_records, record_by_id, year_file_counts = _load_all_records(corpus_root, args.since, args.until)
        if not all_records:
            raise RuntimeError(
                f"0 records found under {corpus_root} for AACR/ASCO -- confirm the corpus root is correct "
                "and its {AACR,ASCO}_Abstracts/*_ADC/adc_abstracts.json files exist."
            )

        all_ids = sorted(record_by_id.keys())
        conference_counts = Counter(r["conference"] for r in all_records)
        result.queries_run = len(queries_by_id)
        result.records_discovered = len(all_ids)

        discovery_path = output_dir / "manifests" / f"{self.name}_discovery.parquet"
        attempts_path = output_dir / "manifests" / f"{self.name}_attempts.parquet"

        now = _now_iso()
        run_id = now
        discovery_rows = [
            dict(
                source=self.name, source_record_id=sid,
                query_id=QUERY_ID_BY_CONFERENCE[record_by_id[sid]["conference"]],
                query_version=queries_by_id[QUERY_ID_BY_CONFERENCE[record_by_id[sid]["conference"]]].query_version,
                query_text=_query_text_for(record_by_id[sid]["conference"], queries_by_id),
                discovered_at=run_id, run_id=run_id,
            )
            for sid in all_ids
        ]

        # Content-change detection: unlike every network-fetch job in this
        # repo, recomputing content_hash here costs nothing extra -- the
        # record is already fully loaded in memory from _load_all_records
        # above (a local file read, not a network call). There is no
        # expensive operation being saved by trusting a prior attempts-
        # ledger status without rechecking, so this job always recomputes
        # and compares directly against the checkpoint (the authoritative
        # record of what was last materialized), rather than reusing the
        # attempts-ledger-trust pattern jobs 13/14 use to avoid a real
        # re-fetch. Verified live: a first version of this job that DID
        # reuse that pattern silently missed a corpus file the external
        # workflow corrected between runs -- caught by
        # test_content_change_bumps_version, not by inspection.
        changed_ids: list[str] = []
        unchanged_ids: list[str] = []
        raw_bytes_by_id: dict[str, bytes] = {}
        content_hash_by_id: dict[str, str] = {}
        for sid in all_ids:
            raw_bytes = json.dumps(record_by_id[sid], sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
            content_hash = sha256_bytes(raw_bytes)
            raw_bytes_by_id[sid] = raw_bytes
            content_hash_by_id[sid] = content_hash
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, sid, namespace=RAW_NAMESPACE)
            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                unchanged_ids.append(sid)
            else:
                changed_ids.append(sid)

        target_ids = changed_ids[: args.limit] if args.limit else changed_ids

        if args.dry_run:
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} candidate records "
                f"({conference_counts.get('AACR', 0)} AACR, {conference_counts.get('ASCO', 0)} ASCO across "
                f"{year_file_counts.get('AACR', 0)} AACR year-files and {year_file_counts.get('ASCO', 0)} ASCO "
                f"year-files) -- {len(changed_ids)} new-or-changed, {len(unchanged_ids)} unchanged and would be skipped."
            )
            return result

        manifest_path = output_dir / "manifests" / f"{self.name}.parquet"
        content_rows = []
        attempt_rows = []
        outcome_counts: Counter = Counter()

        for source_record_id in unchanged_ids:
            result.records_skipped_unchanged += 1
            outcome_counts["skipped_unchanged"] += 1
            record = record_by_id[source_record_id]
            query_id = QUERY_ID_BY_CONFERENCE[record["conference"]]
            query_text = _query_text_for(record["conference"], queries_by_id)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id, namespace=RAW_NAMESPACE)
            attempt_rows.append(
                _record_row(
                    source_record_id, now, now, "skipped_unchanged", query_id, query_text,
                    content_hash=content_hash_by_id[source_record_id],
                    version=raw_prior_state["version"] if raw_prior_state else None,
                )
            )

        for source_record_id in target_ids:
            record = record_by_id[source_record_id]
            query_id = QUERY_ID_BY_CONFERENCE[record["conference"]]
            query_text = _query_text_for(record["conference"], queries_by_id)
            content_hash = content_hash_by_id[source_record_id]
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, source_record_id, namespace=RAW_NAMESPACE)
            version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
            raw_dir = output_dir / "raw" / self.name / source_record_id.replace("/", "_").replace(":", "_")
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"v{version}.json"
            raw_path.write_bytes(raw_bytes_by_id[source_record_id])
            checkpoint_store.set_record_state(checkpoint, source_record_id, content_hash, version, now, namespace=RAW_NAMESPACE)
            checkpoint_store.save(checkpoint)

            result.records_downloaded += 1
            outcome_counts["success"] += 1
            attempt_rows.append(
                _record_row(source_record_id, now, now, "success", query_id, query_text, content_hash=content_hash, version=version)
            )
            content_rows.append(
                _content_manifest_row(record, source_record_id, query_id, query_text, raw_path, content_hash, version, now)
            )

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        total_outcomes = result.records_downloaded + result.records_skipped_unchanged
        result.notes.append(
            f"this run: {result.records_downloaded} success, {result.records_skipped_unchanged} skipped_unchanged "
            f"({total_outcomes} total attempted/fast-skipped outcomes); corpus root: {corpus_root}."
        )
        if len(changed_ids) > len(target_ids):
            result.notes.append(
                f"{len(changed_ids) - len(target_ids)} new-or-changed record(s) deferred to a future run by --limit."
            )

        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        report_path = output_dir.parent / "reports" / "acquisition" / f"{self.name}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(result, manifest_df, all_ids, changed_ids, unchanged_ids,
                         conference_counts, year_file_counts, outcome_counts, corpus_root),
            encoding="utf-8",
        )

        return result
