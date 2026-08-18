"""Per-source execution report (Prompt.md sections 18 and 26)."""

from __future__ import annotations

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list,
    fresh_ids: list,
    backlog_ids: list,
    pending_recovery_ids: list,
    fast_skip_ids: list,
    candidates_by_source: dict,
    outcome_counts: dict,
    not_available_this_run: int,
    already_covered_count: int,
    identifier_type_counts: dict,
    pmid_candidates_total: int,
    pmid_resolved_to_doi: int,
    pmid_resolved_to_pmcid: int,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["source_record_id"])
        sample_rows = "\n".join(
            f"- {row['source_record_id']} (identifier_type={row['identifier_type']}, host_type={row['host_type']}, "
            f"oa_status={row['oa_status']}, upstream={row['upstream_sources']}, version {row['version']})"
            for _, row in sample.head(20).iterrows()
        )

    candidates_by_source_str = ", ".join(f"{source}: {count}" for source, count in candidates_by_source.items())
    total_outcomes = (
        result.records_downloaded + result.records_skipped_unchanged + not_available_this_run + result.records_failed
    )
    pmid_resolved_total = pmid_resolved_to_doi + pmid_resolved_to_pmcid

    return f"""# Publication Bioactivity Evidence Corpus (Job 14)

## Acquisition mechanism

SECOND-PASS job -- Prompt.md's input is "PMIDs / PMCIDs / DOIs / known ADC aliases", not a new literature search. Candidates are read directly from Job 01 (PubMed)'s `pubmed.parquet`, Job 02 (Europe PMC)'s `europe_pmc.parquet`, and Job 04 (Crossref)'s `crossref.parquet` (latest version per record only), not from a new discovery query. "known ADC aliases"-driven discovery is deferred to Job 15 -- this job only reconciles exact identifiers (doi/pmcid/pmid) those three jobs already discovered.

For each candidate record, acquisition routes by its most specific available identifier: a **doi** goes through (1) an Unpaywall (https://unpaywall.org) lookup for OA status and locations, then (2) a content fetch trying every URL a location offers (PDF, then landing page, then generic `url`) before moving to the next location -- a publisher landing page can serve full text as HTML even when its PDF link blocks a bot. A **pmcid** (no doi known) is fetched directly from Europe PMC's own `fullTextXML` endpoint -- the exact mechanism Job 02 itself uses, attempted here because Job 02 may not have fetched it for this specific record. A **pmid-only** record (no doi, no pmcid) is first resolved via NCBI's own PMC ID Converter (exact-identifier lookup, not a search) before falling back to `not_available` if NCBI has no mapping for it.

## Known scope limitations (disclosed, not silently narrowed)

**Job 02 (Europe PMC)'s own already-resolved full text is NOT duplicated here.** {already_covered_count} candidate record(s) this run were excluded because Europe PMC's own `europe_pmc_fulltext.parquet` already has a successfully materialized full-text artifact for their pmcid (checked directly by pmcid, not via a doi round-trip). This mirrors Job 13's USPTO exclusion: re-downloading the identical article's OA full text under a second table would be pure duplication of Job 02's own work. Unpaywall/direct-pmcid coverage is NOT a strict subset of Europe PMC's OA subset, so every other candidate record is still attempted here.

**"known ADC aliases"-driven discovery is Job 15's job, not this one's.** This job only works through exact identifiers (doi/pmcid/pmid) already present in Jobs 01/02/04's manifests; it never searches PubMed/Europe PMC/Unpaywall by asset alias.

## Candidate identifier coverage this run (empirical, not assumed)

{identifier_type_counts.get('doi', 0)} doi-addressable, {identifier_type_counts.get('pmcid', 0)} pmcid-addressable (no doi known), {identifier_type_counts.get('pmid_unresolved', 0)} unresolved identifier-only candidates (pmid only, no doi/pmcid mapping found). Of {pmid_candidates_total} upstream mentions that started as pmid-only (no doi, no pmcid at load time), {pmid_resolved_total} were resolved via NCBI's PMC ID Converter this run ({pmid_resolved_to_doi} to a doi, {pmid_resolved_to_pmcid} to a pmcid) -- round-1 fix: the initial version of this job silently dropped every such record instead of resolving it.

## Candidate provenance this run

{candidates_by_source_str} (upstream mentions across Jobs 01/02/04; a record can appear in more than one, so these do not sum to the number of unique candidate records).

## Materialization this run

{len(all_ids)} unique candidate records (after excluding {already_covered_count} already covered by Job 02). {len(fresh_ids)} never-attempted (fresh), {len(backlog_ids)} unresolved-retry (backlog, includes `not_available` -- retried every ordinary run, NOT treated as permanently terminal), {len(pending_recovery_ids)} pending recovery (raw durable but ledger stale), {len(fast_skip_ids)} already successful and skipped with no request.

**This run's outcomes:** {result.records_downloaded} success (newly downloaded), {result.records_skipped_unchanged} skipped_unchanged, {not_available_this_run} not_available, {result.records_failed} failed -- {total_outcomes} total attempted/fast-skipped outcomes (must equal the sum of these four).

## Sample materialized artifacts

{sample_rows}

## Failed downloads

{result.records_failed} this run (see DATA/logs/publication_bioactivity_corpus_failures.log and publication_bioactivity_corpus_attempts.parquet, status=failed). Separately, `not_available` ({not_available_this_run} this run) is NOT counted as a failure -- it's a genuine negative result (Unpaywall confirms no OA copy / the doi is unknown to Unpaywall / Europe PMC 404s the pmcid / NCBI has no PMID mapping), still retried on every ordinary run since it's not assumed permanent. `not_available`'s recorded `http_status` is truthful to what actually happened: 404 only when a lookup itself returned HTTP 404, 200 (with a distinct `error` value) when the lookup succeeded but confirmed no usable OA copy, and no fabricated status for a pmid the ID Converter simply has no mapping for.

## Reproduction command

```bash
python -m adc_acquisition publication_bioactivity_corpus --output DATA
```
"""
