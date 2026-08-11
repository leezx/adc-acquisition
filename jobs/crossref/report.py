"""Per-source execution report (Prompt.md sections 16 and 26)."""

from __future__ import annotations

from collections import Counter

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    sources_used: list[str],
    query_id_counts: Counter,
    unique_ids: set[str],
    duplicate_ids: set[str],
    not_found_count: int,
    skipped_missing_manifests: list[str],
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(unique_ids)] if not manifest_df.empty else manifest_df

    with_authors = int(run_df["authors"].apply(lambda a: a is not None and len(a) > 0).sum()) if not run_df.empty else 0
    with_abstract = int(run_df["abstract"].notna().sum()) if not run_df.empty else 0
    with_references = int(run_df["references"].apply(lambda r: r is not None and len(r) > 0).sum()) if not run_df.empty else 0

    missing_fields = []
    for col in ["title", "publisher", "container_title", "published_date"]:
        if col in run_df.columns:
            missing = int(run_df[col].isna().sum())
            if missing:
                missing_fields.append(f"{col} missing in {missing}/{len(run_df)} records")

    records_per_source = "\n".join(f"- {qid}: {count}" for qid, count in sorted(query_id_counts.items()))

    return f"""# Crossref (Job 04)

## Acquisition mechanism

Crossref REST API (`GET /works/{{doi}}`), official REST API. No scraping, no API key required (a `mailto` param opts into the "polite pool").

## Official endpoint / API / dataset

https://api.crossref.org/works/{{doi}} — https://api.crossref.org/swagger-ui/index.html

## Design note: no broad discovery query, by design

Crossref's `query.bibliographic`/`query.title` params are relevance-ranked full-text search, NOT boolean/phrase search like PubMed/Europe PMC/ClinicalTrials.gov — verified live on 2026-08-11: `query.title="antibody-drug conjugate"` returned 860,937 hits (any work whose title contains "antibody" OR "drug" OR "conjugate"). That's unusable for precise discovery, so this job is DOI-centric reconciliation only (Prompt.md section 16): it looks up DOIs already discovered by other jobs via the authoritative `/works/{{doi}}` endpoint, which returns richer bibliographic metadata (publisher, license, references, container-title) than PubMed/Europe PMC capture on their own.

## Reconciliation sources used

{records_per_source}

{chr(10).join(f"- skipped (manifest not found yet): {s}" for s in skipped_missing_manifests) if skipped_missing_manifests else "- all configured reconciliation sources had a manifest to read"}

## Records discovered

{sum(query_id_counts.values())} DOI-source pairs across {len(sources_used)} reconciliation sources; {len(unique_ids)} unique DOIs.

## Records downloaded

{result.records_downloaded} new/changed snapshots, {result.records_skipped_unchanged} skipped as unchanged (matched checkpoint content hash).

## Duplicates

{len(duplicate_ids)} DOIs were contributed by more than one upstream source (e.g. a paper indexed by both PubMed and Europe PMC) — each is recorded once in the content manifest; the full multi-source history lives in `crossref_discovery.parquet`.

## Missing fields

{chr(10).join(f"- {m}" for m in missing_fields) if missing_fields else "- none observed in this run"}

- records with authors: {with_authors}
- records with abstract: {with_abstract}
- records with references: {with_references}

## Failed downloads

{result.records_failed} ({'see DATA/logs/crossref_failures.log and crossref_attempts.parquet (status=failed)' if result.records_failed else 'none'}), of which {not_found_count} were DOIs Crossref itself doesn't have a record for (HTTP 404 — not an error, just not indexed there). Failed attempts never occupy a content-manifest version slot.

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
python -m adc_acquisition crossref --limit {result.records_discovered or 20} --output DATA
```
"""
