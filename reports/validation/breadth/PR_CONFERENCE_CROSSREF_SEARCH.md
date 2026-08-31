# Live Crossref conference-abstract discovery: ESMO/ASH/EHA/SABCS (V1.1 #37)

## Why

WHO ICTRP (#34) and China CDE (#36) closed this round's registry-coverage
gaps. The last remaining planned V1.1 increment is conference coverage:
this repo already has AACR/ASCO abstract coverage
(`jobs/conference_abstract_corpus`, a passive reuse of an externally
pre-computed historical corpus), but no ESMO, ASH, EHA, or SABCS coverage
at all -- four of the highest-signal ADC congresses.

## Why this needed a genuinely new job, not an extension of an existing one

- `jobs/crossref` (Job 04) is explicitly DOI-exact reconciliation, not
  discovery: it looks up DOIs already found by other jobs via
  `GET /works/{doi}`. Its own module docstring documents that Crossref's
  free-text search is unusable for unrestricted topic discovery (a bare
  title search across all of Crossref returned 860,937 hits -- see
  `configs/crossref_reconciliation_sources.yaml`).
- `jobs/conference_abstract_corpus` passively reuses an AACR/ASCO corpus
  pre-computed by a workflow OUTSIDE this repo; it makes no live requests
  of its own.

Live-verified 2026-08-31: ESMO, ASH, EHA, and SABCS each publish their
congress abstracts as a SUPPLEMENT ISSUE of one specific, ISSN-identified
journal (ESMO -> Annals of Oncology; ASH -> Blood; EHA -> HemaSphere;
SABCS -> Cancer Research). Restricting Crossref's `query.bibliographic`
search to one journal's ISSN via `filter=issn:...` narrows the candidate
pool from "all of Crossref" to "one journal" -- categorically different in
scale from the unrestricted search the reconciliation job's own docstring
warns against. This makes a new, live-discovery job (`conference_crossref_search`)
tractable without a bespoke per-conference crawler.

## Container/ISSN match is not conference attribution

Every target journal also carries regular (non-congress) research
articles, and Cancer Research specifically carries AACR Annual Meeting AND
SABCS abstracts (and other congresses') side by side in the same
supplement issues. Each conference in `configs/conference_crossref_search.yaml`
declares a `signature_type` -- a deterministic, locally-applied structural
check (`jobs/conference_crossref_search/signatures.py`), live-verified
against real DOIs, that confirms a candidate actually belongs to THIS
congress:

| Congress | Journal | Signature |
|---|---|---|
| ESMO | Annals of Oncology | no `issue` field + S-prefixed `page` |
| ASH | Blood | `issue` contains "Supplement" |
| EHA | HemaSphere | `issue` starts with "S" |
| SABCS | Cancer Research | DOI suffix contains "sabcs" (the only way to separate it from AACR Annual Meeting abstracts sharing the same journal/issue shape) |

A candidate that matches the ISSN/query-term search but fails its
conference's own signature is out of this job's scope entirely -- a
different document, not a low-relevance ADC match to acquire-and-disclose.

## Round-1-lesson applied proactively: discovery-ledger completeness

Same design as the WHO ICTRP/China CDE round-1 fixes, applied from the
start here: a single DOI can be returned by more than one
`adc_query_terms` search within the same conference. The manifest is
content-deduped to one row per DOI; the discovery ledger retains every
real `(doi, query_id)` observation (deduped only within one page-sweep of
the same term, never across terms/conferences). Verified by
`test_same_doi_found_by_two_terms_keeps_both_discovery_observations_but_one_manifest_row`.

## Bug found and fixed during live verification: `score` field content-hash leak

Running the real job twice in a row against live Crossref showed **every**
record spuriously version-bumping on the second, otherwise-identical run.
Root cause: Crossref's `/works?` search response includes a `score` field
-- the record's per-QUERY relevance ranking for that specific search call,
not a property of the record itself -- and it measurably changes between
two immediately-repeated identical queries (`4.8008943` -> `4.8030787` for
the same DOI, seconds apart). This is the exact same class of bug as WHO
ICTRP's `export_file_date`-in-hash leak, except sourced from Crossref's
own API rather than this job's own metadata. Fixed: `score` is excluded
from the hashable dict used for `content_hash` (still present in the
full raw JSON snapshot on disk). Verified against real data: a second live
run after the fix showed `records_skipped_unchanged=1487,
records_downloaded=0`. Regression test:
`test_volatile_relevance_score_change_alone_does_not_bump_version`.

## Disclosed finding -- most materialized titles don't contain a recognizable ADC term

Real-run diagnostic (title-only, NOT a precision measurement -- see
`_ADC_TITLE_HINT_RE`'s own caveat): only 306 of 1487 (21%) of this run's
materialized titles contain a recognizable ADC-relevant term at all. This
is the concrete, in-the-wild confirmation of
`configs/crossref_reconciliation_sources.yaml`'s own documented warning
that `query.bibliographic` is relevance-ranked, not phrase/boolean --
even restricted to a single journal's ISSN, the query "antibody-drug
conjugate" ranks many works highly for loosely matching "antibody" or
"drug" alone (especially in Blood's large ASH Annual Meeting supplement).
Per this repo's "acquire broadly, filter downstream" principle (the same
one applied to China CDE's own two disclosed-imprecise search terms), the
full result set is materialized as-is; relevance filtering is left to a
downstream consumer. This diagnostic is computed live in `report.py` on
every run, not a one-time hardcoded finding, so it stays current as the
underlying data changes.

## Scope: acquisition foundation only

Same boundary as WHO ICTRP/China CDE: materializes DOI + bibliographic +
conference-attribution metadata only (`conference`, `conference_year`,
`container_title`, `publisher`, `volume`, `issue`, `page`,
`conference_attribution_evidence`). No secondary per-DOI fetch needed --
the `/works?` search response already carries full metadata. No
target/payload/linker/candidate extraction.

## `--since`/`--until` are real, wired to Crossref's own date filters

Unlike `jobs/crossref` (DOI-exact reconciliation with no date-filterable
request) and unlike WHO ICTRP/China CDE (manual export, no live query at
all), this job's `/works?` collection endpoint genuinely supports
`from-pub-date`/`until-pub-date` filters, so `--since`/`--until` are wired
through for real, not a documented no-op.

## Live verification

Ran the real job against live Crossref with `--since 2022-01-01` (a
practical initial window, not exhaustive back to 2016 -- can be widened in
a future run; disclosed in the acquisition report, not silently narrowed):
1,487 unique candidate works discovered and signature-confirmed (772 ASH,
540 ESMO, 111 SABCS, 64 EHA), all newly materialized on a clean first run,
then confirmed fully idempotent (`skipped_unchanged=1487`) on a second
live run after the `score`-leak fix. `DATA/manifests/
conference_crossref_search*.parquet` and `reports/acquisition/
conference_crossref_search.md` committed with this PR.

## Tests

29 new tests (5 client + 10 signatures + 14 job), including the
cross-term discovery-observation regression, the signature-rejection
regression (Cancer Research's AACR-vs-SABCS disambiguation), pagination
cursor-following, a page-fetch-failure-degrades-gracefully test, and the
`score`-leak regression described above.

Full suite: 674 passed.

## Reproduction command

```bash
python -m adc_acquisition conference_crossref_search --since 2022-01-01 --output DATA
```
