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
- `manifest.py` — the universal manifest contract (common columns every
  source must populate) plus per-source extra columns, upserted into
  `DATA/manifests/<job>.parquet` keyed by `(source, source_record_id, version)`.
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

Each run writes/updates `DATA/manifests/pubmed.parquet`,
`DATA/raw/pubmed/<pmid>/v<N>.xml`, `DATA/checkpoints/pubmed.json`, and
regenerates `reports/acquisition/pubmed.md`.

## Tests

```bash
pytest
```

All tests mock HTTP (via `responses`) — no live network access is required
or used by the normal test suite.

## Status

See `reports/acquisition/COVERAGE.md`. Only Job 01 (PubMed) is implemented
so far; every other source in `Prompt.md` is intentionally not started yet —
sources are implemented and reviewed one at a time.
