"""China CDE (Center for Drug Evaluation) drug clinical trial registry
acquisition -- chinadrugtrials.org.cn's "药物临床试验登记与信息公示平台"
(Drug Clinical Trial Registration and Information Disclosure Platform),
NMPA's mandatory drug-trial disclosure system.

Source-coverage expansion, per the reviewer's V1.1 priority list item #2
(China regulatory/clinical disclosure): WHO ICTRP (this repo's other new
2026-08 source) aggregates ChiCTR, but ChiCTR is a SEPARATE registry from
CDE's own mandatory drug-trial disclosure platform -- live research
confirmed these are two distinct systems with disjoint ID namespaces
(ChiCTR IDs look like "ChiCTR2600000001"; CDE's own registration numbers
look like "CTR20262727"). ADC development is heavily China-weighted right
now, and an asset can enter Phase 1/2, priority review, or approval in
China well before it appears on ClinicalTrials.gov or at a Western
conference -- this source targets exactly that lag.

INTERIM ACCESS MODEL (disclosed, not silently narrowed -- reviewer-
confirmed 2026-08-31). Live research found chinadrugtrials.org.cn's
functional pages (search form, results listing, disclaimer) are a
client-side-rendered SPA that returns empty content to a plain HTTP
fetch -- this project's tools cannot determine from that alone whether
automated access is permitted. No `robots.txt` exists on the domain
(404, not a Disallow list -- genuinely absent, not evidence either way).
The platform's own Disclaimer page could not be read from this
environment. **AUTOMATION PERMISSION STATUS: UNKNOWN** -- neither
confirmed-permitted nor confirmed-prohibited. Given that ambiguity, this
job makes ZERO network requests to chinadrugtrials.org.cn, identical in
spirit to this repo's WHO ICTRP job: it reads a MANUALLY downloaded
search-results export file that a human produces via the results page's
own "下载" (download) button and drops into `--corpus-dir` (default
`DATA/raw/chinadrugtrials/`, gitignored like every other `DATA/raw/`
path). nmpa.gov.cn itself was found to be completely unreachable from
this environment (connection-level block, not a 403) and is out of
scope for this job entirely.

WHAT THE MANUAL SEARCH ACTUALLY COVERS is recorded, verbatim, in
`configs/china_drug_trials_queries.yaml`'s own `query_text` per export
file -- this job does not re-derive or guess it (same discipline as WHO
ICTRP's `query_text`). Two confirmed search terms exist as of this job's
first round: a bare `"ADC"` acronym search and a targeted `"抗体药物偶联物"`
(Chinese for "antibody-drug conjugate") search.

DISCLOSED FINDING: BOTH terms produced substantial false positives, and
neither can be called "the clean one." The bare acronym matches an
internal drug-code numbering prefix used by some sponsor(s) for unrelated
products ("ADC189"/"ADC118"/"ADC308" -- an influenza antiviral, an HIV
drug, an endometriosis drug) and the unrelated "AADC" (enzyme-deficiency)
acronym -- expected. More surprisingly, the TARGETED Chinese-phrase search
ALSO returned results with no plausible ADC connection at all (ethambutol,
an anti-tuberculosis drug; an HIV combination pill) -- not explainable by
acronym ambiguity, indicating chinadrugtrials.org.cn's search matches
against a field not visible in the list-page columns (most likely a
protocol/reference number, not drug content). See
`configs/china_drug_trials_queries.yaml`'s own file-level comment for the
full writeup. This job does NOT filter for relevance itself -- both
queries' full result sets are materialized as-is, per this repo's
"acquire broadly, filter downstream" principle; a future round should try
searching by known ADC asset names/development codes and known ADC
company/applicant names instead of a single broad term.

PER-EXPORT-FILE QUERY ATTRIBUTION (same fix as WHO ICTRP's round-1,
generalized to filenames): unlike WHO ICTRP's own default download
filename (`ICTRP-Results-YYYYMMDD.xml`, which self-encodes a date), CDE's
downloaded file has no project-meaningful default name -- a human must
name each file and explicitly register it, alongside the export date it
was actually produced on, under whichever query produced it, in
`configs/china_drug_trials_queries.yaml`'s per-query `exports: [{filename,
export_date}, ...]` list. Every `*.xls` file present under `--corpus-dir`
that isn't registered under some query is a hard RuntimeError, never a
silent guess (see `_load_export_filename_query_map`/`_query_for` below).

NO DETAIL-PAGE DATA THIS ROUND (deliberately acquisition-foundation-only):
the search-results export gives only 6 columns (registration_number,
trial_status, drug_name, indication, public_title) -- it does NOT include
applicant/sponsor, phase, enrollment, or the internal UUID that would let
this job construct a stable detail-page URL (verified: no hyperlink data
exists in the raw export XML at all). Fetching those would require a live
page visit per record, which this round does not do given the UNKNOWN
automation-permission status above. A follow-up increment (#36B) can add
detail-page materialization once terms/access are clearer, keyed off the
SAME `registration_number` identity this round establishes.

Three tables, same shape as WHO ICTRP (no live network call, so no
`failed`/`not_available` outcome class):
- china_drug_trials.parquet             content-version manifest
- china_drug_trials_discovery.parquet   append-only (record, query) ledger
- china_drug_trials_attempts.parquet    append-only attempts ledger

Usage:
    python -m adc_acquisition china_drug_trials \
        --corpus-dir DATA/raw/chinadrugtrials \
        --output DATA
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from adc_acquisition.checkpoint import CheckpointStore
from adc_acquisition.hashing import sha256_bytes
from adc_acquisition.job_base import AcquisitionJob, JobRunResult
from adc_acquisition.logging_utils import setup_job_logging
from adc_acquisition.manifest import append_only, new_manifest_row, write_manifest
from adc_acquisition.query_registry import QuerySpec, active_queries, load_queries
from jobs.china_drug_trials.parser import parse_export_file
from jobs.china_drug_trials.report import build_report

QUERIES_PATH = Path("configs/china_drug_trials_queries.yaml")
DEFAULT_CORPUS_DIR = Path("DATA/raw/chinadrugtrials")

EXTRA_FIELDS = ["trial_status", "drug_name", "indication", "export_filename", "export_date"]
LICENSE_NOTE = (
    "CDE (Center for Drug Evaluation, NMPA) drug clinical trial registration and "
    "information disclosure platform (chinadrugtrials.org.cn); publicly viewable via a "
    "human-operated search + \"download search results\" export function, confirmed live "
    "2026-08-31. AUTOMATION PERMISSION STATUS: UNKNOWN -- no robots.txt exists on this "
    "domain, and the platform's own Disclaimer page could not be read from this "
    "environment (client-side-rendered). This project has NEITHER confirmed explicit "
    "permission NOR an explicit prohibition on automated access, so this job makes ZERO "
    "network requests to chinadrugtrials.org.cn -- it reads only a human-downloaded "
    "search-results export file, identical in spirit to this repo's WHO ICTRP job."
)

RAW_NAMESPACE = "raw_records"
DISCOVERY_COLUMNS = ["source", "source_record_id", "query_id", "query_version", "query_text", "discovered_at", "run_id"]
ATTEMPT_COLUMNS = [
    "source", "source_record_id", "run_id", "attempted_at", "status",
    "http_status", "error", "query_id", "query_text", "content_hash", "version",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_export_files(corpus_dir: Path) -> list[Path]:
    """Every `*.xls` file directly under `corpus_dir` -- CDE's downloaded
    file has no project-meaningful default name (unlike WHO ICTRP's own
    dated filename), so this globs broadly and relies entirely on
    `configs/china_drug_trials_queries.yaml`'s explicit per-filename
    registration (see module docstring) to attribute -- and validate --
    every file found."""
    return sorted(Path(p) for p in glob.glob(str(corpus_dir / "*.xls")))


def _load_export_filename_query_map(
    queries_file: Path, queries: list[QuerySpec],
) -> dict[str, tuple[QuerySpec, str]]:
    """Reads `exports` -- a china_drug_trials-specific field NOT part of
    the shared `QuerySpec` shape (see `adc_acquisition.query_registry`) --
    directly from the raw YAML, same reason as WHO ICTRP's own
    `_load_export_date_query_map`: `query_registry.load_queries()` silently
    drops unknown keys for config forward-compatibility, not to hide a
    field this exact loader needs.

    Returns {filename: (QuerySpec, export_date)} -- the query a human
    actually ran to produce that specific named export file, and the date
    they ran it on. Every trial is attributed via its OWN export file,
    never a single job-wide constant, so a bare-"ADC" export (high false-
    positive rate) can coexist with a targeted "抗体药物偶联物" export
    without either being mislabeled as the other's provenance.

    Raises on: an `exports` entry naming a query_id that isn't in the
    registry at all, or two different queries both claiming the same
    filename (an unresolvable provenance conflict a human must fix by
    hand, not something this job should silently pick a winner for)."""
    with Path(queries_file).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    by_id = {q.query_id: q for q in queries}
    filename_to_query: dict[str, tuple[QuerySpec, str]] = {}
    for entry in raw.get("queries", []):
        query_id = entry["query_id"]
        if query_id not in by_id:
            raise ValueError(f"{queries_file}: exports references unknown query_id={query_id!r}")
        for export in entry.get("exports", []):
            filename = export["filename"]
            export_date = export["export_date"]
            if filename in filename_to_query:
                raise ValueError(
                    f"{queries_file}: export filename={filename!r} is claimed by both "
                    f"{filename_to_query[filename][0].query_id!r} and {query_id!r} -- each "
                    "downloaded export file must be attributed to exactly one query."
                )
            filename_to_query[filename] = (by_id[query_id], export_date)
    return filename_to_query


def _load_all_trials(
    corpus_dir: Path, filename_to_query: dict[str, tuple[QuerySpec, str]],
) -> tuple[dict[str, dict], Counter]:
    """Returns (trial_by_registration_number, export_file_counts). A
    registration_number present in more than one export file keeps the
    MOST RECENTLY DATED file's version (same "later export is a more
    current snapshot" rationale as WHO ICTRP) -- files are processed in
    ascending export_date order (from the query registry, NOT filename
    lexical order, since CDE filenames carry no reliable date)."""
    files = [f for f in _find_export_files(corpus_dir) if f.name in filename_to_query]
    files.sort(key=lambda f: filename_to_query[f.name][1])
    trial_by_regnum: dict[str, dict] = {}
    export_file_counts: Counter = Counter()
    for path in files:
        _, export_date = filename_to_query[path.name]
        export_file_counts["files"] += 1
        for trial in parse_export_file(path):
            regnum = trial["registration_number"]
            if not regnum:
                continue  # defensive: a malformed row with no registration number has no usable identity
            trial["export_filename"] = path.name
            trial["export_date"] = export_date
            trial_by_regnum[regnum] = trial  # later (more recent) file wins, files iterated oldest-first
    return trial_by_regnum, export_file_counts


def _record_row(
    source_record_id: str, run_id: str, attempted_at: str, status: str, query_id: str, query_text: str,
    content_hash: str | None = None, version: int | None = None,
) -> dict:
    return dict(
        source="china_drug_trials", source_record_id=source_record_id, run_id=run_id, attempted_at=attempted_at,
        status=status, http_status=None, error=None, query_id=query_id, query_text=query_text,
        content_hash=content_hash, version=version,
    )


def _content_manifest_row(
    trial: dict, source_record_id: str, query_id: str, query_text: str, raw_path: Path,
    content_hash: str, version: int, now: str,
) -> dict:
    return new_manifest_row(
        extra_fields=EXTRA_FIELDS,
        source="china_drug_trials", source_record_id=source_record_id, source_record_type="clinical_trial",
        title=trial["public_title"], url=None,
        publication_or_release_date=None,
        retrieved_at=now, query_id=query_id, query_text=query_text,
        raw_file_path=str(raw_path), raw_format="json", content_hash=content_hash,
        download_status="success", http_status=None, license_or_access_note=LICENSE_NOTE,
        parent_record_id=None, version=version, notes=None,
        trial_status=trial["trial_status"], drug_name=trial["drug_name"],
        indication=trial["indication"], export_filename=trial["export_filename"],
        export_date=trial["export_date"],
    )


class ChinaDrugTrialsJob(AcquisitionJob):
    name = "china_drug_trials"

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--corpus-dir", type=str, default=str(DEFAULT_CORPUS_DIR),
            help=(
                "Directory containing one or more manually-downloaded chinadrugtrials.org.cn "
                "search-results export files (results page's own \"下载\" button -- this job "
                "never queries chinadrugtrials.org.cn over the network itself, see module "
                "docstring)."
            ),
        )
        parser.add_argument(
            "--queries-file", type=str, default=str(QUERIES_PATH),
            help="Path to the query registry documenting each manual search's provenance.",
        )

    def run(self, args: argparse.Namespace) -> JobRunResult:
        output_dir = Path(args.output)
        logger, failure_logger = setup_job_logging(self.name, output_dir)
        checkpoint_store = CheckpointStore(self.name, output_dir)
        checkpoint = checkpoint_store.load()

        corpus_dir = Path(args.corpus_dir)
        if not corpus_dir.exists():
            raise RuntimeError(
                f"chinadrugtrials.org.cn corpus directory not found at {corpus_dir} -- this job "
                "reads a MANUALLY downloaded search-results export file (results page's own "
                "\"下载\" button; see module docstring for why this job does not query "
                f"chinadrugtrials.org.cn directly). Pass --corpus-dir, or place an export file "
                f"at {corpus_dir}."
            )

        queries = load_queries(Path(args.queries_file))
        if not active_queries(queries):
            raise RuntimeError(f"{args.queries_file} has no active queries")
        filename_to_query = _load_export_filename_query_map(Path(args.queries_file), queries)

        result = JobRunResult(job_name=self.name, dry_run=bool(args.dry_run))
        if args.resume:
            result.notes.append(
                "--resume is a no-op beyond default behavior: this job reads whatever export "
                "file(s) are present under --corpus-dir every run (cheap local file reads, no "
                "paginated remote query to resume from a cursor)."
            )

        present_files = {f.name for f in _find_export_files(corpus_dir)}
        unmapped_files = sorted(present_files - filename_to_query.keys())
        if unmapped_files:
            raise RuntimeError(
                f"{args.queries_file} has no query attributed to export file(s) "
                f"{unmapped_files} -- add an `exports` entry (filename + export_date) under "
                "the query a human actually ran to produce that downloaded file before this "
                "job can attribute its trials (never guessing which query a file came from)."
            )

        trial_by_regnum, export_file_counts = _load_all_trials(corpus_dir, filename_to_query)
        if not trial_by_regnum:
            raise RuntimeError(
                f"0 trials found under {corpus_dir} -- confirm --corpus-dir is correct and "
                "contains at least one downloaded search-results export file."
            )

        all_ids = sorted(trial_by_regnum.keys())

        def _query_for(regnum: str) -> QuerySpec:
            return filename_to_query[trial_by_regnum[regnum]["export_filename"]][0]

        result.queries_run = len({q.query_id for q, _ in filename_to_query.values()})
        result.records_discovered = len(all_ids)

        discovery_path = output_dir / "manifests" / f"{self.name}_discovery.parquet"
        attempts_path = output_dir / "manifests" / f"{self.name}_attempts.parquet"

        now = _now_iso()
        run_id = now
        discovery_rows = []
        for regnum in all_ids:
            q = _query_for(regnum)
            discovery_rows.append(dict(
                source=self.name, source_record_id=regnum, query_id=q.query_id,
                query_version=q.query_version, query_text=q.query_text,
                discovered_at=run_id, run_id=run_id,
            ))

        # Same rationale as WHO ICTRP: no network fetch to save by trusting a
        # prior status without rechecking, since the trial is already fully
        # loaded in memory from a local file read -- always recompute and
        # compare content_hash directly.
        changed_ids: list[str] = []
        unchanged_ids: list[str] = []
        raw_bytes_by_id: dict[str, bytes] = {}
        content_hash_by_id: dict[str, str] = {}
        for regnum in all_ids:
            trial = trial_by_regnum[regnum]
            raw_bytes = json.dumps(trial, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
            # content_hash deliberately excludes export_filename/export_date:
            # they're provenance about WHICH download produced this row, not
            # part of the trial's own content -- a human may re-download the
            # same search under a new filename/date even when the trial's
            # real content hasn't changed, and folding these into the hash
            # would bump every unchanged trial's version on every re-run.
            hashable = {k: v for k, v in trial.items() if k not in ("export_filename", "export_date")}
            content_hash = sha256_bytes(json.dumps(hashable, sort_keys=True, ensure_ascii=False).encode("utf-8"))
            raw_bytes_by_id[regnum] = raw_bytes
            content_hash_by_id[regnum] = content_hash
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, regnum, namespace=RAW_NAMESPACE)
            if raw_prior_state and raw_prior_state.get("content_hash") == content_hash:
                unchanged_ids.append(regnum)
            else:
                changed_ids.append(regnum)

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

        for regnum in unchanged_ids:
            result.records_skipped_unchanged += 1
            outcome_counts["skipped_unchanged"] += 1
            q = _query_for(regnum)
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, regnum, namespace=RAW_NAMESPACE)
            attempt_rows.append(_record_row(
                regnum, now, now, "skipped_unchanged", q.query_id, q.query_text,
                content_hash=content_hash_by_id[regnum],
                version=raw_prior_state["version"] if raw_prior_state else None,
            ))

        for regnum in target_ids:
            content_hash = content_hash_by_id[regnum]
            raw_prior_state = checkpoint_store.get_record_state(checkpoint, regnum, namespace=RAW_NAMESPACE)
            version = (raw_prior_state["version"] + 1) if raw_prior_state else 1
            raw_dir = output_dir / "raw" / self.name / regnum.replace("/", "_")
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"v{version}.json"
            raw_path.write_bytes(raw_bytes_by_id[regnum])
            checkpoint_store.set_record_state(checkpoint, regnum, content_hash, version, now, namespace=RAW_NAMESPACE)
            checkpoint_store.save(checkpoint)

            result.records_downloaded += 1
            outcome_counts["success"] += 1
            q = _query_for(regnum)
            attempt_rows.append(_record_row(regnum, now, now, "success", q.query_id, q.query_text, content_hash=content_hash, version=version))
            content_rows.append(_content_manifest_row(trial_by_regnum[regnum], regnum, q.query_id, q.query_text, raw_path, content_hash, version, now))

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

        report_path = output_dir.parent / "reports" / "acquisition" / f"{self.name}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            build_report(
                result, manifest_df, all_ids, changed_ids, unchanged_ids,
                export_file_counts, outcome_counts, corpus_dir, output_dir,
            ),
            encoding="utf-8",
        )

        return result
