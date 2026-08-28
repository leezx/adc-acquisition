"""WHO ICTRP (International Clinical Trials Registry Platform) acquisition.

Source-coverage expansion, per the reviewer's explicit V1.1 priority list
(P0: "WHO ICTRP / global trial registry layer") -- Job 03 (ClinicalTrials.gov)
is this repo's only clinical-trial discovery source, and WHO ICTRP itself
aggregates 17+ national/regional primary registries (ClinicalTrials.gov,
EU CTIS, ChiCTR, JPRN, CTRI, ANZCTR, ISRCTN, and more), making it the
single highest-leverage patch for global trial discovery this repo can add
without building a bespoke job per country registry.

INTERIM ACCESS MODEL (disclosed, not silently narrowed -- reviewer-
confirmed 2026-08-28). WHO ICTRP's real batch/automated ("crawling")
access requires WHO-issued credentials: live research confirmed the public
Search Portal's bulk CSV/XML download is free and unrestricted for a
HUMAN using the portal's own "Export results to XML" button, but
programmatic/scheduled crawling explicitly requires emailing
ictrpinfo@who.int to request a username/password (WHO's own documented
process); the portal's real-time XML web service separately states its
own access cost "can be provided upon request," i.e. may not be free at
all. Until WHO-issued crawling credentials exist, this job makes NO
network request to WHO whatsoever -- it reads a MANUALLY exported XML
file that a human periodically downloads via the Search Portal's own
export button and drops into `--corpus-dir` (default `DATA/raw/WHO_ICTRP/`,
gitignored like every other `DATA/raw/` path in this repo). This is the
exact same "reuse an already-materialized local file, do not scrape"
architecture already established by
`jobs/conference_abstract_corpus/job.py` -- see that job's own docstring
for the precedent this one follows field-for-field.

WHAT THE MANUAL SEARCH ACTUALLY COVERS is recorded, verbatim, in
`configs/who_ictrp_queries.yaml`'s own `query_text` -- this job does not
re-derive or guess it; the exact search terms/filters used in the Search
Portal UI to produce a given export file are provenance a human must
supply (this repo has no other way to know what a person searched for
before clicking "Export").

Multiple accumulated export files are all read (glob `--corpus-dir` for
`ICTRP-Results-*.xml`, WHO's own default download filename shape, dated
YYYYMMDD): a trial appearing in more than one dated export keeps the
MOST RECENTLY DATED file's version of that trial (a live database can
change between two exports of the same saved search, and a later export
is a more current snapshot) -- this deliberately does NOT drop a trial
that disappears from a LATER export but was present in an OLDER one
(e.g. if a status filter or ICTRP's own indexing lag ever removed it),
since silently losing a previously-observed trial would violate this
repo's "content-version manifest never silently erases evidence"
discipline; that trial's LAST-KNOWN state just stops being refreshed
until it reappears.

DELIBERATELY ACQUISITION-ONLY, no extraction wiring yet (Prompt.md's own
acquisition/extraction boundary, same discipline Jobs 13/14 and the
conference abstract corpus job followed before their own later Phase-5
extraction wiring): this job's only claim is "this trial, aggregated by
WHO ICTRP from this Source_Register, was in this dated export." Feeding
trial titles/interventions from non-ClinicalTrials.gov `Source_Register`s
into `tools/breadth/candidate_queue.py`'s discovery signals is left for a
follow-up increment, once this job's own materialization is reviewed and
stable.

Three tables, same shape as `conference_abstract_corpus` (no live network
call, so no `failed`/`not_available` outcome class -- every candidate
record is either `success` (new-or-changed) or `skipped_unchanged`):
- who_ictrp.parquet             content-version manifest
- who_ictrp_discovery.parquet   append-only (record, query) ledger
- who_ictrp_attempts.parquet    append-only attempts ledger

Usage:
    python -m adc_acquisition who_ictrp \
        --corpus-dir DATA/raw/WHO_ICTRP \
        --output DATA
"""

from __future__ import annotations

import argparse
import glob
import json
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
from jobs.who_ictrp.parser import normalize_registration_date, parse_export_file
from jobs.who_ictrp.report import build_report

QUERIES_PATH = Path("configs/who_ictrp_queries.yaml")
DEFAULT_CORPUS_DIR = Path("DATA/raw/WHO_ICTRP")
QUERY_ID = "WHO_ICTRP_001"

EXTRA_FIELDS = [
    "source_register", "primary_sponsor", "secondary_sponsor", "phase",
    "recruitment_status", "countries", "intervention", "condition",
    "scientific_title", "target_size", "study_type", "other_records",
    "export_file_date",
]
LICENSE_NOTE = (
    "WHO ICTRP data, publicly downloadable at no charge via the Search Portal's own "
    "export function (https://trialsearch.who.int/); WHO ICTRP's terms require "
    "attribution and prohibit marketing/commercial use or asserting proprietary "
    "rights over the data -- see https://www.who.int/tools/clinical-trials-registry-"
    "platform/network/who-data-set/downloading-records-from-the-ictrp-database."
)

RAW_NAMESPACE = "raw_records"
DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]

EXPORT_FILE_RE = re.compile(r"ICTRP-Results-(\d{8})\.xml$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_export_files(corpus_dir: Path) -> list[tuple[str, Path]]:
    """Returns [(export_date_yyyymmdd, path), ...] sorted oldest-first, for
    every `ICTRP-Results-*.xml` file under `corpus_dir` -- WHO's own default
    download filename shape (verified against the real 2026-08-28 export).
    A file whose name doesn't match this shape is skipped (defensive: an
    unrelated file dropped in the same directory shouldn't crash the job)."""
    found = []
    for path_str in sorted(glob.glob(str(corpus_dir / "ICTRP-Results-*.xml"))):
        path = Path(path_str)
        m = EXPORT_FILE_RE.search(path.name)
        if not m:
            continue
        found.append((m.group(1), path))
    found.sort(key=lambda t: t[0])
    return found


def _load_all_trials(corpus_dir: Path) -> tuple[dict[str, dict], Counter]:
    """Returns (trial_by_id, export_file_counts). A TrialID present in more
    than one dated export keeps the MOST RECENTLY DATED file's version --
    see this module's own docstring for why an older-only trial is never
    silently dropped just because it merges from an earlier file."""
    export_files = _find_export_files(corpus_dir)
    trial_by_id: dict[str, dict] = {}
    export_file_counts: Counter = Counter()
    for export_date, path in export_files:
        export_file_counts["files"] += 1
        for trial in parse_export_file(path):
            trial_id = trial["TrialID"]
            if not trial_id:
                continue  # defensive: a malformed row with no TrialID has no usable identity
            trial["export_file_date"] = export_date
            trial_by_id[trial_id] = trial  # later (more recent) file wins, files iterated oldest-first
    return trial_by_id, export_file_counts


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    content_hash: str | None = None, version: int | None = None,
) -> dict:
    return dict(
        source="who_ictrp", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=None, error=None, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _content_manifest_row(
    trial: dict, source_record_id: str, query_id: str, query_text: str, raw_path: Path,
    content_hash: str, version: int, now: str,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="who_ictrp", source_record_id=source_record_id, source_record_type="clinical_trial",
        title=trial["Public_title"], url=trial["web_address"],
        publication_or_release_date=normalize_registration_date(trial["Date_registration3"]),
        retrieved_at=now, query_id=query_id, query_text=query_text,
        raw_file_path=str(raw_path), raw_format="json", content_hash=content_hash,
        download_status="success", http_status=None, license_or_access_note=LICENSE_NOTE,
        parent_record_id=None, version=version, notes=None,
        source_register=trial["Source_Register"], primary_sponsor=trial["Primary_sponsor"],
        secondary_sponsor=trial["Secondary_Sponsor"], phase=trial["Phase"],
        recruitment_status=trial["Recruitment_Status"], countries=trial["Countries"],
        intervention=trial["Intervention"], condition=trial["Condition"],
        scientific_title=trial["Scientific_title"], target_size=trial["Target_size"],
        study_type=trial["Study_type"], other_records=trial["other_records"],
        export_file_date=trial["export_file_date"],
    )


class WHOICTRPJob(AcquisitionJob):
    name = "who_ictrp"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--corpus-dir", type=str, default=str(DEFAULT_CORPUS_DIR),
            help=(
                "Directory containing one or more manually-exported WHO ICTRP "
                "'ICTRP-Results-YYYYMMDD.xml' files (Search Portal's own 'Export "
                "results to XML' button -- this job never queries WHO ICTRP over "
                "the network itself, see module docstring)."
            ),
        )
        parser.add_argument(
            "--queries-file", type=str, default=str(QUERIES_PATH),
            help="Path to the query registry documenting the manual search's provenance.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        corpus_dir = Path(args.corpus_dir)
        if not corpus_dir.exists():
            raise RuntimeError(
                f"WHO ICTRP corpus directory not found at {corpus_dir} -- this job reads a "
                "MANUALLY exported 'ICTRP-Results-YYYYMMDD.xml' file (Search Portal's own "
                "export button; see module docstring for why this job does not query WHO "
                f"ICTRP directly). Pass --corpus-dir, or place an export file at {corpus_dir}."
            )

        queries = load_queries(Path(args.queries_file))
        queries_by_id = {q.query_id: q for q in active_queries(queries)}
        if QUERY_ID not in queries_by_id:
            raise RuntimeError(f"{args.queries_file} is missing required active query_id={QUERY_ID}")
        query_spec = queries_by_id[QUERY_ID]

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: this job reads whatever export "
                "file(s) are present under --corpus-dir every run (cheap local file reads, no "
                "paginated remote query to resume from a cursor)."
            )

        trial_by_id, export_file_counts = _load_all_trials(corpus_dir)
        if not trial_by_id:
            raise RuntimeError(
                f"0 trials found under {corpus_dir} -- confirm --corpus-dir is correct and "
                "contains at least one 'ICTRP-Results-YYYYMMDD.xml' export file."
            )

        all_ids = sorted(trial_by_id.keys())
        source_register_counts = Counter(trial_by_id[tid]["Source_Register"] for tid in all_ids)
        result.queries_run = 1
        result.records_discovered = len(all_ids)

        discovery_path = output_dir / "manifests" / f"{self.name}_discovery.parquet"
        attempts_path = output_dir / "manifests" / f"{self.name}_attempts.parquet"

        now = _now_iso()
        run_id = now
        discovery_rows = [
            dict(
                source=self.name, source_record_id=tid, query_id=QUERY_ID,
                query_version=query_spec.query_version, query_text=query_spec.query_text,
                discovered_at=run_id, run_id=run_id,
            )
            for tid in all_ids
        ]

        # Same rationale as conference_abstract_corpus: no network fetch to
        # save by trusting a prior status without rechecking, since the
        # trial is already fully loaded in memory from a local file read --
        # always recompute and compare content_hash directly.
        changed_ids: list[str] = []
        unchanged_ids: list[str] = []
        raw_bytes_by_id: dict[str, bytes] = {}
        content_hash_by_id: dict[str, str] = {}
        for tid in all_ids:
            raw_bytes = json.dumps(trial_by_id[tid], sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
            content_hash = sha256_bytes(raw_bytes)
            raw_bytes_by_id[tid] = raw_bytes
            content_hash_by_id[tid] = content_hash
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, tid, namespace=RAW_NAMESPACE)
            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                unchanged_ids.append(tid)
            else:
                changed_ids.append(tid)

        target_ids = changed_ids[: args.limit] if args.limit else changed_ids

        if args.dry_run:
            result.notes.append(
                f"dry-run: would materialize {len(target_ids)} of {len(all_ids)} candidate trials "
                f"across {export_file_counts.get('files', 0)} export file(s) -- {len(changed_ids)} "
                f"new-or-changed, {len(unchanged_ids)} unchanged and would be skipped."
            )
            return result

        manifest_path = output_dir / "manifests" / f"{self.name}.parquet"
        content_rows = []
        attempt_rows = []
        outcome_counts: Counter = Counter()

        for tid in unchanged_ids:
            result.records_skipped_unchanged += 1
            outcome_counts["skipped_unchanged"] += 1
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, tid, namespace=RAW_NAMESPACE)
            attempt_rows.append(_record_row(
                tid, now, now, "skipped_unchanged", QUERY_ID, query_spec.query_text,
                content_hash=content_hash_by_id[tid],
                version=raw_prior_state["version"] if raw_prior_state else None,
            ))

        for tid in target_ids:
            content_hash = content_hash_by_id[tid]
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, tid, namespace=RAW_NAMESPACE)
            version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
            raw_dir = output_dir / "raw" / self.name / tid.replace("/", "_").replace(":", "_")
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"v{version}.json"
            raw_path.write_bytes(raw_bytes_by_id[tid])
            checkpoint_store.set_record_state(checkpoint, tid, content_hash, version, now, namespace=RAW_NAMESPACE)
            checkpoint_store.save(checkpoint)

            result.records_downloaded += 1
            outcome_counts["success"] += 1
            attempt_rows.append(_record_row(tid, now, now, "success", QUERY_ID, query_spec.query_text, content_hash=content_hash, version=version))
            content_rows.append(_content_manifest_row(trial_by_id[tid], tid, QUERY_ID, query_spec.query_text, raw_path, content_hash, version, now))

        manifest_df = write_manifest(content_rows, manifest_path, extra_fields=EXTRA_FIELDS)
        append_only(discovery_rows, discovery_path, DISCOVERY_COLUMNS)
        append_only(attempt_rows, attempts_path, ATTEMPT_COLUMNS)
        result.manifest_path = str(manifest_path)

        total_outcomes = result.records_downloaded + result.records_skipped_unchanged
        result.notes.append(
            f"this run: {result.records_downloaded} success, {result.records_skipped_unchanged} skipped_unchanged "
            f"({total_outcomes} total attempted/fast-skipped outcomes); corpus dir: {corpus_dir} "
            f"({export_file_counts.get('files', 0)} export file(s))."
        )
        if len(changed_ids) > len(target_ids):
            result.notes.append(
                f"{len(changed_ids) - len(target_ids)} new-or-changed trial(s) deferred to a future run by --limit."
            )

        checkpoint["last_run_at"] = now
        checkpoint_store.save(checkpoint)

        ctgov_manifest_path = output_dir / "manifests" / "clinicaltrials.parquet"
        report_path = output_dir.parent / "reports" / "acquisition" / f"{self.name}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(
                result, manifest_df, all_ids, changed_ids, unchanged_ids,
                source_register_counts, export_file_counts, outcome_counts,
                corpus_dir, ctgov_manifest_path,
            ),
            encoding="utf-8",
        )

        return result
