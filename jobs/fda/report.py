"""Per-source execution report (Prompt.md sections 14 and 26)."""

from __future__ import annotations

from collections import Counter

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    query_id_counts: Counter,
    unique_ids: set[str],
    duplicate_ids: set[str],
    document_attempted: int,
    document_new_or_changed: int,
    document_unchanged: int,
    document_failed: int,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(unique_ids)] if not manifest_df.empty else manifest_df

    app_counts = run_df["application_number"].value_counts().to_dict() if not run_df.empty else {}
    app_summary = ", ".join(f"{app}: {count}" for app, count in sorted(app_counts.items())) or "n/a"
    class_counts = run_df["submission_class_code_description"].value_counts().to_dict() if not run_df.empty else {}
    class_summary = ", ".join(f"{cls}: {count}" for cls, count in sorted(class_counts.items()) if cls) or "n/a"

    missing_fields = []
    for col in ["submission_status_date", "submission_type"]:
        if col in run_df.columns:
            missing = int(run_df[col].isna().sum())
            if missing:
                missing_fields.append(f"{col} missing in {missing}/{len(run_df)} records")

    records_per_query = "\n".join(f"- {qid}: {count}" for qid, count in sorted(query_id_counts.items()))

    return f"""# FDA (Job 06)

## Acquisition mechanism

openFDA structured product label full-text search (`GET /drug/label.json`) for discovery, Drugs@FDA submissions API (`GET /drug/drugsfda.json`) for reconciliation, plus direct retrieval of the actual regulatory documents (labels, approval letters, review documents) from FDA's Drugs@FDA document archive. Official REST interfaces; an API key is optional (raises the daily quota, never required).

## Official endpoint / API / dataset

https://api.fda.gov/drug/label.json — https://api.fda.gov/drug/drugsfda.json — https://open.fda.gov/apis/drug/drugsfda/

## Discovery strategy — not a manually maintained ADC list

Prompt.md section 14 explicitly prohibits relying on a manually maintained ADC drug list as the primary evidence source. FDA's own structured pharmacologic-class tags (`openfda.pharm_class_epc`/`pharm_class_cs`) turned out NOT to be reliably populated for ADCs when checked live (only 2 of 15 known ADCs carry a class tag at all). Instead, discovery is full-text search of the FDA-approved label's own `mechanism_of_action` and `description` sections for "antibody-drug conjugate" (configs/fda_queries.yaml) — verified live to catch all 15 major approved ADCs. See configs/fda_queries.yaml for the full verification notes.

## Records discovered

{sum(query_id_counts.values())} label-search hits across {len(query_id_counts)} discovery queries; {len(unique_ids)} unique submissions after reconciling each discovered application_number's full Drugs@FDA submission history.

## Records downloaded

{result.records_downloaded} new/changed submission snapshots, {result.records_skipped_unchanged} skipped as unchanged (matched checkpoint content hash).

## Duplicates

{len(duplicate_ids)} submissions were attributed to more than one discovery query (expected overlap between the mechanism_of_action/description full-text queries hitting the same label, not a data-quality concern).

### Label hits per discovery query

{records_per_query}

## Missing fields

{chr(10).join(f"- {m}" for m in missing_fields) if missing_fields else "- none observed in this run"}

- application distribution: {app_summary}
- submission class distribution: {class_summary}

## Documents (independent artifact, see `fda_documents.parquet`)

{document_attempted} document fetches attempted this run ({document_new_or_changed} new/changed, {document_unchanged} unchanged, {document_failed} failed). Documents (labels, approval letters, review documents, medication guides, ...) are tracked as their own content-version manifest, keyed by `{{submission_key}}:{{doc_id}}` with `parent_record_id` pointing back to the submission — never as a field on the submission row itself, so a document fetch failure or a later successful retry never touches the submission's own content-version snapshot.

## Failed downloads

{result.records_failed} (see DATA/logs/fda_failures.log and fda_attempts.parquet (status=failed)). Failed attempts never occupy a content-manifest version slot. Note: a submission's own row can never itself fail to materialize (its "content" is metadata already in hand once the parent application's Drugs@FDA record was fetched) — only document-level fetches (and whole-application-record fetches, which drop that application's submissions from this run entirely rather than partially materializing) can fail.

## Rate/access limitations

openFDA: 240 requests/min either way; 1,000 requests/day without an API key, 120,000/day with one (verified live). `FDA_API_KEY` is optional, read from the environment if present.

## Data quality observations

- A submission's `submission_type`/`submission_number` pair (e.g. ORIG-1, SUPPL-81) is FDA's own regulatory-milestone identifier; an amendment/supplement is its own submission entry, not a patch to the original.
- Some older `application_docs` URLs redirect to a dead page on FDA's modern site (observed live: an "Other Important Information from FDA" doc from 2012 404s after a 301 redirect) — a genuine FDA-side historical link-rot gap, surfaced as an expected logged `failed` attempt, not a crash.
- `--since`/`--until` filter by each submission's own `submission_status_date`; `--resume`'s cursor advances unconditionally every run (same failure-safe design as SEC EDGAR's Job 05, applied here from the start) — any submission not yet successfully materialized, or with an unresolved document failure, is unioned back into scope regardless of date, with fresh/in-range submissions always prioritized over that backlog within a `--limit` budget.

## Known coverage gaps

- Discovery only covers currently FDA-*approved* products with a structured product label — an ADC that was submitted/reviewed but never approved (no label exists) would not be discovered this way; Prompt.md's "review documents" for non-approved products would need a different discovery path if that scope is ever needed.
- No terminal-failure category is classified yet for FDA (unlike SEC's confirmed-permanent `no_primary_document`) — none has been observed live; the --resume backlog protections (fresh-priority ordering) still prevent starvation even without one.

## Reproduction command

```bash
python -m adc_acquisition fda --limit {result.records_discovered or 20} --output DATA
```
"""
