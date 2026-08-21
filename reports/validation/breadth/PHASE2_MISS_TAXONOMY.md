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
whether it cites an NCT id at all. **Category names are deliberately
observation-based, not causal** (round-1 correction: a category name that
already asserts a root cause overstates what a two-signal rule can
actually establish) — the causal *guess* lives in a separate
`root_cause_hypothesis` column instead, so a later phase can revise it
without renaming or reinterpreting the observation itself:

| Category (observation) | Count | What was actually checked | `root_cause_hypothesis` |
|---|---|---|---|
| `NO_NAR_EXTERNAL_CITATION_SIGNAL` | 346 (70.8%) | NAR cites **zero** references and **no** NCT id for this asset | `POSSIBLE_SOURCE_GAP` — consistent with, but not proof of, a genuinely early-stage/conference-only/company-disclosure-only asset |
| `NAR_EXTERNAL_CITATION_PRESENT` | 143 (29.2%) | NAR cites at least one reference or NCT id | `POSSIBLE_DISCOVERY_OR_MATERIALIZATION_DEPTH` — consistent with, but not proof of, an asset our broad discovery/materialization simply hasn't reached yet |

Neither observation rules out the other's hypothesis: "NAR cites nothing"
does not prove the asset only exists in a source we don't query, and "NAR
cites something" does not prove our query wording would actually match
it if we materialized/paginated further — it could just as well be a
query-scope/wording mismatch. §3 investigates this distinction directly
for the most diagnostic subset, rather than asserting it from the coarse
split alone.

Additionally, `possible_patent_text_gap` is flagged on 272 rows (56%) —
assets with no cited NCT id, no cited reference DOI, but a named company —
where the only plausible trace would be a patent filing, which is exactly
where Phase 1's disclosed gaps (USPTO has no text-extraction capability at
all; WIPO/EPO still have a large unmaterialized backlog) are most likely to
matter. Kept explicitly "possible" per the same discipline.

## 3. Is there evidence of a real query-content defect? (diagnostic, not proof either way)

The most informative test case is the intersection of "NAR clearly
documents this asset with real citable evidence" and "it's a relatively
mature asset" — if the query mechanism had a genuine content defect, this
is where it should show up most clearly. 14 unresolved assets meet this
bar (`reference_count > 0` AND cites >=1 NCT id AND phase bucket in
Approved/Phase3/Phase2).

For every one of these 14, `miss_taxonomy.py` checked whether their cited
NCT id(s) appear **anywhere** in our clinicaltrials discovery ledger, under
any query type:

> **14/14 (100%)** have ALL their cited NCT ids completely absent from our
> clinicaltrials discovery ledger, under any query type whatsoever.

**This does NOT, by itself, prove CT.gov discovery-pagination depth is the
explanation** (an earlier draft of this report overclaimed exactly that,
and was corrected). Two things had to be checked, not assumed:

1. **Job 15 registry membership.** Job 15's per-asset/per-intervention
   targeted lookups only ever run for assets already in
   `configs/known_adc_assets.yaml`. Checked directly: **all 14 of these
   assets are NOT in that registry.** So "absent from the ledger's
   targeted query_ids" is expected and uninformative for every one of
   them — no targeted lookup was ever attempted, and its absence proves
   nothing about the query mechanism.
2. **Pagination-depth vs. query-scope mismatch.** CT.gov's broad-query
   pagination genuinely is `--limit`-capped this session
   (`jobs/clinicaltrials/job.py` stops paginating once
   `len(record_first_query) >= args.limit`; the live run's own output
   showed `CTGOV_ADC_001: 600 hits`, right at the cap), which makes
   discovery-depth censoring a **plausible** explanation. But absence from
   the ledger alone cannot distinguish "we simply haven't paginated far
   enough" from "the query's phrasing/terms wouldn't match this trial even
   with full pagination." Confirming pagination-depth specifically (as
   opposed to a scope/wording mismatch) would require fetching each
   flagged trial's own intervention/title text and checking it offline
   against the current broad query's semantics — not done in this script.

**Verdict: `TRUE_CANDIDATE_MISS` — 0 confirmed.** This means *no evidence
was found in this round to confirm a query-content defect* — it does
**not** mean "proven to be pagination depth" and does **not** mean "proven
the query is complete." Per the same evidence-gated rule already applied
to the Polivy fix and the missing-alias fix in the prior audit, **no
production query is patched in this phase**, because there is no confirmed
defect to fix — but this absence of a confirmed defect is not itself
proof that none exists.

This is a bounded, disclosed-scope check (14 cases, the most diagnostic
subset available), not an exhaustive audit of all 489, and not a
definitive root-cause determination for even those 14 — a genuine offline
query-semantics check on this same set of trials (Phase 4/5/6 candidate
work, not required to close Phase 2) could still confirm or rule out
pagination-depth specifically.

## 4. What Phase 2 does and does not conclude

- Establishes two DISTINCT, checkable observations about the unresolved
  set (does NAR cite external evidence for it, or not) without asserting
  either observation's causal explanation as fact.
- Does **not** claim `NO_NAR_EXTERNAL_CITATION_SIGNAL` assets are provably
  conference-only/absent from the literature — only that NAR itself gives
  no citable trail; `POSSIBLE_SOURCE_GAP` is a hypothesis for Phases 4-5 to
  test with real new sources, not a conclusion.
- Does **not** claim `NAR_EXTERNAL_CITATION_PRESENT` assets are provably
  just a materialization/depth problem — `POSSIBLE_DISCOVERY_OR_
  MATERIALIZATION_DEPTH` is likewise a hypothesis, not a conclusion; §3's
  diagnostic found no counter-evidence in its 14-case sample, but also did
  not positively confirm the hypothesis.
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
