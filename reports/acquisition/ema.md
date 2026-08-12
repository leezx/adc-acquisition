# EMA (Job 07)

## Acquisition mechanism

EMA has no public REST API for this, but explicitly publishes bulk JSON exports intended for automated systems — one covering every EMA-authorised medicine, one covering every EPAR document across every medicine (20,099 records live) with its own stable id/type/dates independent of any single medicine's page. Both verified live as documented, machine-oriented data exports (not scraped from rendered HTML).

## Official endpoint / dataset

https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format — medicines feed + EPAR documents feed

## Discovery strategy — systematic INN-suffix matching, not a manual list

configs/ema_adc_substance_patterns.yaml matches standardized WHO INN stems for ADC linker/payload chemistry (vedotin, emtansine, deruxtecan, ozogamicin, govitecan, soravtansine, mafodotin, tesirine) against the medicines feed's name/active-substance fields — verified live to catch all 14 known EMA-authorised ADCs (16 rows, since some have more than one EMA product number from separate application histories, e.g. Blenrep/Mylotarg).

## Medicines discovered

16 ADC-candidate medicines matched this run.

## Medicines downloaded

0 new/changed medicine snapshots, 16 skipped as unchanged (matched checkpoint content hash). Status distribution: Application withdrawn: 1, Authorised: 13, Expired: 1, Refused: 1.

- EMEA/H/C/000705: Mylotarg (gemtuzumab ozogamicin), status: Refused
- EMEA/H/C/002389: Kadcyla (trastuzumab emtansine), status: Authorised
- EMEA/H/C/002455: Adcetris (Brentuximab vedotin), status: Authorised
- EMEA/H/C/004119: Besponsa (Inotuzumab ozogamicin), status: Authorised
- EMEA/H/C/004204: Mylotarg (gemtuzumab ozogamicin), status: Authorised
- EMEA/H/C/004870: Polivy (polatuzumab vedotin), status: Authorised
- EMEA/H/C/004935: Blenrep (belantamab mafodotin), status: Expired
- EMEA/H/C/005036: Elahere (mirvetuximab soravtansine), status: Authorised
- EMEA/H/C/005124: Enhertu (trastuzumab deruxtecan), status: Authorised
- EMEA/H/C/005182: Trodelvy (sacituzumab govitecan), status: Authorised
- EMEA/H/C/005363: Tivdak (tisotumab vedotin), status: Authorised
- EMEA/H/C/005392: Padcev (Enfortumab vedotin), status: Authorised
- EMEA/H/C/005685: Zynlonta (loncastuximab tesirine), status: Authorised
- EMEA/H/C/006081: Datopotamab deruxtecan Daiichi Sankyo (datopotamab deruxtecan), status: Application withdrawn
- EMEA/H/C/006511: Blenrep (belantamab mafodotin), status: Authorised
- EMEA/H/C/006547: Datroway (datopotamab deruxtecan), status: Authorised

## Documents (independent artifact, see `ema_documents.parquet`)

147 document fetches attempted this run (2 new/changed, 99 unchanged, 46 failed). EPAR documents (product information, assessment reports, public assessment reports, procedural steps, ...) are tracked as their own content-version manifest, keyed by `{product_number}:{doc_id}` (EMA's own stable numeric document id) with `parent_record_id` pointing back to the medicine. Documents are discovered from the bulk documents feed for every ADC-candidate medicine on every run, independent of which medicines `--limit`/`--since`/`--until`/`--resume` selected for materialization — a medicine outside this run's scope can still have a new or updated document discovered.

## Raw bulk snapshots (see `ema_bulk.parquet`)

The exact bytes of both bulk JSON feeds are preserved, content-versioned, every run — so a future EMA schema/data change never leaves us without the actual input that produced a given run's discovery decisions.

## Failed downloads

0 (see DATA/logs/ema_failures.log and ema_attempts.parquet (status=failed)). Failed attempts never occupy a content-manifest version slot. A medicine's own row can never itself fail to materialize from a network error (its content is already in hand from the bulk feed) — only individual document PDF fetches can fail.

## Rate/access limitations

No officially documented rate limit found for ema.europa.eu. Verified live on 2026-08-12: sustained per-medicine-page + per-document request volume (the earlier HTML-scraping design) triggered a cumulative session-level HTTP 429 throttle; switching document discovery to the bulk documents feed eliminates the per-medicine-page requests entirely, leaving only the individual document PDF fetches as per-record traffic.

## Data quality observations

- Authorisation history and withdrawal information (Prompt.md's explicit ask) live as structured date fields on the medicine row itself (authorisation_date, withdrawal_date, decision_date), not as separate documents.
- `--since`/`--until` filter medicines by `last_updated_date`, applied entirely client-side (the bulk feed has no server-side filtering at all). `--resume`'s cursor advances unconditionally every run for medicines — any medicine not yet successfully materialized is unioned back into scope regardless of date, with fresh/in-range medicines always prioritized over that backlog within a `--limit` budget (same failure-safe design as Jobs 05/06).

## Known coverage gaps

- Discovery only covers currently-listed medicines in EMA's bulk export (authorised, refused, and withdrawn applications), not investigational products with no EMA procedure at all.
- Safety-update-specific feeds (PSUSA periodic safety update assessments, DHPC direct healthcare professional communications) are separate EMA datasets and are **not yet acquired here** — only the EPAR documents feed's per-medicine documents are covered, which includes general safety-related EPAR documents but not the dedicated safety feeds.
- No terminal-failure category is classified yet (unlike SEC's confirmed-permanent `no_primary_document`) — none has been observed live for EMA.

## Reproduction command

```bash
python -m adc_acquisition ema --limit 16 --output DATA
```
