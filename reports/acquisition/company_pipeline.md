# Company Pipeline Pages (Job 11)

## Acquisition mechanism

No official API exists for these pages — "fundamentally different from database APIs" (Prompt.md's own framing). Every (company, pipeline_url) pair processed this run comes directly from the curated `configs/company_registry.yaml` (shared with Job 05/SEC), not from a live search/discovery step. A company with no standalone pipeline page (e.g. Seagen/ImmunoGen/Mersana, all acquired/absorbed — see the registry's notes) simply has an empty `pipeline_urls` list.

## Registered companies this run

- Zymeworks Inc. (zymeworks): 1 registered pipeline_url(s)
- Sutro Biopharma, Inc. (sutro_biopharma): 1 registered pipeline_url(s)
- ADC Therapeutics SA (adc_therapeutics): 1 registered pipeline_url(s)
- AbbVie Inc. (abbvie): 1 registered pipeline_url(s)
- Pfizer Inc. (pfizer): 1 registered pipeline_url(s)

## Materialization this run

5 registered (company, pipeline_url) pairs. 0 never-attempted (fresh), 1 unresolved-retry (backlog), 4 already-resolved reverify candidates. 3 newly downloaded (new or changed content), 1 unchanged, 1 failed. Every pair is refetched and hash-compared every run (Prompt.md: "company pipeline pages change over time... snapshots are essential") — there is no skip-by-default the way Job 08/WIPO and Job 10/EPO have.

- ADC Therapeutics SA: Pipeline | ADC Therapeutics (https://www.adctherapeutics.com/our-pipeline1-1/, version 1)
- Pfizer Inc.: Oncology: Cancer Drug Pipeline and Clinical Trials | Pfizer (https://www.pfizer.com/science/oncology-cancer/pipeline, version 1)
- Pfizer Inc.: Oncology: Cancer Drug Pipeline and Clinical Trials | Pfizer (https://www.pfizer.com/science/oncology-cancer/pipeline, version 2)
- Sutro Biopharma, Inc.: Pipeline Draft | Sutro Biopharma, Inc. (https://www.sutrobio.com/pipeline/, version 1)
- Sutro Biopharma, Inc.: Pipeline Draft | Sutro Biopharma, Inc. (https://www.sutrobio.com/pipeline/, version 2)
- Zymeworks Inc.: Pipeline — Zymeworks (https://www.zymeworks.com/pipeline/, version 1)
- Zymeworks Inc.: Pipeline — Zymeworks (https://www.zymeworks.com/pipeline/, version 2)

## Failed downloads

1 (see DATA/logs/company_pipeline_failures.log and company_pipeline_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run.

## Known access limitation

AbbVie's registered pipeline page (https://www.abbvie.com/science/pipeline.html) is behind an active Cloudflare JS challenge (HTTP 403, "Just a moment..." interstitial) — confirmed live 2026-08-14 that a descriptive User-Agent (the fix that resolved fda.gov's simpler bot detection) does NOT get past it. This repo does not attempt to defeat the challenge (Prompt.md prohibits CAPTCHA/bot-challenge bypassing) — every attempt is recorded as a normal, logged `failed` attempt, not silently dropped, until AbbVie offers an alternative official machine-readable route.

## Known coverage gaps

- Individual pipeline program entries (drug names, phases, indications) are NOT extracted from the page — only the raw page snapshot and its `<title>` tag are preserved. Program-level extraction is downstream knowledge extraction (Prompt.md section 1), not acquisition.
- Seagen, ImmunoGen, and Mersana have no standalone pipeline page of their own as of this run (all acquired/absorbed) — their former ADC assets appear only in their acquirers' own pipeline pages (Pfizer, AbbVie) or, for Mersana's Emi-Le, in Day One Biopharmaceuticals' pipeline (Day One is not yet a registered company in this file — a scope decision left for a future round).
- `--since`/`--until` are not applicable (a pipeline page has no natural publication/release date of its own).

## Reproduction command

```bash
python -m adc_acquisition company_pipeline --output DATA
```
