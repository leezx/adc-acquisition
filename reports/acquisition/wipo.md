# WIPO (Job 08)

## Acquisition mechanism

WIPO PATENTSCOPE has no public API, and its Terms of Use Section 2.1 explicitly prohibit automated queries, bulk downloading, and scraping (verified live on 2026-08-13: "more than 10 search-related actions per minute from a single IP can be considered excessive") — a legal constraint, not a technical one. WO-prefixed (PCT) publication data is instead acquired via EPO's Open Patent Services (OPS), a free, registration-based REST API (OAuth2 client-credentials) whose INPADOC/DOCDB data covers WO publications' full bibliographic data.

## Official endpoint / dataset

https://developers.epo.org/ops-v3-2/documentation — `published-data/search` (discovery) and `published-data/publication/docdb/{...}/biblio` (bibliographic data), verified live.

## Discovery strategy — CQL queries per Prompt.md's listed search concepts

configs/wipo_queries.yaml (5 queries, each verified live to stay under OPS's 2000-total-result access cap): singular/plural "antibody-drug conjugate(s)" phrase, "immunoconjugate", "antibody AND linker AND cytotoxin", "antibody AND payload AND conjugate" — all restricted to `pn=WO`.

## Publications discovered

9 unique WO publications matched across 7 queries this run.

- WO2017210473A1: USE OF AN ANTI-PD-1 ANTIBODY IN COMBINATION WITH AN ANTI-CD30 ANTIBODY IN LYMPHOMA TREATMENT (family 59067913)
- WO2018068832A1: HODGKIN LYMPHOMA THERAPY (family 57121286)
- WO2018089890A1: NON-ADULT HUMAN DOSING OF ANTI-CD30 ANTIBODY-DRUG CONJUGATES (family 60543705)

## Materialization this run

9 never-attempted (fresh), 0 unresolved-retry (backlog), 0 already successful and skipped with NO OPS request this run (OPS bibliographic data CAN change via corrections, so this is a default-run efficiency skip, not permanent — run with `--refresh` periodically to re-verify already-successful publications; see jobs/wipo/job.py docstring). 3 newly downloaded, 0 failed.

## Failed downloads

0 (see DATA/logs/wipo_failures.log and wipo_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run regardless of --resume's date cursor (which never narrows WIPO's search itself — see module docstring).

## Rate/access limitations

OPS enforces hourly and weekly quota tiers (verified live via `X-Throttling-Control` response headers) on top of the free tier's documented ~4M requests/month, ~4GB/week fair-use caps. A single query's total accessible result set is capped at 2000 (verified live: CLIENT.InvalidQuery beyond that), and a single search request's Range span is capped at 100 — both enforced in jobs/wipo/client.py.

## Known coverage gaps

- Full document text (description/claims beyond the biblio front page) is not yet acquired — Prompt.md section 7 says to preserve full documents "if legally downloadable," and OPS's fulltext-access terms/entitlement for that were not verified in this round.
- Patent family normalization/deduplication is deliberately NOT performed here (Prompt.md section 7: "Do NOT deduplicate patent families during acquisition — family normalization belongs downstream"); `family_id` is preserved as a raw field per publication instead.
- Job 10 (EPO) will separately query OPS for EP-prefixed publications — the two jobs are architecturally independent (own query_id/provenance namespaces) despite sharing the same underlying API.
- If a registered query's total_result_count approaches OPS's 2000-result access cap, this job currently only logs a warning and silently accesses the first 2000 (not a hard failure) — fine while every registered query stays well under that cap (current max: 1208), but a future query nearing 2000 should be hard-failed or partitioned (e.g. by publication date) rather than allowed to silently truncate discovery long-term.

## Reproduction command

```bash
python -m adc_acquisition wipo --limit 20 --output DATA
```
