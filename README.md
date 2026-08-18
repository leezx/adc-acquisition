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

## Running the company pipeline job (Job 11)

```bash
python -m adc_acquisition company_pipeline --dry-run
python -m adc_acquisition company_pipeline
python -m adc_acquisition company_pipeline --company zymeworks
```

"Fundamentally different from database APIs" (Prompt.md's own framing):
no live search/discovery step exists — every (company, pipeline_url) pair
comes directly from the curated `configs/company_registry.yaml`, shared
with Job 05 (SEC), now extended with `official_domain`/`pipeline_urls`/
`investor_relations_url`/`press_release_url` fields
(`adc_acquisition/company_registry.py`). No discovery ledger is needed —
a pipeline_url is curated, not a discovery outcome, same reason SEC's own
CIK level never needed one. Just two tables:
`company_pipeline.parquet` (page snapshot manifest) and
`company_pipeline_attempts.parquet`.

Every registered pair is refetched and hash-compared **every run** (the
ordinary SEC/FDA/EMA/USPTO pattern, not WIPO/EPO's skip-by-default) —
Prompt.md is explicit that pipeline pages change over time and snapshots
are essential, and the curated set is small enough that there's no
efficiency pressure to skip. Individual pipeline program entries (drug
names, phases) are deliberately NOT extracted — only the raw page
snapshot and its `<title>` tag are preserved; parsing out programs is
downstream knowledge extraction.

**Two live findings from verifying all 8 registered companies (2026-08-14):**
1. Seagen, ImmunoGen, and Mersana (all acquired/absorbed) have no
   standalone pipeline page anymore — `pipeline_urls: []` for those three;
   their former ADC assets appear only in their acquirers' own pipeline
   pages (confirmed live: Pfizer's oncology pipeline page lists
   PADCEV/TIVDAK/disitamab vedotin, all former Seagen assets).
2. AbbVie's pipeline page is behind an active Cloudflare JS challenge
   (HTTP 403, "Just a moment..." interstitial) — confirmed a descriptive
   User-Agent (the fix that resolved fda.gov's simpler bot detection)
   does NOT get past it. Not bypassed (Prompt.md prohibits CAPTCHA/bot-
   challenge circumvention) — recorded as a normal, logged failed attempt.
   Zymeworks, Sutro Biopharma, ADC Therapeutics, and Pfizer's pipeline
   pages are all plain static HTML, live-verified accessible and
   materialized with real content.

## Running the company press-release job (Job 12)

```bash
python -m adc_acquisition company_press_release --dry-run
python -m adc_acquisition company_press_release
python -m adc_acquisition company_press_release --company sutro_biopharma
python -m adc_acquisition company_press_release --refresh   # periodic re-verification, not for every run
```

"Separate this from company pipeline pages" (Prompt.md's own instruction)
— Job 11 archives a company's current-state pipeline snapshot; this job
acquires discrete, dated ANNOUNCEMENTS. Unlike Job 11, this genuinely
needs a discovery ledger: each company's `press_release_url`
(`configs/company_registry.yaml`, shared with Job 05/Job 11) is a curated
LISTING page, but the individual releases behind it are a discovery
outcome that grows over time. No unified API exists across companies —
live-verified 2026-08-17 that the registered companies' listing pages
reduce to 3 reused third-party IR-platform templates, selected per
company via the registry's new `press_release_template` field
(`jobs/company_press_release/parser.py`).

Discovery walks each company's listing pagination, stopping once a page
contributes zero not-yet-*resolved* items — checked against every release
whose most recent attempt is genuinely resolved (not just "ever
discovered"; a failed or never-materialized release must re-enter scope
on the very next ordinary run, not just under `--refresh`). Two of the
three templates clamp/wrap to repeat an already-seen page past the real
end instead of emptying out (live-verified) — this stop rule handles both
behaviors uniformly. Materialization mirrors Job 10 (EPO)'s fully-hardened
skip-by-default + `--refresh` + stale-ledger-recovery design, applied
proactively from the start. "Only official company domains... do not mix
media reports" is enforced at discovery time via an `official_domain`
membership check on every listing item.

**Live finding (2026-08-17):** Zymeworks' entire `ir.zymeworks.com`
subdomain is currently unreachable (a direct request with a descriptive
User-Agent hangs to a read timeout — distinct from AbbVie's fast
Cloudflare 403 in Job 11) — recorded as a normal, logged failed attempt,
not bypassed or silently dropped.

## Running the patent bioactivity corpus job (Job 13)

```bash
python -m adc_acquisition patent_bioactivity_corpus --dry-run
python -m adc_acquisition patent_bioactivity_corpus
python -m adc_acquisition patent_bioactivity_corpus --refresh   # periodic re-verification, not for every run
```

A SECOND-PASS job — Prompt.md is explicit it "should NOT search the
entire patent universe again." Candidates are read directly from Job 08
(WIPO)'s `wipo.parquet` AND Job 10 (EPO)'s `epo.parquet` manifests
(latest version per `publication_number` only), not from a new OPS
search. For each candidate publication, two independent artifacts are
fetched via EPO OPS's full-text endpoints: `description` (specification
body text — where Prompt.md's target sections
Examples/Experimental/IC50/etc. actually live) and `claims`, each its
own independent content-version manifest entry (own checkpoint/version,
`parent_record_id` pointing back to the upstream manifest's
`publication_number`, `upstream_source` recording which of WIPO/EPO it
came from).

**Round-1 fix (2026-08-18):** the initial version of this job read ONLY
`epo.parquet`, reasoning from a single live-tested WO publication (whose
description/claims 404'd while its biblio succeeded) that OPS full-text
coverage was a hard EP-only limitation and excluding WIPO entirely. This
was an overreach from n=1 — EPO's own OPS Reference Guide documents
full-text availability across multiple authorities including WO, not
just EP. WIPO candidates are now attempted exactly like EPO candidates;
a 404 is recorded per (publication, artifact) as `not_available` — the
already-correct mechanism for "OPS confirms this one thing isn't there"
— rather than excluding an entire upstream source in code. Real
per-authority coverage (WIPO vs. EPO) is reported separately in the
written report, as an empirical result of this job's own attempts — a
live run against this repo's own real WIPO/EPO manifests found WIPO
publications actually have SUBSTANTIAL full-text coverage (38/40
artifacts, 95%), comparable to EPO's own (72/90, 80%), directly
disproving the original "EP-only" assumption.
**Job 09 (USPTO) is still not duplicated here**: its already-acquired
SPEC-type documents (`uspto_documents.parquet`) are the as-filed
Specification PDF, already bundling description + claims + abstract for
the original filing.

Materialization mirrors Job 10 (EPO)'s fully-hardened design (own raw
checkpoint namespace, resolved-status-AND-version-match skip decision,
`--refresh`), applied proactively. A 404 (`not_available`, OPS confirms
no full text exists for this specific artifact) is retried on every
ordinary run — staying conservative about assuming any 404 is
permanent, per the lesson from Job 05 (SEC)'s round-3 review. EPO's OPS
free tier has a 4GB/WEEK data quota across all OPS usage — full-text
documents are far larger than biblio XML, so `result.notes` reports
per-run downloaded bytes for monitoring.

## Running the publication bioactivity corpus job (Job 14)

```bash
python -m adc_acquisition publication_bioactivity_corpus --dry-run
python -m adc_acquisition publication_bioactivity_corpus
python -m adc_acquisition publication_bioactivity_corpus --refresh   # periodic re-verification, not for every run
```

A SECOND-PASS job — Prompt.md's input for this job is "PMIDs / PMCIDs /
DOIs / known ADC aliases," not a new literature search. Candidates are
read directly from Job 01 (PubMed)'s `pubmed.parquet`, Job 02 (Europe
PMC)'s `europe_pmc.parquet`, and Job 04 (Crossref)'s `crossref.parquet`
(latest version per record only), not from a new discovery query.
"known ADC aliases"-driven discovery is deferred to Job 15 — this job
only reconciles exact identifiers those three jobs already discovered.

**Mechanism, researched before writing any code** (explicitly to avoid
repeating Job 13's "generalize from a single test point" mistake): Job 02
(Europe PMC) only fetches full-text JATS XML for records ITS OWN search
queries discovered AND that are flagged `is_open_access` — verified live
that this repo's real `europe_pmc_fulltext.parquet` currently has zero
rows, so nothing has actually been acquired that way yet in this repo's
own data. [Unpaywall](https://unpaywall.org/products/api) (free, no API
key, just a real-looking contact email — verified live that a
placeholder like `test@example.com` is rejected with HTTP 422) closes a
genuinely separate gap: its coverage is empirically NOT a subset of
Europe PMC's OA subset — it also covers DOIs Job 02 never discovered at
all, and DOIs where Europe PMC's own `is_open_access` flag is
false/absent but a legal OA copy exists elsewhere (hybrid OA,
institutional repository, etc.).

**Exact-identifier coverage, not DOI-only (round-1 fix):** the initial
version of this job only ever looked at each upstream record's `doi`
field, silently dropping every PubMed/Europe PMC record that has a PMID
and/or PMCID but no DOI — verified live this is NOT a theoretical edge
case (8/20 PubMed records and 6/20 Europe PMC records in the real
committed demo set have no doi at all), and Prompt.md's own input list is
explicitly PMIDs/PMCIDs/DOIs, not "DOIs only." Fixed by routing each
candidate record through the most specific identifier it has
(doi > pmcid > pmid priority), still purely reconciling identifiers
Jobs 01/02 already discovered, never a new search:
- a record with a **doi** — unchanged: Unpaywall OA lookup + content fetch.
- a record with a **pmcid** (no doi) — fetched directly from Europe PMC's
  own `fullTextXML` endpoint (the exact mechanism Job 02 itself uses) —
  Job 02 might not have fetched it (its `is_open_access` flag may have
  been false at discovery time, or it came from a different query), so
  this is a genuinely separate acquisition attempt, not a guaranteed
  duplicate.
- a record with **only a pmid** (no doi, no pmcid) — resolved via NCBI's
  own [PMC ID Converter](https://www.ncbi.nlm.nih.gov/pmc/tools/id-converter-api/)
  (exact PMID→PMCID/DOI lookup, batched once per run), before falling
  back to `not_available` if NCBI has no mapping for it.

For a doi-identified record: (1) an Unpaywall lookup for OA status and an
ordered list of OA locations; (2) a content fetch trying every URL a
location offers — `url_for_pdf`, then `url_for_landing_page`, then
`url`, deduplicated — before moving to the NEXT location, not just the
single "best" one (round-1 fix: the initial version only tried
`url_for_pdf or url` per location, so a location whose PDF link 403s a
bot but whose landing page still serves full text as HTML was wrongly
treated as dead and skipped entirely). A DOI Unpaywall doesn't know, or
confirms has no OA copy, is `not_available`; a content fetch failing
across every offered location/URL is `failed` (Unpaywall confirmed a
copy exists, the fetch itself just didn't succeed this run).

**Truthful `not_available` provenance (round-1 fix):** the initial
version recorded every `not_available` outcome with a hardcoded
`http_status=404`, conflating Unpaywall's DOI endpoint genuinely
returning HTTP 404 (this DOI is unknown to it) with a 200 response that
simply confirms no OA copy exists. Fixed: only a genuine lookup-level 404
is recorded as `http_status=404`; a 200 response with no usable OA copy
is recorded as `http_status=200` with a distinct `error` value
(`no_oa_copy` / `no_usable_oa_location`), and a pmid the ID Converter
simply has no mapping for gets no fabricated status at all.

**Job 02 (Europe PMC)'s own already-resolved full text is not
duplicated here** — a record whose pmcid already has a successfully
materialized Europe PMC full-text artifact (checked directly by pmcid,
not via a doi round-trip) is excluded from this job's candidate set
every run, the same don't-duplicate-an-existing-job's-work precedent as
Job 13's USPTO exclusion.

**Self-caught before this job was ever run for real:** DOIs are
case-insensitive by specification, but this repo's own committed data
has the identical work recorded as `10.1007/BF01741596` in PubMed's
manifest and `10.1007/bf01741596` in Crossref's (Crossref itself
lowercases the doi field it returns) — every DOI is normalized (stripped
+ lowercased) before becoming a candidate identity, or this job would
silently fetch/store the same OA article twice under two manifest rows.
Separately, live-verifying the PMC ID Converter integration surfaced a
second real bug before it ever reached a PR: NCBI's JSON response
encodes `pmid` as an int, not the string this job requests with, which
would have made every SUCCESSFUL resolution look unresolved — fixed to
key results by the response's own `requested-id` field instead.

Materialization mirrors Job 13's fully-hardened design (own raw
checkpoint namespace, resolved-status-AND-version-match skip decision,
`--refresh` re-verifying the full acquisition path), applied
proactively. Live-verified end-to-end against this repo's own real
committed `pubmed.parquet`/`europe_pmc.parquet`/`crossref.parquet` (58
upstream mentions, 38 unique candidate records: 24 doi-addressable, 0
pmcid-addressable, 14 pmid-only — all 14 confirmed unresolvable by
NCBI's own ID Converter for these older, pre-DOI-era papers): 3 success,
34 `not_available`, 1 `failed` (a Wiley landing page 403), stable
skip-by-default confirmed on rerun.

**Requires `UNPAYWALL_CONTACT_EMAIL`** (`.env`) — free, no registration
at https://unpaywall.org/products/api, but Unpaywall rejects
placeholder-looking addresses with HTTP 422.

## Running the known-ADC asset expansion job (Job 15)

```bash
python -m adc_acquisition known_adc_asset_expansion --dry-run
python -m adc_acquisition known_adc_asset_expansion
python -m adc_acquisition known_adc_asset_expansion --sources pubmed,clinicaltrials  # subset of {pubmed,europe_pmc,wipo,epo,clinicaltrials}
```

The final job (Prompt.md section 19) — Jobs 01-14 together are the broad
DISCOVERY PASS; this is the separate ASSET-CENTRIC EXPANSION PASS
Prompt.md describes ("do not conflate the two passes"). Given a curated
registry of known ADC assets (`configs/known_adc_assets.yaml` — name,
aliases, dev codes, target, company — an INPUT to this job, not something
it discovers itself), it generates Prompt.md's search templates
("&lt;name&gt;", "&lt;alias&gt;", "&lt;name&gt; patent/trial/activity/
cytotoxicity/xenograft/IC50") translated into each source's own real
query syntax, and executes them by calling Job 01 (PubMed), Job 02
(Europe PMC), Job 03 (ClinicalTrials.gov), Job 08 (WIPO), and Job 10
(EPO) **in-process**.

**Architecturally unique in this repo: no content-version manifest of
its own.** Every discovered/materialized record lands in those 5 jobs'
own manifests, tagged with its own asset-expansion `query_id` for
provenance — building a separate acquisition pipeline here would
duplicate the checkpointing/versioning/rate-limiting those jobs already
have fully hardened, the same "don't re-acquire what an existing job
already does" discipline Job 13 (USPTO) and Job 14 (Europe PMC) already
established. The 6 suffix templates (patent/trial/activity/cytotoxicity/
xenograft/IC50) are generated only for PubMed/Europe PMC — disclosed, not
silently narrowed: WIPO/EPO's searchable fields (OPS biblio's
title/abstract) essentially never contain experimental-data language
like "xenograft"/"IC50" (that lives in the full specification text Job
13 already acquires separately), so WIPO/EPO instead get every bare
identifier (name + every alias + every dev code). ClinicalTrials.gov is
driven entirely through its existing `--intervention` lookup (built
during Job 03 specifically anticipating this job). Crossref (Job 04) is
deliberately not a target — its own free-text search is unusable for
precise discovery, already established live.

**Self-caught before this job was ever run for real:** Jobs 01/02/03/08/
10 each end their own run by unconditionally writing their `--resume`
cursor (`last_success_max_date`). Since this job calls those SAME job
classes (sharing their checkpoint files), naively invoking them would
silently advance the broad-discovery pass's own resume cursor forward to
whatever date an asset-expansion run happened to execute on — corrupting
a subsequent `--resume` run of the underlying job. Fixed: this job's own
`--resume` is a no-op (always considers the full active registry), it
never passes `resume=True` to a sub-job, and it explicitly snapshots and
restores each sub-job's resume-cursor field after every call (per-record
content-hash/version checkpoint state is left fully shared — a record
found by both passes should still only be fetched/versioned once).

**Also self-caught live** (a real run, not a mock, was the only thing
that could have caught this): EPO OPS's search endpoint returns **HTTP
404** for a query with genuinely zero hits, not an empty HTTP 200 — a
case Job 08/10's own broad topic queries never hit (they always have
hundreds+ of real matches), but common for this job's specific brand-name
searches. Fixed in the shared `adc_acquisition/ops_client.py` (benefits
Jobs 08/10 too, not just this job).

Live-verified end-to-end against this repo's own real committed
manifests using a 2-asset verification subset (trastuzumab deruxtecan,
brentuximab vedotin — the real committed registry has 15 assets; a full
production run generates substantially more queries and was
intentionally not run in full this round to bound OPS/API quota usage):
59 queries across all 5 sources, 3351 records discovered, 23 newly
downloaded, 8 correctly recognized as already-materialized by Jobs
01-14's own broad-discovery pass (`skipped_unchanged`, not re-fetched —
confirming a record shared between both passes is fetched/versioned
exactly once), 0 failed. Each sub-job's own resume cursor was confirmed
unchanged after the run.

## Tests

```bash
pytest
```

All tests mock HTTP (via `responses`) — no live network access is required
or used by the normal test suite.

## Status

See `reports/acquisition/COVERAGE.md`. All 15 jobs from Prompt.md are now
implemented: Job 01 (PubMed), Job 02 (Europe PMC), Job 03
(ClinicalTrials.gov), Job 04 (Crossref), Job 05 (SEC EDGAR), Job 06
(FDA), Job 07 (EMA), Job 08 (WIPO), Job 09 (USPTO), Job 10 (EPO), Job 11
(company pipeline pages), Job 12 (company press releases), Job 13
(patent bioactivity corpus), Job 14 (publication bioactivity corpus),
and Job 15 (known-ADC asset expansion) — each implemented and reviewed
one at a time.
