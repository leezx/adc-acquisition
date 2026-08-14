# EPO (Job 10)

## Acquisition mechanism

Same official mechanism as Job 08 (WIPO): EPO's Open Patent Services (OPS), a free, registration-based REST API (OAuth2 client-credentials) whose INPADOC/DOCDB data covers publications' full bibliographic data. This job filters to EP-prefixed publications (`pn=EP`) rather than Job 08's WO-prefixed (PCT) publications — architecturally independent (own query registry, own query_id/provenance namespace, own manifest/discovery/attempts triple), sharing only the already-tested OPS client and response parser (adc_acquisition/ops_client.py, adc_acquisition/ops_parser.py).

## Official endpoint / dataset

https://developers.epo.org/ops-v3-2/documentation — `published-data/search` (discovery) and `published-data/publication/docdb/{...}/biblio` (bibliographic data).

## Discovery strategy — CQL queries per Prompt.md's listed search concepts

configs/epo_queries.yaml (5 queries, each verified live to stay under OPS's 2000-total-result access cap): singular/plural "antibody-drug conjugate(s)" phrase, "immunoconjugate", "antibody AND linker AND cytotoxin", "antibody AND payload AND conjugate" — all restricted to `pn=EP`.

## Publications discovered

559 unique EP publications matched across 5 queries this run.

- EP0222360A2: A method of producing a patient-specific cytotoxic reagent and composition. (family 25170824)
- EP0271918A2: Stable formulations of ricin  toxin A chain and of RTA-immunoconjugates and stabilizer screening methods therefor. (family 25481236)
- EP0306943A2: Immunconjugates joined by thioether bonds having reduced toxicity and improved selectivity. (family 22250495)
- EP0318948A2: Cleavable immunoconjugates for the delivery and release of agents in native form. (family 22431215)
- EP0329184A2: Antimers and antimeric conjugation. (family 22565750)
- EP0350230A2: Immunoconjugates for cancer diagnosis and therapy. (family 22807704)
- EP0392745A2: Immunoconjugates and prodrugs and their use in association for drug delivery. (family 10654469)
- EP0485749A2: Chemical modification of antibodies for creating of immunoconjugates. (family 24457023)
- EP0637591A2: A novel expression vector for phytolacca antiviral protein. (family 19358572)
- EP0665020A2: Method for preparing thioether conjugates. (family 22688565)
- EP0842668A1: Ex-corpore method for treating human blood cells (family 08223402)
- EP0873140A2: IMMUNOCONJUGATE FOR THE TREATMENT OF AIDS (family 24339486)
- EP0931836A1: Vasopermeability enhancing peptide of human interleukin-2 and immunoconjugates thereof (family 31720801)
- EP0968002A1: CONCURRENT IN-VIVO IMMUNOCONJUGATE BINDING TO MULTIPLE EPITOPES OF VASCULAR PERMEABILITY FACTOR ON TUMOR-ASSOCIATED BLOOD VESSELS (family 25197602)
- EP1179541A1: Compositions and methods for cancer treatment by selectively inhibiting VEGF (family 22449437)

## Materialization this run

529 never-attempted (fresh), 0 unresolved-retry (backlog), 30 already successful and skipped with NO OPS request this run (OPS bibliographic data CAN change via corrections, so this is a default-run efficiency skip, not permanent — run with `--refresh` periodically to re-verify already-successful publications; see jobs/epo/job.py docstring). 10 newly downloaded, 0 failed.

## Failed downloads

0 (see DATA/logs/epo_failures.log and epo_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run regardless of --resume's date cursor (which never narrows EPO's search itself — see module docstring).

## Rate/access limitations

Same OPS account/quota as Job 08 (WIPO) — see adc_acquisition/ops_client.py for the live-verified per-endpoint throttle-bucket behavior (search vs. retrieval) and this job's shared rate-limit constants.

## Data quality observations

- Live-verified, EP-specific OPS limitation (2026-08-14): `ti=` (title) search with a quoted multi-word phrase, restricted to `pn=EP`, at Range spans greater than 1, reproducibly returns HTTP 500 `SERVER.DomainAccess` — confirmed via isolated A/B testing that this is not query-clause ordering, not OR-combination, and not general OPS system load (concurrent single-word and AND-of-words `pn=EP` queries at the same Range succeeded throughout). Does not reproduce for Job 08 (WIPO)'s identical `pn=WO and ti="..."` pattern. See configs/epo_queries.yaml's header comment for the full investigation. The two phrase queries use `ab=` only as a result (see known coverage gaps below); the immunoconjugate query is unaffected since it searches a single word, not a quoted phrase.

## Known coverage gaps

- The two "antibody-drug conjugate(s)" phrase queries search the ABSTRACT only, not title+abstract like Job 08 (WIPO) — EP-scoped title-phrase search is broken on OPS's side (see Data quality observations). Live-verified impact: the singular-phrase title+abstract count would be 477; abstract-only is 342 — roughly 135 EP publications with the phrase in title only, not abstract, are not discovered by this job. Disclosed here rather than silently narrowed.
- Full document text (description/claims beyond the biblio front page) is not yet acquired — same known gap as Job 08 (WIPO), for the same reason (OPS's fulltext-access entitlement was not verified in this round).
- Patent family normalization/deduplication is deliberately NOT performed here (Prompt.md section 9's WIPO-section instruction "Do NOT deduplicate patent families during acquisition" applies identically here); `family_id` is preserved as a raw field per publication instead.
- If a registered query's total_result_count approaches OPS's 2000-result access cap, this job currently only logs a warning and silently accesses the first 2000 (not a hard failure) — fine while every registered query stays well under that cap (current max: 342), same known limitation as Job 08.

## Reproduction command

```bash
python -m adc_acquisition epo --limit 20 --output DATA
```
