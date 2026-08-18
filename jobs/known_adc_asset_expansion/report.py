"""Per-source execution report (Prompt.md sections 19 and 26)."""

from __future__ import annotations

from jobs.known_adc_asset_expansion.asset_registry import KnownADCAsset


def build_report(
    assets: list[KnownADCAsset],
    per_source_query_counts: dict[str, int],
    per_source_results: dict,
) -> str:
    asset_rows = "\n".join(
        f"- **{a.canonical_name}** ({a.asset_id}) — aliases: {', '.join(a.aliases) or 'none'}; "
        f"dev codes: {', '.join(a.dev_codes) or 'none'}; target: {a.target or 'n/a'}; company: {a.company or 'n/a'}"
        for a in assets
    )

    source_rows = "\n".join(
        f"- **{source}**: {per_source_query_counts.get(source, 0)} queries generated — "
        f"{r.records_discovered} discovered, {r.records_downloaded} downloaded, "
        f"{r.records_skipped_unchanged} skipped_unchanged, {r.records_failed} failed"
        for source, r in per_source_results.items()
    )

    total_discovered = sum(r.records_discovered for r in per_source_results.values())
    total_downloaded = sum(r.records_downloaded for r in per_source_results.values())

    return f"""# Known-ADC Asset Expansion (Job 15)

## Acquisition mechanism

ASSET-CENTRIC EXPANSION PASS -- Prompt.md: "another acquisition loop should operate from known asset names," distinct from the broad DISCOVERY PASS Jobs 01-14 already perform ("do not conflate the two passes"). This job generates source-specific searches (bare name/alias, plus "patent"/"trial"/"activity"/"cytotoxicity"/"xenograft"/"IC50" suffixes for PubMed/Europe PMC/USPTO) from a curated known-ADC asset registry, then EXECUTES them by calling Jobs 01 (PubMed), 02 (Europe PMC), 03 (ClinicalTrials.gov), 08 (WIPO), 09 (USPTO), and 10 (EPO) in-process with those queries. This job has NO content manifest of its own -- every discovered/materialized record lands in those jobs' own manifests, tagged with an asset-expansion query_id for provenance. Crossref (Job 04) is not a target (its own free-text search is unusable for precise discovery, already established live).

## Known-ADC asset registry

{len(assets)} active assets:

{asset_rows}

## Per-source execution this run

{source_rows}

**Aggregate:** {total_discovered} records discovered across all sources this run, {total_downloaded} newly downloaded.

Each source's OWN `reports/acquisition/<source>.md` continues to describe ONLY that job's broad-discovery pass, unchanged by this run -- this job explicitly restores it after every sub-invocation (Prompt.md: "do not conflate the two passes" applies to reporting, not just acquisition). Full per-record provenance for what THIS asset-expansion pass discovered lives in each source's OWN `*_discovery.parquet`/`*_attempts.parquet` instead -- every row there is tagged with its own asset-expansion `query_id` (e.g. `PUBMED_ASSETEXP_...`), which is the actual audit trail for "why is this record in our corpus."

## Reproduction command

```bash
python -m adc_acquisition known_adc_asset_expansion --output DATA
```
"""
