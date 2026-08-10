"""Per-source execution report (Prompt.md sections 6 and 26)."""

from __future__ import annotations

from collections import Counter

import pandas as pd

from adc_acquisition.job_base import JobRunResult
from adc_acquisition.query_registry import QuerySpec


def build_report(
    result: JobRunResult,
    manifest_df: pd.DataFrame,
    queries: list[QuerySpec],
    query_id_counts: Counter,
    unique_ids: set[str],
    duplicate_ids: set[str],
    since: str | None = None,
    until: str | None = None,
    fulltext_attempted: int = 0,
    fulltext_new_or_changed: int = 0,
    fulltext_unchanged: int = 0,
    fulltext_failed: int = 0,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(unique_ids)] if not manifest_df.empty else manifest_df

    records_with_abstract = int(run_df["abstract"].notna().sum()) if not run_df.empty else 0
    records_with_doi = int(run_df["doi"].notna().sum()) if not run_df.empty else 0
    open_access = int(run_df["is_open_access"].fillna(False).sum()) if not run_df.empty else 0

    missing_fields = []
    for col in ["title", "abstract", "doi", "journal", "publication_or_release_date"]:
        if col in run_df.columns:
            missing = int(run_df[col].isna().sum())
            if missing:
                missing_fields.append(f"{col} missing in {missing}/{len(run_df)} records")

    queries_used = "\n".join(f"- `{q.query_id}` (v{q.query_version}): `{q.query_text}` — {q.purpose}" for q in queries)
    records_per_query = "\n".join(f"- {qid}: {count}" for qid, count in sorted(query_id_counts.items()))

    return f"""# Europe PMC (Job 02)

## Acquisition mechanism

Europe PMC RESTful Web Service (`search` + `fullTextXML`), official REST API. No scraping, no API key required.

## Official endpoint / API / dataset

https://www.ebi.ac.uk/europepmc/webservices/rest/ — https://europepmc.org/RestfulWebService

## Queries used

{queries_used}

## Date coverage

since={since or "(no lower bound)"}, until={until or "(no upper bound)"} (filtered via `FIRST_PDATE:[...]` when set)

## Records discovered

{sum(query_id_counts.values())} query-hits across {len(queries)} active queries; {len(unique_ids)} unique records.

## Records downloaded

{result.records_downloaded} new/changed metadata snapshots, {result.records_skipped_unchanged} skipped as unchanged (matched checkpoint content hash).

## Duplicates

{len(duplicate_ids)} records were discovered by more than one query. As with PubMed, the content manifest attributes one primary query_id per record; the full multi-query history lives in `europe_pmc_discovery.parquet` (append-only, one row per (record, query, run)).

### Records per query

{records_per_query}

## Missing fields

{chr(10).join(f"- {m}" for m in missing_fields) if missing_fields else "- none observed in this run"}

- records with abstract: {records_with_abstract}
- records with DOI: {records_with_doi}
- open access: {open_access}

## Full text (independent artifact, see `europe_pmc_fulltext.parquet`)

{fulltext_attempted} full-text fetches attempted this run ({fulltext_new_or_changed} new/changed, {fulltext_unchanged} unchanged, {fulltext_failed} failed). Full text is tracked as its own content-version manifest, keyed by pmcid with `parent_record_id` pointing back to the metadata record — never as a field on the metadata row itself, so a full-text fetch failure or a later successful retry can never touch the metadata snapshot.

## Failed downloads

{result.records_failed} ({'see DATA/logs/europe_pmc_failures.log and europe_pmc_attempts.parquet (status=failed)' if result.records_failed else 'none'}). As with PubMed, failed attempts never occupy a content-manifest version slot. Full-text failures are tracked separately in `europe_pmc_fulltext_attempts.parquet` and likewise never touch a content-manifest version slot (metadata's or full text's own).

## Rate/access limitations

No API key or authentication required. No officially published numeric rate limit; ~10 req/s is the figure commonly cited on the Europe PMC developer forum, so this job uses 5 req/s to stay well under it. Full-text XML is only fetched for records marked `isOpenAccess=Y` by Europe PMC itself — publisher paywalls are never bypassed.

## Data quality observations

- `abstractText` from the `resultType=core` search response is used directly as the abstract; no re-processing.
- A full-text fetch that fails (e.g. Europe PMC's own metadata says open access but the fullTextXML endpoint 404s) is retried on every subsequent run — full text is content-hash-checkpointed exactly like metadata, so it is never a permanent per-record failure.
- No deduplication against the PubMed manifest is performed; `pmid`/`doi` are preserved so a downstream join is possible, but a paper appearing in both sources intentionally keeps two independent evidence rows (Prompt.md section 6).

## Known coverage gaps

- Query family mirrors PubMed's four query forms translated into Europe PMC syntax; same terminology-coverage caveat applies.
- Preprints (`source=PPR`) and patents (`source=PAT`) that Europe PMC indexes are captured like any other record if they match a query — no special handling or filtering is applied to them in this job.

## Reproduction command

```bash
python -m adc_acquisition europe_pmc --limit {result.records_discovered or 20} --output DATA
```
"""
