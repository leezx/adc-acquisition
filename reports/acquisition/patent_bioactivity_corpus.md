# Patent Bioactivity Evidence Corpus (Job 13)

## Acquisition mechanism

SECOND-PASS job — "should NOT search the entire patent universe again" (Prompt.md). Candidates are read directly from Job 10 (EPO)'s already-materialized `epo.parquet` manifest (latest version per publication_number only), not from a new OPS search. For each EP publication, two independent artifacts are fetched via EPO OPS's full-text endpoints: `description` (specification body text, where Examples/Experimental/IC50/etc. sections actually live) and `claims`.

## Known scope limitation (disclosed, not silently narrowed)

**WIPO (Job 08)'s WO-prefixed candidates are NOT processed by this job.** Live-verified 2026-08-19: EPO OPS's full-text retrieval is EP-only — a real WO publication (confirmed to exist via live search, biblio succeeds) returns HTTP 404 on description/claims/fulltext. This is a hard OPS data-coverage limitation, not a rate/access issue. WO-only patent families currently have no full text available through any legitimate machine-readable channel this repo uses.

**USPTO (Job 09) is NOT duplicated here.** USPTO's own already-acquired SPEC-type documents (`uspto_documents.parquet`) are the as-filed Specification PDF, already bundling description + claims + abstract for the original filing — exactly the raw evidence this job exists to acquire for EPO, but which USPTO's own job already has.

## Materialization this run

45 EP publication candidates (90 candidate artifacts, 2 per publication: description + claims). 0 never-attempted (fresh), 18 unresolved-retry (backlog, includes `not_available` 404s — retried every ordinary run, NOT treated as permanently terminal), 0 pending recovery (raw durable but ledger stale), 72 already successful and skipped with no request. 0 newly downloaded (new or changed content), 72 unchanged, 0 failed.

## Sample materialized artifacts

- EP0222360A2 (claims, version 1)
- EP0222360A2 (description, version 1)
- EP0271918A2 (claims, version 1)
- EP0271918A2 (description, version 1)
- EP0306943A2 (claims, version 1)
- EP0306943A2 (description, version 1)
- EP0318948A2 (claims, version 1)
- EP0318948A2 (description, version 1)
- EP0329184A2 (claims, version 1)
- EP0329184A2 (description, version 1)
- EP0350230A2 (claims, version 1)
- EP0350230A2 (description, version 1)
- EP0392745A2 (claims, version 1)
- EP0392745A2 (description, version 1)
- EP0485749A2 (claims, version 1)
- EP0485749A2 (description, version 1)
- EP0637591A2 (claims, version 1)
- EP0637591A2 (description, version 1)
- EP0665020A2 (claims, version 1)
- EP0665020A2 (description, version 1)

## Failed downloads

0 (see DATA/logs/patent_bioactivity_corpus_failures.log and patent_bioactivity_corpus_attempts.parquet, status=failed). Separately, `not_available` (OPS confirmed no full text exists for this specific publication/artifact) is NOT counted as a failure — it's a genuine negative result, still retried on every ordinary run since it's not assumed permanent.

## OPS quota note

EPO's OPS free tier has a 4GB/month data quota across ALL OPS usage (not just this job) — full-text documents are far larger than biblio XML. See `result.notes` for this run's downloaded byte total.

## Reproduction command

```bash
python -m adc_acquisition patent_bioactivity_corpus --output DATA
```
