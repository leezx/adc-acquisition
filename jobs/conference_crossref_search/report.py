"""Per-source execution report (V1.1 PR #37, live Crossref conference discovery)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# A rough, title-only diagnostic -- NOT a precision measurement. A title
# missing every one of these terms can still be substantively about ADCs
# (e.g. abstract-body-only mentions, or a company internal dev code this
# list doesn't know); this only lower-bounds how many materialized records
# are recognizably ADC-relevant from their title alone, to make Crossref's
# own relevance-ranked-not-phrase search behavior (documented in
# configs/crossref_reconciliation_sources.yaml) visible in THIS job's own
# real output, not just asserted in the abstract.
_ADC_TITLE_HINT_RE = re.compile(
    r"antibody[- ]drug conjugate|\bADCs?\b|vedotin|deruxtecan|govitecan|emtansine|"
    r"mafodotin|tesirine|duocarmazine|maytansinoid|auristatin|\bDXd\b|\bMMAE\b|\bMMAF\b|"
    r"\bDM1\b|\bDM4\b",
    re.IGNORECASE,
)


def build_report(
    result,
    manifest_df: pd.DataFrame,
    all_ids: list,
    active_specs: list,
    terms: list[str],
    signature_rejected_counts,
    output_dir: Path,
    since: str | None = None,
    until: str | None = None,
) -> str:
    run_df = manifest_df[manifest_df["source_record_id"].isin(all_ids)] if not manifest_df.empty else manifest_df

    conference_breakdown = "n/a"
    if not run_df.empty:
        counts = run_df.groupby("conference").size().sort_values(ascending=False)
        conference_breakdown = "\n".join(f"- {conf}: {n}" for conf, n in counts.items())

    sample_rows = "n/a"
    if not run_df.empty:
        sample = run_df.sort_values(["conference", "source_record_id"])
        sample_rows = "\n".join(
            f"- [{row['conference']}] {row['source_record_id']} ({row['issue'] or 'no-issue'}, "
            f"p.{row['page']}): {row['title'][:90] if row['title'] else '(no title)'}"
            for _, row in sample.head(20).iterrows()
        )

    title_hint_line = "n/a"
    if not run_df.empty:
        titles = run_df["title"].fillna("")
        has_hint = titles.apply(lambda t: bool(_ADC_TITLE_HINT_RE.search(t)))
        n_hint, n_total = int(has_hint.sum()), len(has_hint)
        title_hint_line = f"{n_hint} of {n_total} ({100 * n_hint / n_total:.0f}%)"

    rejected_lines = "\n".join(
        f"- {conf}: {n} candidates matched the ISSN/query search but failed the conference's own signature check"
        for conf, n in signature_rejected_counts.items()
    ) or "- none"

    conference_defs = "\n".join(
        f"- **{c.conference_id}**: {c.container_title} (ISSN {', '.join(c.issn)}), "
        f"signature=`{c.signature_type}`" + (f"(value={c.signature_value!r})" if c.signature_value else "")
        for c in active_specs
    )

    repro_flags = ""
    if since:
        repro_flags += f" --since {since}"
    if until:
        repro_flags += f" --until {until}"
    repro_command = f"python -m adc_acquisition conference_crossref_search{repro_flags} --output DATA"

    return f"""# Conference Crossref Search (live ESMO/ASH/EHA/SABCS discovery)

## Acquisition mechanism

LIVE Crossref `/works?` collection queries, one per (conference, query
term) pair, restricted to each conference's own journal ISSN -- see this
job's own module docstring and `configs/conference_crossref_search.yaml`
for why this is tractable despite Crossref's free-text search being
unusable for unrestricted whole-of-Crossref topic discovery (see
`configs/crossref_reconciliation_sources.yaml`).

Query terms this run ({len(terms)}): {", ".join(f'"{t}"' for t in terms)}

Effective date window this run: since={since or 'none (no lower bound)'},
until={until or 'none (no upper bound)'} -- this is part of the EFFECTIVE
query sent to Crossref (`from-pub-date`/`until-pub-date`), and this run's
`query_id`/`query_text` in the discovery ledger are derived from the full
effective query (term + ISSN + this date window), so a differently-windowed
run of the same conference/term is never conflated with this one's
provenance (reviewer-flagged, round-1 fix).

Conferences searched:
{conference_defs}

## Records by conference

{conference_breakdown}

## Conference-attribution signature rejections (NOT ADC-relevance filtering)

Container/ISSN match alone is not conference attribution -- these
candidates matched the journal + search term but were structurally
determined (via each conference's own deterministic signature) to be a
different document (a regular research article, or a different congress's
abstract sharing the same journal) and were excluded from this job's
scope entirely, not acquired-and-disclosed the way ADC-relevance
imprecision is handled elsewhere in this repo:

{rejected_lines}

## Disclosed finding -- most materialized titles don't contain a
## recognizable ADC term (precision, not just recall, is affected)

Title-only diagnostic (NOT a precision measurement -- see
`_ADC_TITLE_HINT_RE`'s own caveat in this job's report.py; a title missing
every listed term can still be substantively about ADCs): only
{title_hint_line} of this run's materialized titles contain a recognizable
ADC-relevant term at all. This is the concrete, in-the-wild confirmation
of `configs/crossref_reconciliation_sources.yaml`'s own documented warning
that Crossref's `query.bibliographic` is relevance-ranked, NOT a
phrase/boolean search -- even restricted to one journal's ISSN, a query
like "antibody-drug conjugate" can rank a work highly for loosely matching
"antibody" or "drug" alone, especially in a large single-journal
collection like Blood's own ASH Annual Meeting supplement. Per this
repo's "acquire broadly, filter downstream" principle (also applied to
China CDE's own two disclosed-imprecise search terms), the full result
set is still materialized as-is -- relevance filtering is left to a
downstream consumer, not silently narrowed here.

## Known, disclosed limitations (not silently narrowed)

**Relevance-ranked search, not phrase/boolean.** Even within one
ISSN-restricted journal collection, Crossref's `query.bibliographic` does
not guarantee exhaustive recall of every genuinely ADC-relevant abstract
in that journal -- the same disclosed recall-ceiling shape as this repo's
existing ASCO Stage-1 candidate-fetch limitation
(`configs/conference_abstract_corpus_queries.yaml`). See the disclosed
finding immediately above for this run's own concrete precision evidence.

**ASH signature covers the current issue-labeling convention only.**
Verified live back through 2018 ("Supplement N"); older, differently
labeled ASH annual-meeting abstracts are not captured this round.

**No target/payload/linker/candidate extraction from this source yet**
(same acquisition/extraction boundary every other job in this repo draws
first) -- deferred to a follow-up increment.

## Materialization this run

{len(all_ids)} unique candidate works discovered and signature-confirmed
(deduplicated by DOI). {result.records_downloaded} newly materialized,
{result.records_skipped_unchanged} skipped_unchanged this run.

## Sample materialized works

{sample_rows}

## Notes

{chr(10).join(f"- {n}" for n in result.notes) or "- none"}

## Reproduction command

```bash
{repro_command}
```
"""
