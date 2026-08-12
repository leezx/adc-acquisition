"""Per-source execution report (Prompt.md sections 15 and 26)."""

from __future__ import annotations

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    unique_ids: set[str],
    document_attempted: int,
    document_new_or_changed: int,
    document_unchanged: int,
    document_failed: int,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(unique_ids)] if not manifest_df.empty else manifest_df

    medicines_summary = "n/a"
    if not run_df.empty:
        rows = [
            f"- {row['product_number']}: {row['title']}, status: {row.get('status') or 'n/a'}"
            for _, row in run_df.iterrows()
        ]
        medicines_summary = "\n".join(rows)

    status_counts = run_df["status"].value_counts().to_dict() if not run_df.empty else {}
    status_summary = ", ".join(f"{s}: {c}" for s, c in sorted(status_counts.items())) or "n/a"

    return f"""# EMA (Job 07)

## Acquisition mechanism

EMA has no public REST API for this — a single bulk XLSX export ("Download medicine data") covering every EMA-authorised medicine, plus a static per-medicine EPAR HTML page listing its actual documents. Both verified live as plain, non-JS-rendered HTTP resources.

## Official endpoint / dataset

https://www.ema.europa.eu/en/medicines/download-medicine-data — https://www.ema.europa.eu/en/medicines/human/EPAR/&lt;medicine-slug&gt;

## Discovery strategy — systematic INN-suffix matching, not a manual list

configs/ema_adc_substance_patterns.yaml matches standardized WHO INN stems for ADC linker/payload chemistry (vedotin, emtansine, deruxtecan, ozogamicin, govitecan, soravtansine, mafodotin, tesirine) against the bulk file's Name/Active substance columns — verified live to catch all 14 known EMA-authorised ADCs (16 rows, since some have more than one EMA product number from separate application histories, e.g. Blenrep/Mylotarg).

## Medicines discovered

{result.records_discovered} ADC-candidate medicines matched this run.

## Medicines downloaded

{result.records_downloaded} new/changed medicine snapshots, {result.records_skipped_unchanged} skipped as unchanged (matched checkpoint content hash). Status distribution: {status_summary}.

{medicines_summary}

## Documents (independent artifact, see `ema_documents.parquet`)

{document_attempted} document fetches attempted this run ({document_new_or_changed} new/changed, {document_unchanged} unchanged, {document_failed} failed). EPAR documents (product information, assessment reports, safety updates, ...) are tracked as their own content-version manifest, keyed by `{{product_number}}:{{filename}}` with `parent_record_id` pointing back to the medicine — never as a field on the medicine row itself. The EPAR-page fetch that enumerates a medicine's documents has its own self-healing attempt identity (`{{product_number}}:__epar_page__`) so a resolved page-fetch failure doesn't stay permanently "unresolved."

## Failed downloads

{result.records_failed} (see DATA/logs/ema_failures.log and ema_attempts.parquet (status=failed)). Failed attempts never occupy a content-manifest version slot. A medicine's own row can never itself fail to materialize from a network error (its content is already in hand from the one bulk download) — only the EPAR-page fetch and individual document fetches can fail.

## Rate/access limitations

No officially documented rate limit found for ema.europa.eu. Verified live on 2026-08-12: 2 req/s triggered HTTP 429s (with a Retry-After of 0) partway through a run of a few hundred document fetches; 0.5 req/s reduced but did not eliminate this — ema.europa.eu appears to enforce a cumulative session/window throttle, not just a per-request pace limit. Document-level failures from this are genuinely retryable and self-heal on the next `--resume` run (see the failure-safe design below), so this is a real access constraint, not a bug.

## Data quality observations

- Authorisation history and withdrawal information (Prompt.md's explicit ask) live as structured date fields on the medicine row itself (authorisation_date, withdrawal_date, decision_date), not as separate documents.
- `--since`/`--until` filter by each medicine's own `last_updated_date`, applied entirely client-side (the bulk file has no server-side filtering at all). `--resume`'s cursor advances unconditionally every run — any medicine not yet successfully materialized, or with an unresolved document/EPAR-page failure, is unioned back into scope regardless of date, with fresh/in-range medicines always prioritized over that backlog within a `--limit` budget (same failure-safe design as Jobs 05/06, applied here from the start).

## Known coverage gaps

- Discovery only covers currently-listed medicines in EMA's bulk export (which includes authorised, refused, and withdrawn applications, but not investigational products with no EMA procedure at all).
- No terminal-failure category is classified yet (unlike SEC's confirmed-permanent `no_primary_document`) — none has been observed live for EMA.

## Reproduction command

```bash
python -m adc_acquisition ema --limit {result.records_discovered or 20} --output DATA
```
"""
