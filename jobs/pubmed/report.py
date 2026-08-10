"""Per-source execution report (Prompt.md sections 5 and 26)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from adc_acquisition.job_base import JobRunResult
from adc_acquisition.query_registry import QuerySpec

REPRODUCTION_COMMAND_TEMPLATE = (
    "python -m adc_acquisition pubmed --since {since} --until {until} --limit {limit} --output DATA"
)


def build_report(
    result: JobRunResult,
    manifest_df: pd.DataFrame,
    queries: list[QuerySpec],
    query_id_counts: Counter,
    unique_pmids: set[str],
    duplicate_pmids: set[str],
    since: str | None,
    until: str | None,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(unique_pmids)] if not manifest_df.empty else manifest_df

    records_with_abstract = int(run_df["abstract"].notna().sum()) if not run_df.empty else 0
    records_without_abstract = int(len(run_df) - records_with_abstract) if not run_df.empty else 0
    records_with_doi = int(run_df["doi"].notna().sum()) if not run_df.empty else 0

    date_distribution = "n/a"
    if not run_df.empty:
        years = run_df["publication_or_release_date"].dropna().astype(str).str.slice(0, 4)
        year_counts = years.value_counts().sort_index()
        if not year_counts.empty:
            date_distribution = ", ".join(f"{year}: {count}" for year, count in year_counts.items())

    missing_fields = []
    for col in ["title", "abstract", "doi", "journal", "publication_or_release_date"]:
        if col in run_df.columns:
            missing = int(run_df[col].isna().sum())
            if missing:
                missing_fields.append(f"{col} missing in {missing}/{len(run_df)} records")

    queries_used = "\n".join(f"- `{q.query_id}` (v{q.query_version}): `{q.query_text}` — {q.purpose}" for q in queries)
    records_per_query = "\n".join(f"- {qid}: {count}" for qid, count in sorted(query_id_counts.items()))

    return f"""# PubMed (Job 01)

## Acquisition mechanism

NCBI E-utilities (`esearch` + `efetch`), official REST API. No scraping.

## Official endpoint / API / dataset

https://eutils.ncbi.nlm.nih.gov/entrez/eutils/ — https://www.ncbi.nlm.nih.gov/books/NBK25501/

## Queries used

{queries_used}

## Date coverage

since={since or "(no lower bound)"}, until={until or "(no upper bound)"}

## Records discovered

{sum(query_id_counts.values())} query-hits across {len(queries)} active queries; {len(unique_pmids)} unique PMIDs.

## Records downloaded

{result.records_downloaded} downloaded, {result.records_skipped_unchanged} skipped as unchanged (matched checkpoint content hash).

## Duplicates

{len(duplicate_pmids)} PMIDs were discovered by more than one query (each is recorded once in the manifest, attributed to the first query that discovered it; all discovering queries are still visible in this report's per-query counts).

### Records per query

{records_per_query}

## Missing fields

{chr(10).join(f"- {m}" for m in missing_fields) if missing_fields else "- none observed in this run"}

- records with abstract: {records_with_abstract}
- records without abstract: {records_without_abstract}
- records with DOI: {records_with_doi}

## Failed downloads

{result.records_failed} ({'see DATA/logs/pubmed_failures.log' if result.records_failed else 'none'})

## Rate/access limitations

3 req/s without an NCBI API key, 10 req/s with one (Job used {"a key" if result.notes and 'api_key' in ' '.join(result.notes) else "the configured client"}). No authentication required for metadata access.

## Data quality observations

- Abstracts are metadata-level (title/abstract/MeSH), not full text.
- Structured abstracts (with Label attributes) are flattened to `Label: text` blocks joined by blank lines.
- `publication_or_release_date` preserves whatever precision PubMed provides (year, year-month, or year-month-day); some records only carry a `MedlineDate` free-text range.

## Known coverage gaps

- Query family covers phrase/abbreviation/immunoconjugate forms only (configs/pubmed_queries.yaml); it will miss papers that describe an ADC without using any of those terms.
- No full text is retrieved here — see Job 02 (Europe PMC / PMC) for legally accessible full text.

## Date distribution

{date_distribution}

## Reproduction command

```bash
{REPRODUCTION_COMMAND_TEMPLATE.format(since=since or "1900-01-01", until=until or "3000-01-01", limit=result.records_discovered or 20)}
```
"""
