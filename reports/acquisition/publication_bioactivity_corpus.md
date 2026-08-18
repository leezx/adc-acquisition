# Publication Bioactivity Evidence Corpus (Job 14)

## Acquisition mechanism

SECOND-PASS job -- Prompt.md's input is "PMIDs / PMCIDs / DOIs / known ADC aliases", not a new literature search. Candidates are read directly from Job 01 (PubMed)'s `pubmed.parquet`, Job 02 (Europe PMC)'s `europe_pmc.parquet`, and Job 04 (Crossref)'s `crossref.parquet` (latest version per record only), not from a new discovery query. "known ADC aliases"-driven discovery is deferred to Job 15 -- this job only reconciles exact identifiers (doi/pmcid/pmid) those three jobs already discovered.

For each candidate record, acquisition routes by its most specific available identifier: a **doi** goes through (1) an Unpaywall (https://unpaywall.org) lookup for OA status and locations, then (2) a content fetch trying every URL a location offers (PDF, then landing page, then generic `url`) before moving to the next location -- a publisher landing page can serve full text as HTML even when its PDF link blocks a bot. A **pmcid** (no doi known) is fetched directly from Europe PMC's own `fullTextXML` endpoint -- the exact mechanism Job 02 itself uses, attempted here because Job 02 may not have fetched it for this specific record. A **pmid-only** record (no doi, no pmcid) is first resolved via NCBI's own PMC ID Converter (exact-identifier lookup, not a search) before falling back to `not_available` if NCBI has no mapping for it.

## Known scope limitations (disclosed, not silently narrowed)

**Job 02 (Europe PMC)'s own already-resolved full text is NOT duplicated here.** 0 candidate record(s) this run were excluded because Europe PMC's own `europe_pmc_fulltext.parquet` already has a successfully materialized full-text artifact for their pmcid (checked directly by pmcid, not via a doi round-trip). This mirrors Job 13's USPTO exclusion: re-downloading the identical article's OA full text under a second table would be pure duplication of Job 02's own work. Unpaywall/direct-pmcid coverage is NOT a strict subset of Europe PMC's OA subset, so every other candidate record is still attempted here.

**"known ADC aliases"-driven discovery is Job 15's job, not this one's.** This job only works through exact identifiers (doi/pmcid/pmid) already present in Jobs 01/02/04's manifests; it never searches PubMed/Europe PMC/Unpaywall by asset alias.

## Candidate identifier coverage this run (empirical, not assumed)

24 doi-addressable, 0 pmcid-addressable (no doi known), 14 unresolved identifier-only candidates (pmid only, no doi/pmcid mapping found). Of 14 upstream mentions that started as pmid-only (no doi, no pmcid at load time), 0 were resolved via NCBI's PMC ID Converter this run (0 to a doi, 0 to a pmcid) -- round-1 fix: the initial version of this job silently dropped every such record instead of resolving it.

## Candidate provenance this run

pubmed: 20, europe_pmc: 18, crossref: 20 (upstream mentions across Jobs 01/02/04; a record can appear in more than one, so these do not sum to the number of unique candidate records).

## Materialization this run

38 unique candidate records (after excluding 0 already covered by Job 02). 0 never-attempted (fresh), 35 unresolved-retry (backlog, includes `not_available` -- retried every ordinary run, NOT treated as permanently terminal), 0 pending recovery (raw durable but ledger stale), 3 already successful and skipped with no request.

**This run's outcomes:** 0 success (newly downloaded), 3 skipped_unchanged, 34 not_available, 1 failed -- 38 total attempted/fast-skipped outcomes (must equal the sum of these four).

## Sample materialized artifacts

- 10.1007/bf01741596 (identifier_type=doi, host_type=repository, oa_status=green, upstream=crossref,pubmed, version 1)
- 10.1016/s0014-5793(02)02527-9 (identifier_type=doi, host_type=repository, oa_status=bronze, upstream=crossref,europe_pmc, version 1)
- 10.1128/aac.34.5.875 (identifier_type=doi, host_type=repository, oa_status=green, upstream=pubmed, version 1)

## Failed downloads

1 this run (see DATA/logs/publication_bioactivity_corpus_failures.log and publication_bioactivity_corpus_attempts.parquet, status=failed). Separately, `not_available` (34 this run) is NOT counted as a failure -- it's a genuine negative result (Unpaywall confirms no OA copy / the doi is unknown to Unpaywall / Europe PMC 404s the pmcid / NCBI has no PMID mapping), still retried on every ordinary run since it's not assumed permanent. `not_available`'s recorded `http_status` is truthful to what actually happened: 404 only when a lookup itself returned HTTP 404, 200 (with a distinct `error` value) when the lookup succeeded but confirmed no usable OA copy, and no fabricated status for a pmid the ID Converter simply has no mapping for.

## Reproduction command

```bash
python -m adc_acquisition publication_bioactivity_corpus --output DATA
```
