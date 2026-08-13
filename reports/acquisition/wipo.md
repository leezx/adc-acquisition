# WIPO (Job 08)

## Acquisition mechanism

WIPO PATENTSCOPE has no public API, and its Terms of Use Section 2.1 explicitly prohibit automated queries, bulk downloading, and scraping (verified live on 2026-08-13: "more than 10 search-related actions per minute from a single IP can be considered excessive") — a legal constraint, not a technical one. WO-prefixed (PCT) publication data is instead acquired via EPO's Open Patent Services (OPS), a free, registration-based REST API (OAuth2 client-credentials) whose INPADOC/DOCDB data covers WO publications' full bibliographic data.

## Official endpoint / dataset

https://developers.epo.org/ops-v3-2/documentation — `published-data/search` (discovery) and `published-data/publication/docdb/{...}/biblio` (bibliographic data), verified live.

## Discovery strategy — CQL queries per Prompt.md's listed search concepts

configs/wipo_queries.yaml (5 queries, each verified live to stay under OPS's 2000-total-result access cap): singular/plural "antibody-drug conjugate(s)" phrase, "immunoconjugate", "antibody AND linker AND cytotoxin", "antibody AND payload AND conjugate" — all restricted to `pn=WO`.

## Publications discovered

2501 unique WO publications matched across 5 queries this run.

- WO0014537A2: DIAGNOSIS OF MULTIDRUG RESISTANCE IN CANCER AND INFECTIOUS LESIONS (family 22274363)
- WO0064946A2: COMPOSITIONS AND METHODS FOR CANCER TREATMENT BY SELECTIVELY INHIBITING VEGF (family 22449437)
- WO0124763A2: COMPOSITIONS AND METHODS FOR TREATING CANCER USING IMMUNOCONJUGATES AND CHEMOTHERAPEUTIC AGENTS (family 22562160)
- WO02094315A2: USE OF PASSIVE MYOSTATIN IMMUNIZATION (family 25036517)
- WO02096437A1: NEUTRON CAPTURE THERAPY (family 09915350)
- WO02100326A2: PHOTOIMMUNOTHERAPIES FOR CANCER USING PHOTOSENSITIZER IMMUNOCONJUGATES AND COMBINATION THERAPIES (family 26964652)
- WO0217968A2: SENSITIZATION OF CANCER CELLS TO IMMUNOCONJUGATE-INDUCED CELL DEATH BY TRANSFECTION WITH IL-13 RECEPTOR ALPHA CHAIN-2 (family 22862891)
- WO0222629A1: ANTI-STILBENE ANTIBODIES (family 24652773)
- WO2004006847A2: SELECTED ANTIBODIES AND DURAMYCIN PEPTIDES BINDING TO ANIONIC PHOSPHOLIPIDS AND AMINOPHOSPHOLIPIDS AND THEIR USE IN TREATING VIRAL INFECTIONS AND CANCER (family 30115998)
- WO2004006962A2: A TISSUE FACTOR BINDING IMMUNOCONJUGATE COMPRISING FACTOR VIIA (family 30011019)

## Materialization this run

2501 never-attempted (fresh), 0 unresolved-retry (backlog), 0 already successful and skipped with NO OPS request (WIPO biblio data is treated as immutable once a publication_number exists — see jobs/wipo/job.py docstring for why this deliberately differs from SEC/FDA/EMA's refetch-and-hash-compare pattern). 10 newly downloaded, 0 failed.

## Failed downloads

0 (see DATA/logs/wipo_failures.log and wipo_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run regardless of --resume's date cursor (which never narrows WIPO's search itself — see module docstring).

## Rate/access limitations

OPS enforces hourly and weekly quota tiers (verified live via `X-Throttling-Control` response headers) on top of the free tier's documented ~4M requests/month, ~4GB/week fair-use caps. A single query's total accessible result set is capped at 2000 (verified live: CLIENT.InvalidQuery beyond that), and a single search request's Range span is capped at 100 — both enforced in jobs/wipo/client.py.

## Known coverage gaps

- Full document text (description/claims beyond the biblio front page) is not yet acquired — Prompt.md section 7 says to preserve full documents "if legally downloadable," and OPS's fulltext-access terms/entitlement for that were not verified in this round.
- Patent family normalization/deduplication is deliberately NOT performed here (Prompt.md section 7: "Do NOT deduplicate patent families during acquisition — family normalization belongs downstream"); `family_id` is preserved as a raw field per publication instead.
- Job 10 (EPO) will separately query OPS for EP-prefixed publications — the two jobs are architecturally independent (own query_id/provenance namespaces) despite sharing the same underlying API.

## Reproduction command

```bash
python -m adc_acquisition wipo --limit 20 --output DATA
```
