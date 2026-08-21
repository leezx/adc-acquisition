# Phase 4 — Conference Ingestion

Per `reports/validation/BREADTH_PLAN.md` Phase 4 (Part 6). AACR ahead of
ASCO/ESMO per the prompt's own priority ordering, since preclinical/
early-seed ADCs most often first appear in AACR abstracts.

## 1. Reuse search before any new download (Part 6, explicit instruction)

Before writing any acquisition code, this phase searched the project and
local data for a reusable historical AACR/ASCO corpus. It found:

- A real, already-built local corpus at
  `/Volumes/Stelligen_SSD/Stelligen/Zhixins-KB/2.Biotech/5.ADC_Expert/
  {AACR,ASCO}_Abstracts/`, spanning 2016-2026, built by a separate,
  external workflow (`REPOS/aacr-abstract-workflow`, outside both this repo
  and the Claude Code project directory) that queried Crossref for each
  meeting's own DOI prefix and applied an ADC-keyword regex filter.
- A separate, independent tool (`tools/adc_intelligence_delta`, also
  outside this repo) that had already built a 2,456-record
  `full_corpus.jsonl` from that same local corpus, with its own unrelated
  `EvidenceRecord`/`ADCSeed`/`ADCEvent` architecture.

**Decision (explicit user direction, not assumed):** reuse the raw
Zhixins-KB JSON files directly, as an already-fetched historical snapshot,
through a new adc-acquisition-native job following this repo's own
three-table architecture. `tools/adc_intelligence_delta` is a separate
project and is not depended on, imported from, or modified by this phase.

## 2. What was verified before writing the job (not assumed)

- Read the external workflow's own extraction scripts to get the ACTUAL
  filter methodology per source, not a guess or a summary. **Round-1
  fix**: the first version of this report/registry both truncated the
  ASCO regex with "..." and mischaracterized AACR's exclusion step as a
  "manual exclusion pass" (copying `extraction_report.json`'s own
  `curation_note` wording) when it is actually a second, fully
  deterministic regex. Both filters' complete, verbatim logic is now
  recorded in `configs/conference_abstract_corpus_queries.yaml`:
  - **AACR**: title-only, two-regex deterministic filter (no manual
    step) -- included iff `TITLE_INCLUDE_RE` matches the title AND
    `TITLE_EXCLUDE_RE` does not, byte-identical between
    `extract_aacr_annual_adc.py` (2016-2025) and `extract_aacr2026_adc.py`
    (2026).
  - **ASCO**: a two-stage pipeline -- Stage 1 is a Crossref
    `query.title`-based candidate fetch (title-only, restricted by
    default to 4 core terms; a broader `EXPANDED_QUERY_TERMS` list is
    only used if the external workflow's `ASCO_ADC_EXPANDED=1` env var
    was set at build time, which is **not verifiable now** -- disclosed
    as an unresolved provenance gap, not assumed either way); Stage 2 is
    a deterministic `ADC_RE` match against title+abstract, applied to
    every Stage-1 candidate.
- Read the real per-year JSON files directly (not assumed uniform):
  AACR 2016-2025 carry full Crossref metadata (doi, `published_online`/
  `published_print` date-parts, `container_title`, ...); AACR's 2026 file
  was built by PDF-extracting the AACR 2026 proceedings text ahead of
  Crossref indexing, and has **no doi field at all** for 307 of its 344
  records. ASCO's schema is uniform across all years (every record has a
  doi, since the JCO supplement DOI prefix is what queried Crossref in the
  first place).
- Confirmed record_id (AACR's `abstract_number`, ASCO's `absId`) is unique
  within each (conference, year) pair against the real data -- no
  duplicates found.
- Total record count: 1,286 AACR + 1,170 ASCO = 2,456, matching
  `tools/adc_intelligence_delta`'s own `full_corpus.jsonl` count exactly (an
  independent cross-check that both readings of the same underlying local
  corpus agree).

## 3. Job design (`jobs/conference_abstract_corpus/`)

Three tables, same shape as every other job in this repo:
`conference_abstract_corpus.parquet` (content-version manifest),
`conference_abstract_corpus_discovery.parquet` (append-only (record, query)
ledger -- genuinely needed here, unlike Crossref/Job 14's "no discovery
ledger" jobs, because this source is not read from another adc-acquisition
job's own manifest), `conference_abstract_corpus_attempts.parquet`
(append-only attempts ledger).

**Query registry** (`configs/conference_abstract_corpus_queries.yaml`):
two broad-discovery queries, `CONFERENCE_AACR_001`/`CONFERENCE_ASCO_001`,
documenting the external filter's verified text so a future Phase 7
re-benchmark can recognize this source under Phase 1's locked broad-recall
provenance rule (only query_ids present in `configs/*_queries.yaml` count).

**Canonical identity**: doi (normalized lowercase/stripped, same convention
as `jobs/publication_bioactivity_corpus/job.py`) when present, else
`f"{conference.lower()}:{year}:{record_id}"`.

**Year discovery is a glob**, not a hardcoded year range, so a future
re-run of the external workflow that adds a new year's folder is picked up
automatically -- verified with a regression test
(`test_new_year_folder_picked_up_without_code_change`).

## 4. A real bug this phase's own tests caught (not found by inspection)

The first version of this job reused Job 13/14's attempts-ledger-trust
fast-skip pattern (a resolved prior attempt is assumed still correct
without rechecking). `test_content_change_bumps_version` failed against
that version: it silently missed a corpus file the external workflow had
corrected between runs, because the fast-skip path never recomputed the
content hash for anything already marked successful.

That pattern makes sense for Job 13/14 because rechecking there requires a
real, possibly-expensive network call. It does not make sense here: this
job already reads every record's current content into memory on every run
(a local file glob + `json.loads`, no network involved) as part of
building the discovery ledger, so recomputing and comparing the content
hash costs nothing extra. Fixed by always recomputing content_hash for
every record on every run and comparing directly against the checkpoint,
never trusting the attempts ledger's last status -- removing an entire
class of ledger/checkpoint desync logic (`_classify_ids`/
`pending_recovery`) that existed only to work around an expensive-recheck
cost this job doesn't have.

## 4b. Round-1 fix: `--since`/`--until` must never exclude undated records

The first version filtered `all_records` by `publication_or_release_date`
directly (`>= since` / `<= until`), which silently dropped every undated
record -- exactly AACR 2026's 307 no-doi, no-date, PDF-extracted records --
before it ever reached the content-hash comparison step. This directly
conflicts with Phase 6's intended `--since <last_successful_update>`
twice-monthly update pattern: an undated record that is new, or that the
external workflow corrects, would never be re-compared or re-materialized
on any incremental run, permanently defeating exactly the early-seed
conference update this phase exists for.

Fixed to the minimum correct rule: a date filter can only exclude a record
it can actually date. `--since`/`--until` now keep every record with no
`publication_or_release_date` in scope for hash comparison, filtering only
records that actually have a date outside the requested window. Re-reading
an unchanged undated record every run costs nothing beyond a cheap
in-memory hash comparison (still a local file read either way), so this
does not reintroduce any real per-run cost. Regression test:
`test_since_never_excludes_undated_records_from_change_detection` --
an undated AACR record materialized at v1, corrected, then re-run with
`--since` set to a recent date, and asserted to still detect the change
and materialize v2.

## 5. Live run against the real corpus (not just synthetic test fixtures)

```
$ python -m adc_acquisition conference_abstract_corpus --dry-run
records_discovered=2456 (1286 AACR, 1170 ASCO across 11 AACR year-files and 11 ASCO year-files)

$ python -m adc_acquisition conference_abstract_corpus
records_downloaded=2456, records_skipped_unchanged=0

$ python -m adc_acquisition conference_abstract_corpus   # re-run, idempotency check
records_downloaded=0, records_skipped_unchanged=2456
```

2,149 of 2,456 candidate records have a doi (the 307 without are all in
AACR's 2026 PDF-extracted file); 2,386 have abstract text materialized (the
rest -- AACR abstracts with `abstract_text` present in 100% of cases per
the source data, and 70 ASCO abstracts with no `abstract` field in the
source at all -- have title-only evidence, disclosed in the manifest and
report rather than treated as equivalent evidence depth).

## 6. What Phase 4 does and does not establish

- Confirms Part 6's reuse-before-download instruction was followed: this
  phase added zero new AACR/ASCO/Crossref network traffic, and made a
  pre-existing 2,456-record historical corpus (spanning 2016-2026) legible
  to this repo's acquisition architecture for the first time.
- **Does not extract any target/payload/linker/candidate entities from this
  corpus's title/abstract text** (Part 16 scope discipline, same boundary
  every other job in this repo draws). Feeding this corpus into
  `tools/breadth/candidate_queue.py`'s USAN/INN suffix matching, and into a
  future BROAD_DISCOVERED classification pass analogous to
  `tools/breadth/broad_recall.py`'s, is explicit Phase 5/7 scope, not
  attempted here.
- **AACR's filter is title-only** -- a real, disclosed recall ceiling this
  job cannot lift on its own; an AACR abstract that discusses an ADC
  substantively without the matched terms in its own title is not in this
  corpus at all.
- Does not attempt ESMO or company scientific-presentation ingestion --
  explicit Phase 5 scope per `BREADTH_PLAN.md`'s own sequencing.

## Reproduction

```bash
python -m adc_acquisition conference_abstract_corpus --output DATA
```
