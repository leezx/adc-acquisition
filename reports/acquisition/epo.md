# EPO (Job 10)

## Acquisition mechanism

Same official mechanism as Job 08 (WIPO): EPO's Open Patent Services (OPS), a free, registration-based REST API (OAuth2 client-credentials) whose INPADOC/DOCDB data covers publications' full bibliographic data. This job filters to EP-prefixed publications (`pn=EP`) rather than Job 08's WO-prefixed (PCT) publications — architecturally independent (own query registry, own query_id/provenance namespace, own manifest/discovery/attempts triple), sharing only the already-tested OPS client and response parser (adc_acquisition/ops_client.py, adc_acquisition/ops_parser.py).

## Official endpoint / dataset

https://developers.epo.org/ops-v3-2/documentation — `published-data/search` (discovery) and `published-data/publication/docdb/{...}/biblio` (bibliographic data).

## Discovery strategy — CQL queries per Prompt.md's listed search concepts

configs/epo_queries.yaml (5 queries, each verified live to stay under OPS's 2000-total-result access cap): singular/plural "antibody-drug conjugate(s)" phrase, "immunoconjugate", "antibody AND linker AND cytotoxin", "antibody AND payload AND conjugate" — all restricted to `pn=EP`.

## Publications discovered

1 unique EP publications matched across 7 queries this run.

- EP4248989A2: USE OF AN ANTI-PD-1 ANTIBODY IN COMBINATION WITH AN ANTI-CD30 ANTIBODY IN LYMPHOMA TREATMENT (family 59067913)

## Materialization this run

1 never-attempted (fresh), 0 unresolved-retry (backlog), 0 already successful and skipped with NO OPS request this run (OPS bibliographic data CAN change via corrections, so this is a default-run efficiency skip, not permanent — run with `--refresh` periodically to re-verify already-successful publications; see jobs/epo/job.py docstring). 1 newly downloaded, 0 failed.

## Failed downloads

0 (see DATA/logs/epo_failures.log and epo_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run regardless of --resume's date cursor (which never narrows EPO's search itself — see module docstring).

## Rate/access limitations

Same OPS account/quota as Job 08 (WIPO) — see adc_acquisition/ops_client.py for the live-verified per-endpoint throttle-bucket behavior (search vs. retrieval) and this job's shared rate-limit constants.

## Data quality observations

- Live-verified, EP-specific OPS limitation (2026-08-14, re-confirmed round 2 with 2 additional fallback tests): `ti=` (title) search restricted to `pn=EP` reproducibly returns HTTP 500 `SERVER.DomainAccess` once the query has 3+ effective title terms — whether from a quoted multi-word phrase or an explicit AND of 3+ single words (`ti=antibody and ti=drug and ti=conjugate`) or OPS's own `ti all "..."` operator (both tested, both fail identically). A 2-term `ti=` AND succeeds fine, as does the identical phrase on `ab=`, and the byte-identical `pn=WO` version of every failing query succeeds — isolating this to "3+ terms in ti=, restricted to pn=EP" specifically, not general OPS load or CQL syntax. Does not reproduce for Job 08 (WIPO). See configs/epo_queries.yaml's header comment for the full investigation. The two phrase queries use `ab=` only as a result (see known coverage gaps below); the immunoconjugate query is unaffected since it's a single word.

## Known coverage gaps

- The two "antibody-drug conjugate(s)" phrase queries search the ABSTRACT only, not title+abstract like Job 08 (WIPO) — EP-scoped title-phrase search is broken on OPS's side (see Data quality observations). Live-verified impact: the singular-phrase title+abstract count would be 477; abstract-only is 342 — roughly 135 EP publications with the phrase in title only, not abstract, are not discovered by this job. Disclosed here rather than silently narrowed.
- Full document text (description/claims beyond the biblio front page) is not yet acquired — same known gap as Job 08 (WIPO), for the same reason (OPS's fulltext-access entitlement was not verified in this round).
- Patent family normalization/deduplication is deliberately NOT performed here (Prompt.md section 9's WIPO-section instruction "Do NOT deduplicate patent families during acquisition" applies identically here); `family_id` is preserved as a raw field per publication instead.
- If a registered query's total_result_count approaches OPS's 2000-result access cap, this job currently only logs a warning and silently accesses the first 2000 (not a hard failure) — fine while every registered query stays well under that cap (current max: 342), same known limitation as Job 08.

## Reproduction command

```bash
python -m adc_acquisition epo --limit 20 --output DATA
```
