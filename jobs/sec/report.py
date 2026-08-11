"""Per-source execution report (Prompt.md sections 13 and 26)."""

from __future__ import annotations

from collections import Counter

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    companies_used: list[str],
    query_id_counts: Counter,
    unique_ids: set[str],
    duplicate_ids: set[str],
    exhibit_attempted: int,
    exhibit_new_or_changed: int,
    exhibit_unchanged: int,
    exhibit_failed: int,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(unique_ids)] if not manifest_df.empty else manifest_df

    form_counts = run_df["filing_type"].value_counts().to_dict() if not run_df.empty else {}
    form_summary = ", ".join(f"{form}: {count}" for form, count in sorted(form_counts.items())) or "n/a"
    company_counts = run_df["company"].value_counts().to_dict() if not run_df.empty else {}
    company_summary = ", ".join(f"{company}: {count}" for company, count in sorted(company_counts.items())) or "n/a"

    missing_fields = []
    for col in ["filing_date", "primary_document"]:
        if col in run_df.columns:
            missing = int(run_df[col].isna().sum())
            if missing:
                missing_fields.append(f"{col} missing in {missing}/{len(run_df)} records")

    companies_line = "\n".join(f"- {c}" for c in companies_used)
    records_per_query = "\n".join(f"- {qid}: {count}" for qid, count in sorted(query_id_counts.items()))

    return f"""# SEC EDGAR (Job 05)

## Acquisition mechanism

SEC EDGAR submissions API (`GET /submissions/CIK{{cik}}.json`) + Archives document retrieval, official REST interfaces. No scraping, no API key required — but every request requires an identifying `User-Agent` header (SEC's fair access policy) or it is rejected with HTTP 403.

## Official endpoint / API / dataset

https://data.sec.gov/submissions/ — https://www.sec.gov/Archives/edgar/data/ — https://www.sec.gov/search-filings/edgar-application-programming-interfaces

## Companies in this run

{companies_line}

## Records discovered

{sum(query_id_counts.values())} relevant-form filings across {len(companies_used)} companies; {len(unique_ids)} unique accession numbers.

## Records downloaded

{result.records_downloaded} new/changed filing snapshots, {result.records_skipped_unchanged} skipped as unchanged (matched checkpoint content hash).

## Duplicates

{len(duplicate_ids)} accession numbers were attributed to more than one company entry (should be rare — normally indicates an alias/CIK overlap worth double-checking in configs/company_registry.yaml).

### Filings per company query

{records_per_query}

## Missing fields

{chr(10).join(f"- {m}" for m in missing_fields) if missing_fields else "- none observed in this run"}

- filing type distribution: {form_summary}
- company distribution: {company_summary}

## Exhibits (independent artifact, see `sec_exhibits.parquet`)

{exhibit_attempted} exhibit fetches attempted this run ({exhibit_new_or_changed} new/changed, {exhibit_unchanged} unchanged, {exhibit_failed} failed). Exhibits are tracked as their own content-version manifest, keyed by `{{accession_number}}:{{filename}}` with `parent_record_id` pointing back to the filing — never as a field on the filing row itself, so an exhibit fetch failure or a later successful retry never touches the filing's own content-version snapshot. A document only counts as an exhibit if SEC's own filing index page types it `EX-*` (parsed from the `{{accession-number}}-index.htm` "Document Format Files" table, `exhibit_type`/`exhibit_description` columns) — GRAPHIC/embedded-image and XBRL support files in the same directory are not exhibits and are not captured here. Exhibit acquisition is attempted for every target filing regardless of whether that filing's own primary document succeeded, failed, or was unchanged.

## Failed downloads

{result.records_failed} ({'see DATA/logs/sec_failures.log and sec_attempts.parquet (status=failed)' if result.records_failed else 'none'}). Failed attempts never occupy a content-manifest version slot.

## Rate/access limitations

Officially documented: max 10 req/s, mandatory identifying `User-Agent` header (name/tool + contact email) or requests are rejected with HTTP 403 and the source IP may be briefly blocked. This job uses 8 req/s to stay under the limit.

## Data quality observations

- `item_codes` (8-K only) are the numbered disclosure items SEC assigns (e.g. "2.01,5.02") — useful downstream for filtering to acquisition/licensing/executive-change items without parsing filing text.
- An amendment (e.g. `10-K/A`) is its own filing with its own accession number, not a patch applied to the original — both remain independent evidence rows by design.
- Only the current 1000 most recent filings plus any additional pages (`filings.files[]`) from the submissions API are covered — a company's full historical filing set is retrieved, not just the most recent page.
- A company can have more than one SEC filer CIK (a redomicile/reincorporation creates a new filer identity — confirmed live for Zymeworks, which redomiciled from British Columbia to Delaware in 2022 and has its pre-2022 filing history under a different CIK). `configs/company_registry.yaml`'s `ciks` field is a list for this reason; every filer CIK's filings are discovered under its own `query_id` (`SEC_FILINGS_{{company_id}}_{{cik}}`).
- `--since`/`--until` filter discovered filings by SEC's own `filing_date` (client-side, since the submissions API has no server-side date filter); `--resume` reuses the prior run's `--until` (or run time) as an implicit `--since`, same convention as Jobs 01/03.

## Known coverage gaps

- Only companies in `configs/company_registry.yaml`'s currently-active entries are covered; expanding coverage means adding more curated entries, not open-ended crawling (Prompt.md section 13/11's shared guidance).
- Relevance filtering here is by SEC form type only (`RELEVANT_FORMS` in `jobs/sec/parser.py`) — no attempt is made to judge whether a given filing actually discusses an ADC program; that is a downstream decision (Prompt.md section 30).
- Observed live: some pre-2002 filings have an empty or incorrect `primaryDocument` in the submissions API itself (before EDGAR required a structured primary-document designation), which surfaces as an expected, logged `failed` attempt (missing document / 404) rather than a crash — this is a genuine SEC-side historical data-quality gap, not an acquisition bug.

## Reproduction command

```bash
python -m adc_acquisition sec --limit {result.records_discovered or 20} --output DATA
```
"""
