# Phase 1 — NAR Reference Universe + Broad-Discovery Recall

Per `reports/validation/BREADTH_PLAN.md` Phase 1 (Parts 1-2). This is the
first breadth-layer deliverable: build a reproducible NAR ADCdb reference
universe, then measure **broad-discovery recall** (can generic ADC-discovery
queries find a NAR asset without knowing its name beforehand) as distinct
from **targeted-recovery recall** (already largely proven for our 14
curated assets by the prior benchmark, PR #17).

## 1. NAR reference universe (`DATA/reference/nar_adcdb/`)

Built by `tools/breadth/build_nar_reference_universe.py`, read-only against
the external vault, reusing `tools/validation/compare_nar_adcdb.py`'s proven
702-asset extraction (no re-implementation):

| File | Rows | Source |
|---|---|---|
| `assets.tsv` | 702 | NAR's phase-tagged benchmark universe (`ADCs/`) |
| `adc_targets.tsv` | 316 | NAR `Antigens/` — antibody-binding **delivery target** |
| `payload_moa_targets.tsv` | 52 | NAR `Targets/` — payload **mechanism-of-action target** (a distinct concept, never merged with the above) |
| `antibodies.tsv` | 1,380 | NAR `Antibodies/` |
| `payloads.tsv` | 521 | NAR `Payloads/` |
| `linkers.tsv` | 587 | NAR `Linkers/` |
| `indications.tsv` | 422 distinct strings | derived from the 702 assets' own free-text Indication field — NAR has no dedicated Indications/Diseases page directory, so this is not a separate NAR entity type |

Two schema notes established by direct inspection while writing the parser:
- `Targets/` pages backlink to ADCs via bare `[ADC Info](.../details/{adc_id})`
  URLs, not named `[[ADCs/Name|Name]]` wikilinks like every other component
  type — so `payload_moa_targets.tsv`'s backlinks are `adc_id`-only, no name.
  This is a genuine asymmetry in the external vault, not a parsing bug.
- A majority but not all component pages carry a structured "General
  Information" table (283/316 Antigens, 444/521 Payloads, 1,187/1,380
  Antibodies, 45/52 Targets, 494/587 Linkers); the rest fall back to an
  unstructured scrape with no parseable table. Per Part 16's scope
  discipline, the fallback pages still contribute id/name/backlinks — their
  extra structured fields (synonyms, gene name, etc.) are simply left
  blank, not guessed.

## 2. Materialization deepened before measuring recall

Discovery ledgers already held far more broad-query hits than had ever been
downloaded (no title/abstract/applicant text exists at the discovery-ledger
stage — only materialized manifests carry text, and text is what alias
matching needs). Rather than measure recall against a stale, mostly-empty
materialized set, broad-query-only jobs (not `known_adc_asset_expansion`)
were re-run directly to deepen materialization:

| Source | Materialized before | Materialized after | Unique broad-discovered (ledger) |
|---|---|---|---|
| pubmed | 71 | 647 | 852 |
| europe_pmc | 48 | 628 | 837 |
| clinicaltrials | 493 | 976 | 801 |
| wipo | 51 | 186 | 2,511 |
| epo | 51 | 201 | 561 |
| uspto | 57 | 207 | 2,735 |

This is still **not exhaustive** — WIPO and USPTO in particular still have a
large undownloaded broad-query backlog (2,511 and 2,735 unique discovered
publications respectively, vs. ~180-200 materialized). This is disclosed
explicitly, not hidden: a `NOT_CONFIRMED_BROAD` verdict below means "not
found in currently observable broad evidence," not "provably absent."
Closing this further is Phase 2/6 work, not claimed as done here.

There is a second, independent text-coverage gap on top of materialization
depth: WIPO/EPO's production broad queries search **title+abstract**, but
the materialized manifest (`wipo.parquet`/`epo.parquet`) has no `abstract`
column at all — only `title`/`applicants`/`inventors`. Matching therefore
also greps each broad-discovered record's raw OPS XML response directly
(`find_raw_text_matches`), not just the manifest's structured columns, so
abstract text is actually searched. **USPTO's broad query searches full
specification text**, but Job 09's own `report.md` already discloses that
USPTO's Specification document is stored only as a raw PDF with no text
extraction implemented anywhere in this repo (`patent_bioactivity_corpus`,
Job 13, covers WIPO/EPO full text only) — this is a pre-existing, already-
disclosed capability gap, not something new. USPTO matching in this
analysis therefore remains metadata-only (title/applicants/inventors/
assignees), and its negative results are additionally censored by this gap
on top of materialization depth.

## 3. Broad-discovery recall — locked provenance definition

`BROAD_DISCOVERED` is attributed **only** from records whose discovery-ledger
`query_id` belongs to the allowed set built directly from each source's
production broad-query config (`configs/{pubmed,europe_pmc,wipo,epo,uspto,
clinicaltrials}_queries.yaml`, loaded via `adc_acquisition.query_registry.
load_queries`) — never guessed from a `query_id` prefix. This was confirmed
necessary, not just a formality: WIPO/EPO/USPTO's broad query_ids
(`WIPO_ADC_PHRASE_SINGULAR_001`, etc.) do **not** follow the `{SOURCE}_ADC_
\d+` pattern that PubMed/Europe PMC/CT.gov use — a prefix-guessing approach
would have silently produced a wrong or empty allowed set for three of the
six sources. `known_adc_asset_expansion` (Job 15/ASSETEXP) and CT.gov's
`CTGOV_LOOKUP_INTR_*` per-intervention lookups are excluded as a structural
consequence of only reading the production broad-query configs — not by
pattern-matching them out.

Matches are downgraded from `BROAD_DISCOVERED` to `AMBIGUOUS` when every
matching identifier is shorter than 6 characters — a conservative heuristic
**inspired by**, not equivalent to, the confirmed "Polivy" false-positive
collision in the prior audit (Polivy itself is 6 characters, so this rule
would not have caught it; it is a general collision-risk guard for
short/generic-looking tokens like `JK-06`, `XB-002`, `KH815`, not a
verified classification of the same failure mode). A long, generic phrase
can be just as ambiguous, and a short but highly specific dev code can be
perfectly safe — `AMBIGUOUS` here means "needs a human look before being
counted as clean recall," per Rule M3/M10 (don't equate a fuzzy/short-token
match with a true shared asset; don't optimize the number to look good),
not "confirmed false positive."

## 4. Headline results

`reports/validation/breadth/nar702_broad_recall.tsv` (702 rows):

| Status | Count | % of 702 |
|---|---|---|
| BROAD_DISCOVERED | 181 | 25.8% |
| AMBIGUOUS | 18 | 2.6% |
| TARGETED_ONLY | 0 | 0% |
| NOT_CONFIRMED_BROAD | 503 | 71.7% |

**By phase bucket** (the load-bearing breakdown — recall declines sharply
and monotonically from mature to early-stage assets, matching the "breadth
is the real bottleneck for early-stage/repurposing work" hypothesis this
phase exists to test):

| Bucket | N | BROAD_DISCOVERED | AMBIGUOUS | NOT_CONFIRMED_BROAD |
|---|---|---|---|---|
| Approved | 21 | 19 (90.5%) | 1 | 1 |
| Phase 3 | 37 | 28 (75.7%) | 1 | 8 |
| Phase 2 | 84 | 50 (59.5%) | 6 | 28 |
| Phase 1 | 297 | 77 (25.9%) | 7 | 213 |
| Investigative | 263 | 7 (2.7%) | 3 | 253 |

`TARGETED_ONLY` = 0 is a genuine finding, not a bug: all 14 of our currently
curated known assets (`configs/known_adc_assets.yaml`) are major
approved/late-stage drugs that generic ADC queries already surface on their
own — none of them currently depends on targeted (Job 15/ASSETEXP) evidence
to be found. `reports/validation/breadth/nar702_targeted_recovery.tsv`
records this per-asset (`in_known_registry` / `targeted_recoverable`).

**Gate 1 metric** (BROAD_DISCOVERED or TARGETED_RECOVERABLE, reported here
for transparency — formal gate evaluation is Phase 7's job, not this one):
181/702 = **25.8%**, far below the plan's 95% target. This is expected and
correct at the end of Phase 1 alone; it is not a regression to fix in this
PR.

One Approved asset, **Cetuximab sarotalocan** (a Japan-approved
photoimmunotherapy conjugate), is `NOT_CONFIRMED_BROAD` — plausible given
the still-shallow literature materialization (647/852 pubmed, 628/837
europe_pmc) and the disclosed patent text-coverage gaps above, rather than
evidence of a query defect; a candidate for Phase 2's root-cause review,
not patched here.

## 5. What this does and does not establish

**Only `BROAD_DISCOVERED` (181/702) is a positive, confirmed fact.**
`NOT_CONFIRMED_BROAD` (503/702) is a censored negative, not a proven
absence — it reflects the current, disclosed limits of materialization
depth (§2) and patent text-observability (§3, particularly USPTO), not a
verified claim that broad acquisition cannot find these assets. The correct
summary of this phase is therefore:

> At least 181/702 (25.8%) of NAR's phase-tagged benchmark assets have been
> **confirmed** discoverable by generic, name-agnostic ADC acquisition
> queries, with confirmed recall declining sharply and monotonically from
> mature to early-stage assets (90.5% Approved -> 2.7% Investigative). The
> remaining 503 are **unresolved**, not confirmed misses — materialization/
> text-observability censoring means the true broad-discovery recall is
> unknown but at least 25.8%, i.e. this is a **conservative lower bound**,
> not a final precision figure.

This still supports the hypothesis motivating the whole breadth-layer
directive (confirmed recall for mature/approved assets is far higher than
for early-stage ones), just without overclaiming the magnitude of the
gradient the earlier, uncorrected 90.5% -> 2.7% framing implied. It does
**not** yet root-cause the 503 unresolved assets (Phase 2 — which must
start from "503 unresolved negatives," not "503 confirmed query misses",
and split them into categories such as `BROAD_BACKLOG_UNRESOLVED` /
`PATENT_TEXT_NOT_OBSERVABLE` / `TRUE_CANDIDATE_MISS` / `SOURCE_GAP` before
any query is patched), build any feasibility entity model (Phase 3), add
conference ingestion (Phase 4), or evaluate any freeze gate (Phase 7).

## Reproduction

```
python3 tools/breadth/build_nar_reference_universe.py \
    --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
    --output DATA/reference/nar_adcdb

python3 tools/breadth/broad_recall.py \
    --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
    --data-dir DATA \
    --output reports/validation/breadth
```
