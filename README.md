# adc-acquisition

A source-separated raw evidence acquisition pipeline for an antibody–drug
conjugate (ADC) knowledgebase. See `Prompt.md` for the full specification
this repository implements.

This is **acquisition only**: it answers "what source documents exist, where
did they come from, when were they retrieved, what did the source say" — it
never decides what the canonical ADC record is, which duplicates should be
merged, or which biological activity value should be trusted. Those are
downstream concerns.

## Architecture

```text
SOURCE → DISCOVERY → IDENTIFIER COLLECTION → RAW DOWNLOAD
       → METADATA NORMALIZATION → MANIFEST → DOWNSTREAM EXTRACTION
```

Each external source is an independent job under `jobs/<source>/`. One
source failing must never block another. Jobs share infrastructure from
`adc_acquisition/`:

- `job_base.py` — the `AcquisitionJob` interface: every job exposes the same
  `--dry-run/--limit/--resume/--since/--until/--output` CLI surface.
- `http_utils.py` — rate-limited, retrying HTTP client (exponential backoff,
  `Retry-After` support).
- `checkpoint.py` — per-job JSON checkpoint (`DATA/checkpoints/<job>.json`)
  tracking each record's content hash/version, so unchanged records aren't
  redundantly re-downloaded and incremental runs can resume by date.
- `manifest.py` — two table shapes:
  - `write_manifest` (upsert, keyed by `(source, source_record_id, version)`)
    for the **content-version manifest** — one row per evidence snapshot that
    was actually materialized. A failed fetch has no content and must never
    occupy a version slot here, or a later failure could silently overwrite
    an earlier successful snapshot at the same key.
  - `append_only` (no upsert/dedup, every run just adds rows) for **ledger**
    tables: which query discovered a record (every discovering query, not
    just the first) and which attempts (success/skipped/failed) were made.
- `query_registry.py` — loads a source's query provenance from YAML
  (e.g. `configs/pubmed_queries.yaml`) so every record is traceable back to
  the exact query that discovered it.
- `logging_utils.py` — per-job log + a dedicated failed-identifier log
  (`DATA/logs/<job>_failures.log`); failures are recorded, never dropped.

`configs/sources.yaml` is the source registry: one entry per planned source,
tracking its access mechanism and `implementation_status`.

## Repository layout

```text
adc_acquisition/     shared infrastructure (see above)
jobs/<source>/       one independent acquisition job per source
configs/             source registry + per-source query registries
DATA/
  raw/               raw downloaded documents — gitignored, can get large
  manifests/         normalized parquet manifests — small, committed
  logs/               per-job logs — gitignored
  checkpoints/        per-job resume state — gitignored
reports/acquisition/  per-source validation report + COVERAGE.md matrix
tests/               unit tests, HTTP mocked (no live network needed)
```

Only `DATA/manifests/` (structured metadata, not raw documents) and
`reports/` are meant to live in git — see `.gitignore`. Raw HTML/XML/PDF
corpora stay local or in external storage; that's what keeps this repo small
enough for GitHub regardless of how much evidence has been acquired.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in NCBI_API_KEY (optional) and NCBI_CONTACT_EMAIL
```

## Running the PubMed job (Job 01)

```bash
python -m adc_acquisition pubmed --dry-run --limit 20
python -m adc_acquisition pubmed --limit 20
python -m adc_acquisition pubmed --resume            # incremental, from last checkpoint
python -m adc_acquisition pubmed --since 2024-01-01 --until 2024-12-31
```

Each run writes/updates:

- `DATA/manifests/pubmed.parquet` — content-version manifest (evidence
  snapshots only; never contains a failed attempt).
- `DATA/manifests/pubmed_discovery.parquet` — append-only ledger of every
  (PMID, discovering query, run) triple — the full answer to "why is this
  document in our corpus," not just the one primary query_id the content
  manifest carries per Prompt.md's single-valued contract.
- `DATA/manifests/pubmed_attempts.parquet` — append-only ledger of every
  fetch attempt (success / skipped_unchanged / failed) per run, so failures
  stay auditable without ever touching evidence-snapshot state.
- `DATA/raw/pubmed/<pmid>/v<N>.xml`, `DATA/checkpoints/pubmed.json`
  (`source_record_id -> content_hash/version`), and
  `reports/acquisition/pubmed.md`.

### Monthly incremental updates

`DATA/checkpoints/pubmed.json` is the index for this: for every PMID it
already holds the content hash and version last seen. A monthly
`python -m adc_acquisition pubmed --resume` run:

1. narrows the query date window to everything since the last successful
   run (`last_success_max_date` in the checkpoint), so it doesn't even
   re-query records outside that window;
2. for anything it does discover, looks up the PMID in the checkpoint —
   absent means new, present with a matching content hash means unchanged
   (skipped, logged in the attempts ledger only), present with a different
   hash means changed (new version row, old raw snapshot never deleted).

No separate index needs to be built for this — the checkpoint plus the two
ledgers above already are that index. The same model (content manifest +
discovery ledger + attempts ledger + checkpoint) is reused as-is for every
subsequent job, including Europe PMC below.

## Running the Europe PMC job (Job 02)

```bash
python -m adc_acquisition europe_pmc --dry-run --limit 20
python -m adc_acquisition europe_pmc --limit 20
python -m adc_acquisition europe_pmc --resume
python -m adc_acquisition europe_pmc --since 2024-01-01 --until 2024-12-31
```

Same three-table + checkpoint model as PubMed
(`DATA/manifests/europe_pmc{,_discovery,_attempts}.parquet`,
`DATA/checkpoints/europe_pmc.json`), no API key required. One addition: for
records Europe PMC itself marks `isOpenAccess=Y`, this job also fetches the
JATS full-text XML (`fullTextXML` endpoint) — publisher paywalls are never
bypassed. Full text is modeled as its own independent content-version
artifact (`europe_pmc_fulltext.parquet` + `europe_pmc_fulltext_attempts.parquet`,
keyed by `pmcid` with `parent_record_id` linking back to the metadata
record, its own checkpoint namespace) rather than a field on the metadata
row — a full-text fetch failure or a later successful retry never touches
the metadata record's own content-version snapshot, and the full-text XML
itself can be re-versioned independently if it ever changes. No
deduplication against the PubMed manifest happens here — a paper in both
sources keeps two independent evidence rows by design (Prompt.md section 6);
`pmid`/`doi` are preserved so a downstream system can join them.

## Running the ClinicalTrials.gov job (Job 03)

```bash
python -m adc_acquisition clinicaltrials --dry-run --limit 20
python -m adc_acquisition clinicaltrials --limit 20
python -m adc_acquisition clinicaltrials --resume
python -m adc_acquisition clinicaltrials --since 2024-01-01 --until 2024-12-31
python -m adc_acquisition clinicaltrials --intervention "trastuzumab deruxtecan" --limit 20
```

Same three-table + checkpoint model
(`DATA/manifests/clinicaltrials{,_discovery,_attempts}.parquet`,
`DATA/checkpoints/clinicaltrials.json`), no API key required. Unlike
PubMed/Europe PMC, the ClinicalTrials.gov API v2 search endpoint returns
each trial's *complete* record inline — there's no separate "fetch full
record" step, so the content-version snapshot is exactly that search
result. `--intervention "<name>"` is the known-asset lookup capability
Prompt.md section 10.B asks for: it searches `query.intr` instead of the
broad query family in `configs/clinicaltrials_queries.yaml` — implemented
as a capability here, not yet wired into a systematic asset-expansion pass
(that's Job 15).

## Tests

```bash
pytest
```

All tests mock HTTP (via `responses`) — no live network access is required
or used by the normal test suite.

## Status

See `reports/acquisition/COVERAGE.md`. Only Job 01 (PubMed), Job 02
(Europe PMC), and Job 03 (ClinicalTrials.gov) are implemented so far; every
other source in `Prompt.md` is intentionally not started yet — sources are
implemented and reviewed one at a time.
