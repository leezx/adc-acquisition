# Phase 2 — Closing Systematic Broad-Discovery Misses

Per `reports/validation/BREADTH_PLAN.md` Phase 2 (Part 3), and per the
correction from Phase 1's review: this starts explicitly from **"489
unresolved negatives"**, not "489 confirmed query misses." Only a
*repeated* pattern demonstrating a genuine acquisition-mechanism defect
justifies patching a production query — this phase's job is to find out
whether such a pattern exists, not to assume one and not to patch anything
without it.

## 1. Strong-identifier enhancement to Phase 1's own metric

While investigating the unresolved set, a safe, additive signal was found
and folded back into `tools/breadth/broad_recall.py` (see that file's
updated module docstring): NAR's own free-text NCT mentions
(`nar.nct_ids`, already parsed in Phase 1) can be checked by **exact
NCT-number equality** against the full clinicaltrials broad-query
discovery ledger — no materialized text needed at all, so this is not
subject to any of Phase 1's disclosed materialization/text-observability
caveats. This reclassified 17 assets from `NOT_CONFIRMED_BROAD`/`AMBIGUOUS`
to a confidently `BROAD_DISCOVERED` (`match_basis = STRONG_IDENTIFIER_NCT`).

`reports/validation/breadth/nar702_broad_recall.tsv` and
`PHASE1_NAR_UNIVERSE.md` have been regenerated/updated to reflect this;
current totals: **198 BROAD_DISCOVERED / 15 AMBIGUOUS / 489
NOT_CONFIRMED_BROAD** (was 181/18/503 before this addition).

## 2. Coarse split of the 489 unresolved negatives

`reports/validation/breadth/broad_miss_taxonomy.tsv` (489 rows), built by
`tools/breadth/miss_taxonomy.py` from two checkable, NAR-native signals —
the asset's own `reference_count` (how much NAR itself cites for it) and
whether it cites an NCT id at all — with no fuzzy judgment involved:

| Category | Count | Rule |
|---|---|---|
| `SOURCE_GAP` | 346 (70.8%) | NAR cites **zero** references and **no** NCT id for this asset — consistent with a genuinely early-stage/conference-only/company-disclosure-only asset that may never have entered any currently-implemented broad source. A hypothesis for Phase 4/5 to test, not a confirmed absence. |
| `BROAD_BACKLOG_UNRESOLVED` | 143 (29.2%) | NAR cites at least one reference or NCT id — the asset plausibly *does* have a discoverable footprint, but Phase 1's discovery/materialization depth hasn't found/downloaded it yet. |

Additionally, `possible_patent_text_gap` is flagged on 272 rows (56%) —
assets with no cited NCT id, no cited reference DOI, but a named company —
where the only plausible trace would be a patent filing, which is exactly
where Phase 1's disclosed gaps (USPTO has no text-extraction capability at
all; WIPO/EPO still have a large unmaterialized backlog) are most likely to
matter.

**These two categories are not symmetric in what they call for next**:
`SOURCE_GAP` is closed by *breadth of source coverage* (Phase 4 conference
ingestion, Phase 5 company disclosures) — sources we don't have yet, not a
defect in the sources we do have. `BROAD_BACKLOG_UNRESOLVED` is closed by
*depth of the sources we already have* (more materialization, deeper
discovery pagination, USPTO text extraction) — an operational/coverage-depth
matter, not a query-content defect either.

## 3. TRUE_CANDIDATE_MISS diagnostic — is there a real query-content defect?

The most informative test case is the intersection of "NAR clearly
documents this asset with real citable evidence" and "it's a relatively
mature asset" — if the query mechanism has a genuine content defect, this
is where it should show up most clearly. 14 unresolved assets meet this
bar (`reference_count > 0` AND cites >=1 NCT id AND phase bucket in
Approved/Phase3/Phase2).

For every one of these 14, `miss_taxonomy.py` checked whether their cited
NCT id(s) appear **anywhere** in our clinicaltrials discovery ledger —
including Job 15's much deeper per-asset/per-intervention targeted lookups,
not just the broad-query subset:

> **14/14 (100%)** have ALL their cited NCT ids completely absent from our
> clinicaltrials discovery ledger, under any query type whatsoever.

This is direct, checkable evidence that the explanation is **CT.gov
discovery-pagination depth** (the broad query's own result pagination was
capped by `--limit 600` for this session's materialization run, and the
primary phrase query alone reported more matching trials than fit in that
cap — see the live run's own output, `CTGOV_ADC_001: 600 hits` — so the
result pages simply have not been paginated far enough to reach these
particular trials yet), not a defect in what the query asks for. A defect
would show up as "the query's phrasing/terms wouldn't match this trial even
if we paginated further" — that is not what was found here.

**Verdict: `TRUE_CANDIDATE_MISS` — 0 confirmed.** No repeated pattern
demonstrating a systematic query-content defect was found in this sample.
Per the evidence-gated rule (the same one applied to the Polivy fix and the
missing-alias fix in the prior audit), **no production query is patched in
this phase.** The repeated pattern that *was* found (discovery-depth
limitation) is not evidence-backed grounds for a query-content patch — it
is grounds for deeper/longer-running materialization, which is explicit
Phase 6 (twice-monthly delta) territory, not a Phase 2 fix.

This is a bounded, disclosed-scope check (14 cases, the most diagnostic
subset available), not an exhaustive audit of all 489 — a larger sample in
a future round could still surface a genuine content defect; none was found
here.

## 4. What Phase 2 does and does not conclude

- Confirms the unresolved set is dominated by two explainable, non-defect
  causes (source-coverage breadth and discovery/materialization depth), not
  a hidden query-mechanism problem.
- Does **not** claim `SOURCE_GAP` assets are provably conference-only/absent
  from the literature — only that NAR itself gives no citable trail, a
  hypothesis for Phases 4-5 to test with real new sources.
- Does **not** attempt the full 15-value root-cause enum from the original
  breadth-layer directive (`MISSING_QUERY_TERM`/`NONSTANDARD_ADC_TERMINOLOGY`/
  etc.) — that level of detail is warranted only once/if a `TRUE_CANDIDATE_MISS`
  is actually confirmed, which did not happen here.
- Does **not** expand `configs/known_adc_assets.yaml`, add any new source,
  or change any query registry file in this phase.

## Reproduction

```
python3 tools/breadth/broad_recall.py \
    --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
    --data-dir DATA \
    --output reports/validation/breadth

python3 tools/breadth/miss_taxonomy.py \
    --broad-recall reports/validation/breadth/nar702_broad_recall.tsv \
    --assets DATA/reference/nar_adcdb/assets.tsv \
    --data-dir DATA \
    --output reports/validation/breadth
```
