"""Per-source execution report (BREADTH_PLAN.md Phase 4, Part 6)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list,
    changed_ids: list,
    unchanged_ids: list,
    conference_counts: dict,
    year_file_counts: dict,
    outcome_counts: dict,
    corpus_root: Path,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df
    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["conference", "conference_year", "source_record_id"])
        sample_rows = "\n".join(
            f"- {row['conference']} {row['conference_year']} {row['record_id']} ({row['source_record_id']}, version {row['version']}): {row['title'][:100]}"
            for _, row in sample.head(20).iterrows()
        )

    doi_count = int(run_df["doi"].notna().sum()) if not run_df.empty else 0
    no_doi_count = len(all_ids) - doi_count
    abstract_present_count = int(run_df["abstract"].notna().sum()) if not run_df.empty else 0

    return f"""# Conference Abstract Corpus (BREADTH_PLAN.md Phase 4)

## Acquisition mechanism

NOT a live scrape of AACR/ASCO/Crossref -- this job reuses an already-materialized
local historical corpus built by a separate, external workflow
(REPOS/aacr-abstract-workflow, outside this repo), per Part 6's explicit
instruction to search for reusable historical corpora before any new
download. That workflow queried Crossref for each meeting's own DOI prefix
(AACR: `10.1158/1538-7445.am<year>-*`; ASCO: `10.1200/jco.<year>.*.{{15,16}}_suppl.*`)
and applied an ADC-keyword regex filter -- see
`configs/conference_abstract_corpus_queries.yaml` for the exact, verified
filter text per source, including each filter's disclosed scope limitation
(AACR's is title-only; ASCO's is title+abstract). This job's own
contribution is making that corpus legible to this repo's three-table
acquisition architecture (content-version manifest, discovery ledger,
attempts ledger) and re-runnable idempotently.

Corpus root this run: `{corpus_root}`.

## Known scope limitations (disclosed, not silently narrowed)

**AACR's filter is TITLE-ONLY** (narrower than this repo's own PubMed/Europe
PMC title+abstract queries) -- an AACR abstract that discusses an ADC
substantively without the matched terms in its own title is not in this
corpus at all, and this job cannot recover it; the filtering already
happened upstream, outside this job's control.

**AACR 2026's schema diverges from 2016-2025**: {year_file_counts.get('AACR', 0)} AACR
year-files were found; the 2026 file was built by PDF-extracting the AACR
2026 proceedings text ahead of Crossref indexing, so {no_doi_count} of this
run's {len(all_ids)} candidate records have no `doi` at all (identified
instead by `f"aacr:{{year}}:{{abstract_number}}"`) and no
`publication_or_release_date` -- not fabricated.

**No target/payload/linker/candidate extraction from this corpus's text is
done here** (Part 16 scope discipline) -- this job's only claim is "this
abstract, with this text, was findable in this historical corpus by this
query." Feeding this corpus's title/abstract text into
`tools/breadth/candidate_queue.py`'s USAN/INN suffix matching is deferred to
Phase 5.

## Candidate provenance this run

{conference_counts.get('AACR', 0)} AACR abstracts across {year_file_counts.get('AACR', 0)} year-files,
{conference_counts.get('ASCO', 0)} ASCO abstracts across {year_file_counts.get('ASCO', 0)} year-files.
{doi_count} of {len(all_ids)} candidate records have a doi; {abstract_present_count} have abstract
text materialized (the rest have a title only -- disclosed, not treated as
equivalent evidence depth).

## Materialization this run

{len(all_ids)} unique candidate records. {len(changed_ids)} new-or-changed (content_hash
recomputed and compared against the checkpoint on EVERY run -- cheap here since the
record is already loaded from a local file read, unlike a network-fetch job, so
there is no "trust a prior success without rechecking" fast-skip path),
{len(unchanged_ids)} unchanged this run.

**This run's outcomes:** {result.records_downloaded} success (newly materialized),
{result.records_skipped_unchanged} skipped_unchanged -- {result.records_downloaded + result.records_skipped_unchanged} total
attempted/fast-skipped outcomes (must equal the sum of these two; this job
has no network fetch step, so there is no `failed`/`not_available` outcome
class the way network-dependent jobs have).

## Sample materialized artifacts

{sample_rows}

## Reproduction command

```bash
python -m adc_acquisition conference_abstract_corpus --output DATA
```
"""
