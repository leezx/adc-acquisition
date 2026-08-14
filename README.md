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
cp .env.example .env   # fill in NCBI_API_KEY (optional), NCBI_CONTACT_EMAIL,
                        # CROSSREF_CONTACT_EMAIL (optional), SEC_CONTACT_EMAIL
                        # (required for the SEC job), and FDA_API_KEY (optional)
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

## Running the Crossref job (Job 04)

```bash
python -m adc_acquisition crossref --dry-run --limit 20
python -m adc_acquisition crossref --limit 20
python -m adc_acquisition crossref --doi "10.1001/example.doi" --limit 1
```

This job is **DOI-centric reconciliation, not broad discovery** — verified
live that Crossref's `query.bibliographic`/`query.title` params are
relevance-ranked free text, not phrase/boolean search (`query.title="antibody-drug
conjugate"` returned 860,937 hits), so there is no query-family config file
here. Instead it reads non-null `doi` values out of other jobs' manifests
(`configs/crossref_reconciliation_sources.yaml` — currently PubMed and
Europe PMC) and looks each one up via Crossref's authoritative `GET
/works/{doi}`, which returns richer bibliographic metadata (publisher,
license, references, container-title) than either of those capture on
their own. `--doi "<doi>"` is an ad hoc single-DOI lookup mode, independent
of the reconciliation-sources registry — passing `--doi` skips reading the
registry entirely, it never also pulls in every upstream DOI; each distinct
DOI gets its own deterministic query_id (a hash of the DOI), same pattern
as ClinicalTrials.gov's `--intervention`. `--since`/`--until`/`--resume`
are accepted but explicitly not applicable (noted in the result/report,
not silently ignored): this job does exact per-DOI lookups, not a `/works?`
collection query, so there's no date-filterable request to apply them to
(Crossref's collection endpoint does support date filters — this job just
never calls it). The checkpoint's content-hash comparison runs on every DOI
every run regardless of `--resume`; what it avoids is redundant
materialization (rewriting a snapshot or creating a spurious version), not
the network call itself. Reconciliation only ever reads each upstream
record's *latest* content version — an upstream DOI correction in a newer
version supersedes the old one rather than both being reconciled forever.

## Running the SEC EDGAR job (Job 05)

```bash
python -m adc_acquisition sec --dry-run --limit 20
python -m adc_acquisition sec --limit 20
python -m adc_acquisition sec --company seagen --limit 20
python -m adc_acquisition sec --since 2022-01-01 --until 2024-12-31
```

**Requires `SEC_CONTACT_EMAIL`** to be set (`.env` or environment) — SEC's
fair access policy requires every request to carry a real identifying
`User-Agent` (name/tool + contact) or it's rejected with HTTP 403 and the
source IP may be briefly blocked; this job refuses to run without one
rather than sending a placeholder that would violate that policy. Company-
centric, not query-based: `configs/company_registry.yaml` is a curated list
of ADC-relevant filers with CIKs verified live against SEC's own lookup
services. Each registry entry's `ciks` is a list, not a single value — a
corporate redomicile/reincorporation creates a brand-new SEC filer identity
with its own CIK and filing history (confirmed live for Zymeworks, which
redomiciled from British Columbia to Delaware in 2022; its pre-2022 history
is under a different CIK), so a company can have more than one. Every CIK
gets its own `query_id` (`SEC_FILINGS_{company_id}_{cik}`). For each active
CIK this job pulls its *entire* relevant-form filing history (10-K/10-Q/8-K/
S-1/20-F/6-K + amendments — `jobs/sec/parser.py:RELEVANT_FORMS`) via the
submissions API — `--limit` only caps how many filings get materialized,
not how many are discovered. `--company "<company_id>"` restricts a run to
one registry entry (all of that company's CIKs). `--since`/`--until` filter
by SEC's own `filing_date`, applied client-side (the submissions API has no
server-side date filter); `--resume` reuses the prior run's `--until` (or
run time) as an implicit `--since`. That resume cursor always advances,
even when some filings failed this run — some historical gaps are
permanent (the pre-2002 `primaryDocument` issue below) and must not block
all future incremental progress — but any filing or exhibit that's still
unresolved (never had a successful attempt) is explicitly unioned back
into scope on the next `--resume` run regardless of its `filing_date`, so
it can never silently age out of every future incremental run just because
the cursor passed it. This union only kicks in for the *implicit*
resume cursor — an explicit `--since` you type yourself is trusted
literally, same as every other job. Two more protections keep that retry
union itself well-behaved: the filing-index page fetch has its own
success/failure attempt identity (so a resolved filing-index failure
actually leaves the retry set, instead of being stuck on its one and
only ever-recorded "failed" row forever), and unambiguously permanent
conditions (`no_primary_document`) are excluded from the retry set while
fresh/in-range filings always get priority over backlog retries within a
`--limit` budget — so a handful of permanently-broken historical filings
can never occupy every `--resume` run's budget and starve out genuinely
new ones.

Exhibits are a separate, independently versioned artifact
(`DATA/manifests/sec_exhibits{,_attempts}.parquet`, keyed by
`{accession_number}:{filename}` with `parent_record_id` pointing back to
the filing) — same pattern as Europe PMC's full text, so an exhibit fetch
failure or later retry never touches the filing's own content-version
snapshot. A document only counts as an exhibit if SEC's own filing index
page (`{accession-number}-index.htm`'s "Document Format Files" table)
types it `EX-*`, not merely "any non-primary file in the filing
directory" — that would also sweep in GRAPHIC/embedded-image and XBRL
support files, which are not exhibits. Exhibit acquisition is attempted for
every target filing regardless of whether that filing's own primary
document succeeded, failed, or was unchanged. Some pre-2002 filings have
missing/incorrect primary-document metadata on SEC's own side; that
surfaces as an expected, logged failed attempt, not a crash.

## Running the FDA job (Job 06)

```bash
python -m adc_acquisition fda --dry-run --limit 20
python -m adc_acquisition fda --limit 20
python -m adc_acquisition fda --since 2022-01-01 --until 2024-12-31
```

Discovery is **not** a manually maintained ADC drug-name list — Prompt.md
section 14 explicitly prohibits that. Instead, `configs/fda_queries.yaml`
defines full-text search queries against openFDA's own structured product
label text (`GET /drug/label.json`, searching the `mechanism_of_action`
and `description` sections for "antibody-drug conjugate"), verified live
to catch all 15 major FDA-approved ADCs — FDA's own structured
pharmacologic-class tags (`openfda.pharm_class_epc`/`pharm_class_cs`) are
**not** reliably populated for ADCs (only 2 of 15 known ADCs carry one).
Each discovered `application_number` is then reconciled against the
authoritative `/drug/drugsfda.json` endpoint for its full submission
history — same two-step discover-then-reconcile shape as Crossref's DOI
reconciliation.

Three independent levels, each with its own content-version manifest and
checkpoint namespace, mirroring SEC EDGAR's company -> filing -> exhibit
model one level deeper (Drugs@FDA's own data model genuinely has three
parts — application identity, submissions, application_docs — not two):

- `DATA/manifests/fda_applications{,_discovery,_attempts}.parquet` —
  application/product identity, keyed by `application_number`. Content
  is the **complete raw Drugs@FDA record** as returned (sponsor, every
  product's brand name and active ingredients, the full submissions
  list) — Prompt.md section 14's product-name/active-ingredient key
  identifiers live here, not on the submission row. Unlike SEC's CIK,
  `application_number` is itself a discovery outcome (from the label
  search), not a manually curated identifier — so a label match that
  fails to reconcile against Drugs@FDA still gets a durable
  `fda_applications_discovery.parquet` row; the reconciliation outcome
  (`success`/`not_found`/`failed`) is recorded separately in
  `fda_applications_attempts.parquet` and never erases the discovery fact.
- `DATA/manifests/fda_submissions{,_discovery,_attempts}.parquet` — one
  regulatory milestone (e.g. `ORIG-1`, `SUPPL-81`) ~ a SEC filing, keyed
  by `submission_key`, `parent_record_id` = `application_number`. A
  submission's own row can never itself fail to materialize (its
  "content" is metadata already in hand once the parent application's
  Drugs@FDA record was fetched).
- `DATA/manifests/fda_documents{,_attempts}.parquet` — the actual
  downloadable documents (label, approval letter, review document,
  medication guide, ...) ~ a SEC exhibit, as a separate, independently
  versioned artifact keyed by `{submission_key}:{doc_id}`,
  `parent_record_id` = `submission_key` — same pattern as SEC's exhibits
  / Europe PMC's full text. Only document-level fetches (and
  whole-application-record fetches, tracked separately above) can fail.

`--since`/`--until` filter by each submission's own
`submission_status_date`, applied client-side (openFDA's date-range
search only determines whether an *application* matches at all, not
which of its submissions to return — verified live). `--resume`'s
failure-safe design (unconditionally-advancing cursor, unresolved
documents unioned back into scope regardless of date, fresh/in-range
submissions always prioritized over that backlog within a `--limit`
budget) was built in from the start, applying the design SEC EDGAR's
Job 05 needed 3 review rounds to arrive at, rather than waiting to be
caught on it again.

`FDA_API_KEY` is optional (unlike SEC's mandatory contact requirement) —
raises the daily quota from 1,000 to 120,000 requests, never required to
run. Some older `application_docs` URLs redirect to fda.gov's modern
site and 404 there (real historical link rot, not a bug) — and fda.gov's
web front end runs bot detection that silently blocks Python `requests`'
default User-Agent (redirecting to an apology page instead of the real
target), which is why `jobs/fda/client.py` sends a descriptive one on
every request.

## Running the EMA job (Job 07)

```bash
python -m adc_acquisition ema --dry-run --limit 20
python -m adc_acquisition ema --limit 20
```

EMA has no public REST API for this, but explicitly publishes bulk JSON
exports intended for automated systems — one covering every
EMA-authorised medicine, one covering every EPAR document across every
medicine (20,099 records live) with its own stable numeric id/type/dates
independent of any single medicine's page. Discovery filters the
medicines feed by systematic INN-suffix matching
(`configs/ema_adc_substance_patterns.yaml`: vedotin, emtansine,
deruxtecan, ozogamicin, govitecan, soravtansine, mafodotin, tesirine —
standardized WHO stems for ADC linker/payload chemistry, not a manual
drug list, same spirit as Job 06's label search).

Three levels: `ema_bulk.parquet` (the raw bulk feeds themselves,
preserved exactly as downloaded, content-versioned, so a future EMA
schema/data change never leaves us without the exact input that produced
a given run's discovery decisions), `ema.parquet` (medicine identity,
keyed by EMA product number, storing the medicine's own record verbatim
from the medicines feed), and `ema_documents.parquet` (EPAR documents —
product information, assessment reports, ... — as an independent
artifact keyed by `{product_number}:{doc_id}`, EMA's own stable numeric
id, `parent_record_id` back to the medicine). **Documents are discovered
from the bulk documents feed for every ADC-candidate medicine on every
run, entirely independent of which medicines `--limit`/`--since`/
`--until`/`--resume` selected for materialization** — a medicine outside
this run's own scope can still have a new or updated document discovered
and downloaded, since document discovery was never gated by the
medicine's scope to begin with (an earlier version of this job scraped
each medicine's rendered EPAR HTML page instead, which coupled document
discovery to per-medicine page availability and to the medicine's own
`--resume` window — fixed after review).

`--since`/`--until` filter medicines by `last_updated_date`; `--resume`
for medicines uses the same failure-safe design established by Jobs
05/06 (unconditionally-advancing cursor, unresolved backlog unioned back
regardless of date, fresh/in-range medicines always prioritized within a
`--limit` budget). ema.europa.eu has no documented rate limit but
enforces some kind of cumulative session throttle regardless of
per-request pacing (verified live: even after eliminating per-medicine
page scraping, the remaining ~150 individual document PDF fetches alone
still triggered HTTP 429s) — these are genuinely retryable and self-heal
on the next run via each document's own checkpoint.

## Running the WIPO job (Job 08)

```bash
python -m adc_acquisition wipo --dry-run --limit 20
python -m adc_acquisition wipo --limit 20
python -m adc_acquisition wipo --refresh   # periodically (e.g. monthly): re-verify already-successful publications for OPS-side corrections
```

**Requires `OPS_CONSUMER_KEY`/`OPS_CONSUMER_SECRET`** (`.env`) — free
registration at https://developers.epo.org/.

WIPO PATENTSCOPE itself has no public API, and its Terms of Use Section
2.1 explicitly prohibit automated queries, bulk downloading, and scraping
(verified live: "more than 10 search-related actions per minute from a
single IP can be considered excessive") — a legal constraint, not a
technical one. WO-prefixed (PCT) publication data is instead acquired via
EPO's Open Patent Services (OPS), a free OAuth2-authenticated REST API
whose INPADOC/DOCDB data covers WO publications' full bibliographic data.
Job 10 (EPO) will separately query the same OPS API for EP-prefixed
publications — the two stay architecturally independent jobs with their
own query_id/provenance namespaces.

Discovery uses 5 CQL queries (`configs/wipo_queries.yaml`) matching
Prompt.md's listed search concepts (singular/plural "antibody-drug
conjugate(s)" phrase, "immunoconjugate", "antibody AND linker AND
cytotoxin", "antibody AND payload AND conjugate"), each verified live to
stay under OPS's 2000-total-result access cap. `wipo.parquet` is the
publication content-version manifest (raw biblio XML preserved verbatim,
keyed by publication_number e.g. `WO2026163182A1`); `wipo_discovery.parquet`
records every (publication, query, run) triple; `wipo_attempts.parquet`
records every fetch attempt.

**Deviation from Jobs 05/06/07's `--resume` design:** once a specific
publication_number is successfully materialized, its OPS record is
skipped with **no OPS request at all** on subsequent default runs, rather
than being refetched-then-hash-compared every run like SEC/FDA/EMA —
refetching ~2500 discovered publications on every incremental run would
be wasted OPS quota in the common case. This is an efficiency default,
**not** an immutability assumption: OPS's own terms note corrections do
get incorporated into DOCDB data over time, so use `--refresh` to opt an
entire run into re-fetching and hash-comparing every discovered
publication (including already-successful ones), creating a new version
if content genuinely changed — run it periodically (e.g. monthly), not on
every incremental run. `--since`/`--until` apply as a genuine server-side
CQL filter (`pd within "YYYYMMDD,YYYYMMDD"`, verified live); `--resume`
does not date-restrict the search itself (that would make an unresolved
backlog item whose publication predates the cursor undiscoverable), so it
and the plain default both run a full undated sweep, relying entirely on
the attempts ledger's most-recent-status for retry safety. See
`jobs/wipo/job.py`'s module docstring for the full rationale.

OPS meters `search` and `retrieval` (biblio fetch) as separate quota
buckets (verified live via the `X-Throttling-Control` response header) —
`search` has a much tighter short-window budget (observed exhausted after
~15-20 calls, recovering within ~1-2 minutes) than `retrieval`. The two
endpoints use separate, independently-paced rate limiters as a result
(`jobs/wipo/client.py`).

## Running the USPTO job (Job 09)

```bash
python -m adc_acquisition uspto --dry-run --limit 20
python -m adc_acquisition uspto --limit 20
```

**Requires `USPTO_API_KEY`** (`.env`) — free registration at
https://data.uspto.gov/. PatentsView (api.patentsview.org) was shut down
2026-03-20 and now redirects to USPTO's own migration guide; the old
developer.uspto.gov portal is also decommissioned. USPTO's Open Data
Portal (Patent File Wrapper API) is the current official mechanism —
unlike WIPO PATENTSCOPE there is no automation ban, just registration.

Discovery uses the same 5 free-text search concepts as Job 08 (WIPO),
translated to USPTO's query syntax — confirmed live to search across full
specification content, not just titles. `uspto.parquet` is the
application content-version manifest (a deterministic serialization of
the full source record, not the raw HTTP response bytes verbatim — the
record is extracted from a wrapping envelope and re-serialized with
`sort_keys=True` — keyed by application_number); `uspto_documents.parquet`
holds Specification (`documentCode == "SPEC"`) documents as an
independent artifact, whose raw PDF/XML bytes ARE preserved verbatim.

**Unlike Job 08 (WIPO):** every discovered application is refetched and
hash-compared every run — USPTO application content is mutable
(prosecution status/assignments/continuity data genuinely change over
time), so there's no skip-by-default/`--refresh` design here; USPTO's
generous weekly quota (5,000,000 metadata / 1,200,000 document
retrievals) removes the efficiency pressure that motivated WIPO's design
in the first place.

**A different live finding, though:** USPTO's document `/download`
endpoints dynamically RE-RENDER the PDF/XML on every single request —
confirmed live that two immediately-successive fetches of the exact same
`documentIdentifier` return different bytes (the PDF embeds a fresh
`/CreationDate`). Hash-compare-then-version — the pattern every other
document artifact in this repo uses — would treat every re-fetch as
"changed" and create an unbounded stream of spurious versions forever.
Documents are instead skipped once their `documentIdentifier` already has
a `document_records` checkpoint entry (identity-based, not hash-based) —
the skip test reads the checkpoint directly (durable to disk immediately
after every raw write), not the attempts ledger, so a lost ledger flush
(e.g. an uncaught exception after the checkpoint save but before the
end-of-run batch write) self-heals on the next run by reconstructing the
manifest/attempts rows from the checkpoint's own stored hash/version,
rather than re-downloading and overwriting the raw file with different
bytes.

Application-level materialization keeps raw-fetch state (`raw_records`
checkpoint namespace) and "already fully normalized" as two separate
facts: unchanged bytes are only classified `skipped_unchanged` when the
attempts ledger's own most-recent status for that application is already
resolved (`success` or `skipped_unchanged`); unchanged bytes whose last
attempt was `parse_failed` (or missing entirely, e.g. after an uncaught
crash) reuse the existing raw file and retry normalization instead of
being silently skipped forever. `--limit` fairness is three categories,
not two: never-attempted (fresh) first, then unresolved retries
(backlog), then already-resolved applications due for periodic
re-verification (reverify) — strictly last, so a small `--limit` can never
get stuck re-verifying the same already-successful applications while
starving out genuinely new ones.

`--since`/`--until` apply as a genuine server-side bracket-range filter
(`applicationMetaData.filingDate:[YYYY-MM-DD TO YYYY-MM-DD]`, verified
live) whenever supplied explicitly; `--resume` does not date-restrict the
search itself, same reasoning as Job 08.

## Running the EPO job (Job 10)

```bash
python -m adc_acquisition epo --dry-run --limit 20
python -m adc_acquisition epo --limit 20
```

Uses the same EPO Open Patent Services (OPS) API Job 08 (WIPO) uses,
filtered to EP-prefixed publications (`pn=EP`) instead of WO-prefixed
(PCT) ones — an architecturally independent job (own query registry,
own query_id/provenance namespace, own `epo.parquet`/`epo_discovery.parquet`/
`epo_attempts.parquet` triple) sharing only the already-tested OPS client
and response parser, now factored out to `adc_acquisition/ops_client.py`
and `adc_acquisition/ops_parser.py` (Job 08's own `client.py`/`parser.py`
are thin re-export shims onto these shared modules, kept for import-path
backward compatibility with its own already-merged tests).

**Design mirrors Job 08 exactly** (confirmed live that OPS's EP-prefixed
biblio response is the byte-identical schema WO-prefixed responses use):
default-skip-with-`--refresh`-opt-in, the skip decision requires BOTH
unchanged raw bytes AND the attempts ledger's own most-recent status
already resolved, raw XML persisted and checkpoint-saved to disk
immediately before parsing, `--limit` prioritizes fresh over backlog over
reverify.

**One genuine EPO-specific live finding, though:** OPS's `ti=` (title)
field, searched with a quoted multi-word phrase and restricted to
`pn=EP`, reproducibly returns HTTP 500 at any Range span greater than 1 —
confirmed via direct A/B testing this is specific to "title field + quoted
phrase + EP scope" (not clause ordering, not OR-combination, not general
OPS load, and NOT present for Job 08's identical `pn=WO` pattern already
running in production). See `configs/epo_queries.yaml`'s header comment
for the full investigation. Consequence: the two "antibody-drug
conjugate(s)" phrase queries search the abstract only for EP scope (not
title+abstract like WIPO) — a disclosed coverage gap, not a silently
narrowed one (see `reports/acquisition/COVERAGE.md`).

## Tests

```bash
pytest
```

All tests mock HTTP (via `responses`) — no live network access is required
or used by the normal test suite.

## Status

See `reports/acquisition/COVERAGE.md`. Only Job 01 (PubMed), Job 02
(Europe PMC), Job 03 (ClinicalTrials.gov), Job 04 (Crossref), Job 05
(SEC EDGAR), Job 06 (FDA), Job 07 (EMA), Job 08 (WIPO), Job 09 (USPTO),
and Job 10 (EPO) are implemented so far; every other source in
`Prompt.md` is intentionally not started yet — sources are implemented
and reviewed one at a time.
