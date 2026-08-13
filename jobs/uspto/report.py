"""Per-source execution report (Prompt.md sections 8 and 26)."""

from __future__ import annotations

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list[str],
    backlog_ids: list[str],
    document_attempt_rows: list[dict],
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values("source_record_id").head(15)
        sample_rows = "\n".join(
            f"- {row['application_number']}: {row['title'] or 'n/a'} (status: {row.get('status') or 'n/a'})"
            for _, row in sample.iterrows()
        )

    doc_new = sum(1 for r in document_attempt_rows if r["status"] == "success")
    doc_unchanged = sum(1 for r in document_attempt_rows if r["status"] == "skipped_unchanged")
    doc_failed = sum(1 for r in document_attempt_rows if r["status"] == "failed")

    return f"""# USPTO (Job 09)

## Acquisition mechanism

USPTO's own Open Data Portal (data.uspto.gov, "Patent File Wrapper" API) is the current official mechanism — PatentsView (api.patentsview.org) was shut down 2026-03-20 and now redirects to ODP's own migration guide; developer.uspto.gov is also decommissioned. A free USPTO.gov account + API key is required (`X-API-KEY` header, verified live), but unlike WIPO PATENTSCOPE there is no automation ban — registration-gated, not prohibited.

## Official endpoint / dataset

https://data.uspto.gov/ — `patent/applications/search` (discovery), `patent/applications/{{applicationNumber}}` (full bibliographic record), `patent/applications/{{applicationNumber}}/documents` (file wrapper documents).

## Discovery strategy — free-text queries per Prompt.md's listed search concepts

configs/uspto_queries.yaml (5 queries, same concepts as Job 08/WIPO): singular/plural "antibody-drug conjugate(s)" phrase, "immunoconjugate", "antibody AND linker AND cytotoxin" (0 results in USPTO's corpus, verified live — not a bug, kept for provenance parity), "antibody AND payload AND conjugate". USPTO's free-text search covers full specification content, not just titles.

## Applications discovered

{result.records_discovered} unique applications matched across {result.queries_run} queries this run.

{sample_rows}

## Materialization this run

{result.records_downloaded} new/changed, {result.records_skipped_unchanged} unchanged, {result.records_failed} failed. Unlike Job 08 (WIPO), every discovered application is refetched and hash-compared every run (prosecution status/assignments/continuity data genuinely change over time) — {len(backlog_ids)} of this run's candidates were unresolved retries from a previous failure.

## Documents (independent artifact, see `uspto_documents.parquet`)

{len(document_attempt_rows)} Specification-document candidates considered this run ({doc_new} newly fetched, {doc_unchanged} already resolved and skipped with NO HTTP request, {doc_failed} failed) — filtered to `documentCode == "SPEC"` (the actual filed claims/full-text document; other file wrapper document types — filing receipts, fee worksheets, notices, office actions, ... — are a separate, not-yet-acquired concern). Documents are processed for every application reconciled this run, independent try/except from the application's own outcome. Document versioning is IDENTITY-based, not hash-based: USPTO's `/download` endpoints dynamically re-render the PDF/XML on every request (verified live — different bytes on each of two immediately-successive fetches of the same document), so a document is skipped once its `documentIdentifier` has one successful attempt, rather than being refetched and hash-compared like every other document artifact in this repo.

## Failed downloads

{result.records_failed} (see DATA/logs/uspto_failures.log and uspto_attempts.parquet, status=failed). Failed attempts never occupy a manifest version slot, and are retried on every future run regardless of --resume's date cursor (which never narrows USPTO's search itself — see module docstring).

## Rate/access limitations

Weekly quotas verified live via the account's own consumption dashboard: 5,000,000 metadata retrievals, 1,200,000 document retrievals. A short-window HTTP 429 was observed during rapid successive live-verification calls despite this generous weekly ceiling, so a conservative per-second pace is used regardless (jobs/uspto/client.py). Search page size is capped at 100/request, and a full unrestricted page can trip a 6MB response-payload cap due to each record's large event-history log — discovery uses a minimal `fields=` projection to stay well under it.

## Data quality observations

- `--since`/`--until` filter discovery itself via USPTO's own bracket-range date syntax (`applicationMetaData.filingDate:[...]`), applied server-side only when the caller supplies them explicitly. `--resume`'s implicit cursor never narrows the search this way (would make an unresolved backlog item whose filing predates the cursor undiscoverable) — it and the plain default both run a full undated sweep every run.
- Abstract text is not directly exposed in the bibliographic metadata; it would require parsing the Specification document's own full text (not yet done — see known coverage gaps).

## Known coverage gaps

- Abstract text is not directly available as a structured metadata field — only title, applicants, inventors, filing/publication dates, CPC classification, and foreign priority are captured as structured fields; the Specification document (raw PDF/XML) is preserved separately but not yet parsed for abstract/claims text extraction.
- Only Specification (`SPEC`) documents are acquired — Office Actions, examiner citations, and other file wrapper document types are a separate, not-yet-acquired concern.
- Patent family/continuity resolution is deliberately NOT performed here (Prompt.md: "Do not resolve families yet") — `parentContinuityBag`/`foreignPriorityBag` data is preserved as raw fields instead.

## Reproduction command

```bash
python -m adc_acquisition uspto --limit 20 --output DATA
```
"""
