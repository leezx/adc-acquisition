# Fix: PubMed job crashes when a query's hit count exceeds NCBI's ESearch ceiling

## Why

The 2026-08-31/09-01 maintenance cadence run's `pubmed` job failed (exit 1)
while every other one of the 20 registered acquisition jobs succeeded.
Diagnosed live: NCBI's ESearch API has a hard, documented ceiling --
`retstart` cannot exceed 9998 ("For PubMed, ESearch can only retrieve the
first 9,999 records matching the query"). Two of PubMed's four active
queries (`PUBMED_ADC_001`/`002`, the core hyphenated/unhyphenated phrase
queries) have grown to 10,691 hits each, past that ceiling. A request at
`retstart=10000` returns HTTP 200 with a **malformed JSON error body** (a
literal, unescaped newline byte inside the `ERROR` string), which crashed
`response.json()` uncaught in `jobs/pubmed/client.py`'s `esearch()`.

This is not a transient network issue -- confirmed 100% reproducible
(same query, same `retstart`, same error, across three separate attempts).
It will fail identically every future 14-day cadence run until fixed. This
is a targeted bug fix, not new acquisition-source work, so it does not
reopen the V1.1 freeze.

## Impact of the bug (before this fix)

`run()`'s discovery phase collects all four queries' PMIDs purely in
memory before any manifest/checkpoint write happens. The crash on query 1
aborted the entire job immediately -- **zero new PubMed records were
collected that cycle**, not just the two oversized queries' overflow. No
data corruption (nothing had been written yet), but a full loss of that
run's PubMed acquisition.

## Fix

`jobs/pubmed/job.py`: added `NCBI_ESEARCH_MAX_RETSTART = 9998`. The
discovery pagination loop now never requests a `retstart` past this
ceiling -- when a query's true hit count exceeds what's reachable, the
loop stops cleanly and the query is recorded as truncated (in-memory,
alongside the existing `query_id_counts` tracking) rather than crashing.

Truncation is disclosed, not silently absorbed, matching this repo's
established "no silent truncation" discipline (e.g.
`conference_crossref_search`'s `MAX_PAGES_PER_QUERY`): a `logger.warning`
and a `result.notes` entry naming the query, its true hit count, and NCBI's
own EDirect/history-based batching docs as the path to full coverage if
ever needed. `jobs/pubmed/report.py`'s existing "Known coverage gaps"
section now surfaces these notes in the committed acquisition report.

## Round-1 fix (reviewer-flagged): retained records must be newest-first

Truncating at the ceiling is only correctness-safe for 14-day rolling
maintenance if the RETAINED first ~10,000 records are guaranteed to be
the NEWEST ones. NCBI ESearch's default order is relevance, not
publication date -- confirmed via NCBI's own documentation, `pub_date`
descending is an explicitly supported sort. Without it, a just-published
but lower-relevance-scored paper could land in the permanently
unreachable tail and never be discovered by any future cadence run.

Fixed: `PubMedClient.esearch()` now always sends `sort="pub_date"`
(descending) -- a real, always-applied default parameter, not
conditional. The truncated tail is therefore deterministically the
OLDEST portion of an oversized query, never an arbitrary/relevance-ranked
subset. `result.notes`/the acquisition report now state this explicitly:
"the truncated tail represents the OLDEST portion of this oversized query
... rolling 14-day maintenance still reliably captures newly published
papers." NCBI's own EDirect/history-based batching remains the disclosed,
deliberately out-of-scope path to full >10k historical coverage.

Also fixed in passing (the non-blocking nit from the same review): the
truncation warning/note now reports the query's real `hits_for_query`
count directly instead of a reconstructed `min()` estimate.

## Live verification

Ran the real job against live NCBI (`python -m adc_acquisition pubmed
--output DATA`) both before and after this round's fix. After: completed
successfully, no crash -- `records_discovered=10294,
records_downloaded=310, records_skipped_unchanged=9976,
records_failed=8`, with both truncated queries correctly reporting
`9999 of 10691 true hits discovered` (the real `hits_for_query` value,
matching the fix above) and the newest-first sort disclosure, surfaced in
`reports/acquisition/pubmed.md`. `DATA/manifests/pubmed*.parquet` and the
report committed with this PR as the real evidence.

## Tests

5 new tests: `test_esearch_never_requests_retstart_past_ncbi_ceiling` (a
synthetic 10,100-hit query, asserts no request ever exceeds
`retstart=9998` and the truncation note fires),
`test_report_surfaces_retstart_ceiling_truncation` (the note reaches the
committed report), `test_normal_sized_query_under_ceiling_is_unaffected`
(regression guard -- every real, normal-sized query in this repo's actual
config is unaffected, no behavior change), plus this round's
`test_esearch_always_sorts_by_publication_date_descending`
(`tests/jobs/pubmed/test_client.py`) and an assertion added to the
ceiling test confirming every request for an oversized query carries
`sort=pub_date` and the notes state the "OLDEST portion" framing.

Full suite: 689 passed.

## Reproduction command

```bash
python -m adc_acquisition pubmed --output DATA
```
