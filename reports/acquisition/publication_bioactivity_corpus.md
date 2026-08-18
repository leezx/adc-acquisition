# Publication Bioactivity Evidence Corpus (Job 14)

## Acquisition mechanism

SECOND-PASS job -- Prompt.md's input is "PMIDs / PMCIDs / DOIs / known ADC aliases", not a new literature search. DOI candidates are read directly from Job 01 (PubMed)'s `pubmed.parquet`, Job 02 (Europe PMC)'s `europe_pmc.parquet`, and Job 04 (Crossref)'s `crossref.parquet` (latest version per record only), not from a new discovery query. For each candidate DOI: (1) an Unpaywall (https://unpaywall.org) lookup for OA status and locations; (2) a content fetch of the actual bytes, trying Unpaywall's ordered location list until one succeeds (a publisher landing page can block a bot while a repository mirror of the same work succeeds).

## Known scope limitation (disclosed, not silently narrowed)

**Job 02 (Europe PMC)'s own already-resolved full text is NOT duplicated here.** 0 candidate DOI(s) this run were excluded because Europe PMC's own `europe_pmc_fulltext.parquet` already has a successfully materialized full-text artifact for them (joined via pmcid -> doi). This mirrors Job 13's USPTO exclusion: re-downloading the identical article's OA full text under a second table would be pure duplication of Job 02's own work. This count is empirical (checked against real data every run), not an assumption baked into candidate selection -- Unpaywall's coverage is NOT a strict subset of Europe PMC's OA subset (it also covers DOIs Job 02 never discovered, and DOIs where Europe PMC's own is_open_access flag is false/absent but a legal OA copy exists elsewhere), so every other candidate DOI is still attempted here.

## Candidate provenance this run

pubmed: 12, europe_pmc: 12, crossref: 20 (upstream mentions across Jobs 01/02/04; a DOI can appear in more than one, so these do not sum to the number of unique candidate DOIs).

## Materialization this run

24 unique candidate DOIs (after excluding 0 already covered by Job 02). 0 never-attempted (fresh), 21 unresolved-retry (backlog, includes `not_available` -- retried every ordinary run, NOT treated as permanently terminal), 0 pending recovery (raw durable but ledger stale), 3 already successful and skipped with no request.

**This run's outcomes:** 0 success (newly downloaded), 3 skipped_unchanged, 20 not_available, 1 failed -- 24 total attempted/fast-skipped outcomes (must equal the sum of these four).

## Sample materialized artifacts

- 10.1007/bf01741596 (host_type=repository, oa_status=green, upstream=crossref,pubmed, version 1)
- 10.1016/s0014-5793(02)02527-9 (host_type=repository, oa_status=bronze, upstream=crossref,europe_pmc, version 1)
- 10.1128/aac.34.5.875 (host_type=repository, oa_status=green, upstream=pubmed, version 1)

## Failed downloads

1 this run (see DATA/logs/publication_bioactivity_corpus_failures.log and publication_bioactivity_corpus_attempts.parquet, status=failed). Separately, `not_available` (20 this run -- Unpaywall confirmed no OA copy exists, or the DOI is unknown to Unpaywall) is NOT counted as a failure -- it's a genuine negative result, still retried on every ordinary run since it's not assumed permanent.

## Reproduction command

```bash
python -m adc_acquisition publication_bioactivity_corpus --output DATA
```
