"""Per-source execution report (Prompt.md sections 7 and 26)."""

from __future__ import annotations

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list[str],
    fresh_ids: list[str],
    backlog_ids: list[str],
    already_skipped_ids: list[str],
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values("source_record_id").head(15)
        sample_rows = "\n".join(
            f"- {row['source_record_id']}: {row['title'] or 'n/a'} (family {row.get('family_id') or 'n/a'})"
            for _, row in sample.iterrows()
        )

    return f"""# WIPO (Job 08)

## Acquisition mechanism

WIPO PATENTSCOPE has no public API, and its Terms of Use Section 2.1 explicitly prohibit automated queries, bulk downloading, and scraping (verified live on 2026-08-13: "more than 10 search-related actions per minute from a single IP can be considered excessive") — a legal constraint, not a technical one. WO-prefixed (PCT) publication data is instead acquired via EPO's Open Patent Services (OPS), a free, registration-based REST API (OAuth2 client-credentials) whose INPADOC/DOCDB data covers WO publications' full bibliographic data.

## Official endpoint / dataset

https://developers.epo.org/ops-v3-2/documentation — `published-data/search` (discovery) and `published-data/publication/docdb/{{...}}/biblio` (bibliographic data), verified live.

## Discovery strategy — CQL queries per Prompt.md's listed search concepts

configs/wipo_queries.yaml (5 queries, each verified live to stay under OPS's 2000-total-result access cap): singular/plural "antibody-drug conjugate(s)" phrase, "immunoconjugate", "antibody AND linker AND cytotoxin", "antibody AND payload AND conjugate" — all restricted to `pn=WO`.

## Publications discovered

{result.records_discovered} unique WO publications matched across {result.queries_run} queries this run.

{sample_rows}

## Materialization this run

{len(fresh_ids)} never-attempted (fresh), {len(backlog_ids)} unresolved-retry (backlog), {len(already_skipped_ids)} already successful and skipped with NO OPS request (WIPO biblio data is treated as immutable once a publication_number exists — see jobs/wipo/job.py docstring for why this deliberately differs from SEC/FDA/EMA's refetch-and-hash-compare pattern). {result.records_downloaded} newly downloaded, {result.records_failed} failed.

## Failed downloads

{result.records_failed} (see DATA/logs/wipo_failures.log and wipo_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run regardless of --resume's date cursor (which never narrows WIPO's search itself — see module docstring).

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
"""
