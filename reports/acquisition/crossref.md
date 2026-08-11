# Crossref (Job 04)

## Acquisition mechanism

Crossref REST API (`GET /works/{doi}`), official REST API. No scraping, no API key required (a `mailto` param opts into the "polite pool").

## Official endpoint / API / dataset

https://api.crossref.org/works/{doi} — https://api.crossref.org/swagger-ui/index.html

## Design note: no broad discovery query, by design

Crossref's `query.bibliographic`/`query.title` params are relevance-ranked full-text search, NOT boolean/phrase search like PubMed/Europe PMC/ClinicalTrials.gov — verified live on 2026-08-11: `query.title="antibody-drug conjugate"` returned 860,937 hits (any work whose title contains "antibody" OR "drug" OR "conjugate"). That's unusable for precise discovery, so this job is DOI-centric reconciliation only (Prompt.md section 16): it looks up DOIs already discovered by other jobs via the authoritative `/works/{doi}` endpoint, which returns richer bibliographic metadata (publisher, license, references, container-title) than PubMed/Europe PMC capture on their own.

## Reconciliation sources used

- CROSSREF_RECONCILE_EUROPE_PMC: 12
- CROSSREF_RECONCILE_PUBMED: 12

- all configured reconciliation sources had a manifest to read

## Records discovered

24 DOI-source pairs across 2 reconciliation sources; 24 unique DOIs.

## Records downloaded

0 new/changed snapshots, 20 skipped as unchanged (matched checkpoint content hash).

## Duplicates

0 DOIs were contributed by more than one upstream source (e.g. a paper indexed by both PubMed and Europe PMC) — each is recorded once in the content manifest; the full multi-source history lives in `crossref_discovery.parquet`.

## Missing fields

- none observed in this run

- records with authors: 20
- records with abstract: 3
- records with references: 14

## Failed downloads

0 (none), of which 0 were DOIs Crossref itself doesn't have a record for (HTTP 404 — not an error, just not indexed there). Failed attempts never occupy a content-manifest version slot.

## Rate/access limitations

No API key required. Crossref returns a dynamic rate limit via response headers (observed live: 10 req/s, concurrency limit 3); this job uses a conservative static 5 req/s rather than adapting to the header in real time.

## Data quality observations

- `abstract` is returned by Crossref with embedded JATS/XML tags (e.g. `<jats:p>`) where present; stored as-is, no tag stripping.
- `references` prefers a reference's own DOI, falling back to unstructured citation text or article title — whichever Crossref's deposit for that work actually included.
- Crossref's `published`/`published-print`/`published-online`/`issued` date fields can disagree or be partial (year-only); the first available in that preference order is used.

## Known coverage gaps

- Only reconciles DOIs from `configs/crossref_reconciliation_sources.yaml`'s currently-active sources (PubMed, Europe PMC); a DOI known only to a not-yet-implemented source (e.g. a future SEC filing) won't be reconciled until that source is added here.
- No broad discovery pass exists for this source — see the design note above.

## Reproduction command

```bash
python -m adc_acquisition crossref --limit 24 --output DATA
```
