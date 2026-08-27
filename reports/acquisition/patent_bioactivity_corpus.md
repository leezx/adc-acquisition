# Patent Bioactivity Evidence Corpus (Job 13)

## Acquisition mechanism

SECOND-PASS job — "should NOT search the entire patent universe again" (Prompt.md). Candidates are read directly from Job 08 (WIPO)'s `wipo.parquet` AND Job 10 (EPO)'s `epo.parquet` (latest version per publication_number only), not from a new OPS search. For each candidate publication, two independent artifacts are fetched via EPO OPS's full-text endpoints: `description` (specification body text, where Examples/Experimental/IC50/etc. sections actually live) and `claims`.

## Per-authority coverage this run (empirical, not assumed)

- **wipo**: 2104 candidate publications this run — 4100 success, 100 skipped_unchanged, 8 not_available, 0 failed
- **epo**: 505 candidate publications this run — 870 success, 84 skipped_unchanged, 56 not_available, 0 failed

Round-1 fix: an earlier version of this job excluded WIPO candidates entirely, reasoning from a single 404'd WO publication that OPS full-text coverage was EP-only. EPO's own OPS documentation lists full-text availability for multiple authorities including WO — a single 404 only proves that one publication/artifact lacks full text, not that the whole authority is unsupported. WIPO candidates are now attempted exactly like EPO candidates; the numbers above are this run's actual, empirical result, not an assumption.

## Known scope limitation (disclosed, not silently narrowed)

**USPTO (Job 09) is NOT duplicated here.** USPTO's own already-acquired SPEC-type documents (`uspto_documents.parquet`) are the as-filed Specification PDF, already bundling description + claims + abstract for the original filing — exactly the raw evidence this job exists to acquire for WIPO/EPO, but which USPTO's own job already has.

## Materialization this run

2609 candidate publications (wipo: 2104, epo: 505), 5218 candidate artifacts (2 per publication: description + claims). 5014 never-attempted (fresh), 20 unresolved-retry (backlog, includes `not_available` 404s — retried every ordinary run, NOT treated as permanently terminal), 0 pending recovery (raw durable but ledger stale), 184 already successful and skipped with no request.

**This run's outcomes:** 4970 success (newly downloaded), 184 skipped_unchanged, 64 not_available, 0 failed — 5218 total attempted/fast-skipped outcomes (must equal the sum of these four).

## Sample materialized artifacts

- [epo] EP2687202A1 (claims, version 1)
- [epo] EP2687202A1 (description, version 1)
- [epo] EP2796424A1 (claims, version 1)
- [epo] EP2796424A1 (description, version 1)
- [epo] EP3091033A1 (claims, version 1)
- [epo] EP3091033A1 (description, version 1)
- [epo] EP3101032A1 (claims, version 1)
- [epo] EP3101032A1 (description, version 1)
- [epo] EP3130356A1 (claims, version 1)
- [epo] EP3130356A1 (description, version 1)
- [epo] EP3130608A1 (claims, version 1)
- [epo] EP3130608A1 (description, version 1)
- [epo] EP3165237A1 (claims, version 1)
- [epo] EP3165237A1 (description, version 1)
- [epo] EP3210623A1 (claims, version 1)
- [epo] EP3210623A1 (description, version 1)
- [epo] EP3241844A1 (claims, version 1)
- [epo] EP3241844A1 (description, version 1)
- [epo] EP3241846A1 (claims, version 1)
- [epo] EP3241846A1 (description, version 1)

## Failed downloads

0 this run (see DATA/logs/patent_bioactivity_corpus_failures.log and patent_bioactivity_corpus_attempts.parquet, status=failed). Separately, `not_available` (64 this run — OPS confirmed no full text exists) is NOT counted as a failure — it's a genuine negative result, still retried on every ordinary run since it's not assumed permanent.

## OPS quota note

EPO's OPS free tier has a 4GB/WEEK data quota across ALL OPS usage (not just this job) — full-text documents are far larger than biblio XML. See `result.notes` for this run's downloaded byte total.

## Reproduction command

```bash
python -m adc_acquisition patent_bioactivity_corpus --output DATA
```
