# Breadth-Layer Closure Audit — Phase 1–5e vs. the Six Freeze Gates

Per `reports/validation/BREADTH_PLAN.md` Phase 7 ("Final breadth benchmark
+ freeze decision") and the reviewer's explicit instruction after PR #27's
APPROVE: put the cumulative Phase 1–5e results against all six acceptance
gates (`BREADTH_PLAN.md` Section 4), and use that to answer two
DELIBERATELY SEPARATE questions (Section 7/8): whether Phase 6 (the
14-day delta system) should start next, and whether breadth itself is
ready to be frozen as v1 — the second does not follow from the first,
and conflating them is exactly the failure mode the freeze gates exist
to prevent.

**This report recommends a verdict; it does not unilaterally declare
one.** Every prior phase in this project has been gated on the reviewer's
own explicit APPROVE/REQUEST_CHANGES, and a freeze decision is exactly
the kind of judgment call that discipline exists to protect — the
analysis below is real, and the recommendation is a real recommendation,
but the actual freeze/no-freeze call is the reviewer's to make.

## 0. A real gap found and closed before this audit could even run

Before any gate could be honestly evaluated, one thing had to be checked:
does the NAR-comparison tooling this whole benchmark depends on actually
reflect the breadth layer as it exists today? It did not.
`tools/breadth/broad_recall.py` and `tools/validation/compare_nar_adcdb.py`
predate Phase 4 (conference-abstract ingestion) and were **never
extended** to include `conference_abstract_corpus` in the NAR-702
broad-discovery comparison — a pure oversight (the tool simply predates
the source), not a deliberate exclusion. `configs/
conference_abstract_corpus_queries.yaml`'s own header already
self-declares "both are deliberately declared broad-discovery queries
for Phase 1's locked provenance definition," so this was a completeness
gap in the MEASUREMENT, not in the source's own qualification.

Fixed (additive only, no existing behavior changed): `conference_
abstract_corpus` added to `MANIFEST_NAMES`/`TEXT_COLUMNS`/
`DISCOVERY_SOURCES` in `compare_nar_adcdb.py` and to `BROAD_QUERY_CONFIGS`
in `broad_recall.py`. Re-ran the full 702-asset benchmark against the
live vault. Result:

```
BEFORE (Phase 1/2, 6 sources):  BROAD_DISCOVERED 198/702 (28.2%)
AFTER  (Phase 7, 7 sources):    BROAD_DISCOVERED 305/702 (43.4%)
```

**124 of the 702 NAR assets are found ONLY via conference_abstract_corpus**
— they would still show `NOT_CONFIRMED_BROAD` without it. This is a
direct, measured confirmation of the hypothesis that motivated
prioritizing Phase 4 above every other Phase 5 increment in the first
place ("preclinical/early-seed ADCs most often first appear here and
nowhere else" — `BREADTH_PLAN.md` Phase 4). It is also the single most
important number in this entire audit: **the "new source" strategy is
empirically working, not just plausible.**

`reports/validation/breadth/nar702_broad_recall.tsv`/
`nar702_targeted_recovery.tsv` have been regenerated with this fix;
`PHASE1_NAR_UNIVERSE.md` is left as the historical record of what Phase 1
itself established, with a pointer added to this report.

## 1. Gate 1 — NAR reference coverage (≥95% BROAD_DISCOVERED or TARGETED_RECOVERABLE)

**NOT MET. 305/702 = 43.4%.** By phase bucket (recall still declines
monotonically from mature to early-stage, as Phase 1 originally
hypothesized, just less steeply than the pre-Phase-4 numbers implied):

| Bucket | N | BROAD_DISCOVERED | AMBIGUOUS | NOT_CONFIRMED_BROAD |
|---|---|---|---|---|
| Approved | 21 | 19 (90.5%) | 1 | 1 |
| Phase 3 | 37 | 33 (89.2%) | 1 | 3 |
| Phase 2 | 84 | 66 (78.6%) | 7 | 11 |
| Phase 1 | 297 | 157 (52.9%) | 12 | 128 |
| Investigative | 263 | 30 (11.4%) | 11 | 222 |

**Why the shortfall is diagnosed, not mysterious** (Phase 2's own
`miss_taxonomy.py` diagnostic, unchanged by this audit): a stratified
14-case check of the most diagnostic unresolved subset (real NAR-cited
evidence + a mature phase bucket) found **0 confirmed query-content
defects** — no production query is known to be missing a term or
mismatched in scope. The shortfall instead traces to two disclosed,
concrete limitations:

1. **Materialization-depth backlog**, especially in patents:

   | Source | Materialized / Discovered | % |
   |---|---|---|
   | conference_abstract_corpus | 2,456 / 2,456 | 100.0% |
   | clinicaltrials | 622 / 801 | 77.7% |
   | europe_pmc | 600 / 837 | 71.7% |
   | pubmed | 599 / 852 | 70.3% |
   | epo | 197 / 561 | 35.1% |
   | **wipo** | **167 / 2,511** | **6.7%** |
   | **uspto** | **182 / 2,735** | **6.7%** |

   WIPO and USPTO have each discovered well over 2,500 potentially
   relevant records but materialized under 7% of them. This is the
   single largest lever left to raise Gate 1 further, and it requires no
   new source or query — just more downloading of what discovery already
   found.
2. **Text-observability gaps**: USPTO's Specification document is a raw
   PDF with no text-extraction capability anywhere in this repo (a
   pre-existing, already-disclosed gap, not new to this audit) — USPTO
   matching is metadata-only (title/applicants/inventors/assignees) even
   for fully-materialized records.

`NOT_CONFIRMED_BROAD` (365/702, 52.0%) is therefore a **censored
negative, not a proven miss** — true recall is unknown but at least
43.4%, a conservative lower bound, exactly as Phase 1 originally framed
its own (lower) number.

**ROUND-1 FIX — the causal claim below was overstated in an earlier
draft of this report and is corrected here.** Materialization depth and
text observability are **demonstrated major contributors** to the
remaining gap (the WIPO/USPTO numbers above are real and severe). But
Phase 2's 14-case diagnostic (`PHASE2_MISS_TAXONOMY.md` §3) checked only
the most diagnostic subset available — assets with real NAR-cited
evidence AND a mature phase bucket — and found no confirmed query-
content defect *among those 14*. That does **not** extend to a claim
that all 365 currently-unresolved assets are purely a depth problem: a
genuine query-scope gap, an uncovered source, or some other capability
gap could still exist among the remaining unresolved set, and this
audit has not checked for one. The honest statement is: **materialization
depth and text observability are demonstrated major contributors to the
remaining gap; the limited Phase 2 diagnostic found no confirmed
query-content defect, but does not exclude additional query/source/
capability gaps among the remaining unresolved assets.**

**Recommendation:** this gate is a genuine, real, disclosed gap, with at
least part of it attributable to materialization depth rather than a
missing source/capability — but not proven to be *entirely* that.
Closing it further requires both continued materialization (Phase 6's
natural remit) and a broader root-cause pass than Phase 2's 14-case
sample (not attempted here). This gate is **not met** by any reading,
and is treated as such in the verdict below.

## 2. Gate 2 — Approved assets (100% recognized/recoverable unless a documented ontology exclusion applies)

**19/21 (90.5%).** Two unresolved, each different in kind:

- **Cetuximab sarotalocan (Akalux)** — `NOT_CONFIRMED_BROAD`, unchanged
  by adding conference_abstract_corpus. Checked its own NAR record
  directly: its "payload" is **IRDye 700DX**, a near-infrared
  photosensitizer dye activated by light, not a cytotoxic small
  molecule — this is a **photoimmunotherapy conjugate**, not a classical
  ADC, structurally analogous to the already-precedented
  `moxetumomab_pasudotox` immunotoxin exclusion Gate 2's own text names
  as an example. **Flagged as a plausible ontology-exclusion candidate,
  not asserted as one** — that decision belongs to whoever owns this
  gate's acceptance criteria, the same way the moxetumomab_pasudotox
  precedent was presumably a deliberate, documented call, not an
  automatic one.
- **Trastuzumab botidotin (Sertaly)** — `AMBIGUOUS` (low-confidence alias
  match only, in `conference_abstract_corpus` + `pubmed`). **ROUND-1
  FIX**: an earlier draft of this report reproduced NAR's own record
  verbatim as "Approved (FDA): Oct, 2025." External verification (Kelun-
  Biotech's own press releases, prnewswire.com, and independent news
  coverage, October 2025) confirms the October 2025 approval was by
  **China's NMPA**, for adult HER2+ breast cancer patients who received
  >=1 prior anti-HER2 therapy — not an FDA approval. The live ADCdb
  website itself currently shows the same "Approved (FDA)" label, so
  this is an **upstream NAR/ADCdb reference-metadata error**, not
  something introduced by this audit or this repo — treated here as a
  documented inconsistency rather than reproduced as fact. This is a
  genuinely valuable benchmark finding in its own right: it demonstrates
  this system can catch an error in the reference benchmark itself, not
  just measure recall against it.

  Separately, its `AMBIGUOUS` broad-recall status should **not** be
  attributed to recency without evidence for that specifically: the
  asset has multiple mature-looking identifiers (`A166`, `KL-A166`,
  `trastuzumab botidotin`), and at least NCI's own thesaurus already
  indexes `A166`. The correct, undemonstrated-cause framing is: an
  **unresolved identifier/matching or evidence-observability gap**;
  recency may contribute but is not demonstrated as the cause.

**Recommendation:** effectively 20/21 (95.2%) once Cetuximab sarotalocan
is treated as a probable ontology exclusion (pending an explicit
decision) — Gate 2 is close to met, but the one clear residual gap
(Trastuzumab botidotin) has an undemonstrated cause and should not be
assumed to self-resolve on a timeline; it needs the same kind of
identifier/matching investigation Phase 2's diagnostic applied to other
cases, not deferred as a recency issue.

## 3. Gate 3 — Component breadth (ADC_TARGET, PAYLOAD_MOA_TARGET, payloads, linkers; ontology split preserved)

**Split requirement: MET, robustly, since Phase 1.** `adc_targets.tsv`
(`ADC_TARGET`) and `payload_moa_targets.tsv` (`PAYLOAD_MOA_TARGET`,
added Phase 5e) are two physically separate files/entity_types,
never merged, verified at every phase since Phase 1 (Phase 5e's own
round-1 fix specifically double-checked this while adding the payload/
linker evidence-tier work).

**Coverage requirement: NOT fully met, and disclosed as such since
Phase 3.** Current state:

| Table | Entities | Scope |
|---|---|---|
| `adc_targets.tsv` | 11 (from 14 known-registry candidates) | known-registry only |
| `payload_moa_targets.tsv` | 2 (Tubulin, TOP1) | 6 of 8 USAN suffix classes only |
| `adc_payloads.tsv` | 8 (USAN suffix classes) | known-registry + new candidates |
| `adc_linkers.tsv` | 8 (USAN suffix classes) | known-registry + new candidates |
| `adc_platforms.tsv` | 29 | mined from free text, Phase 5e |

`adc_targets.tsv` covers only the 14 known-registry assets' targets, not
any of the 16 Phase 3/5a-discovered candidates (`target=""`, honestly
left blank every phase since Phase 3 — no target-identification
mechanism has ever been built for free-text-discovered candidates).
`payload_moa_targets.tsv` is deliberately capped at 6/8 suffix classes
(ozogamicin/tesirine's DNA-damaging payloads have no single discrete
protein target — a correct omission, not a gap).

**Recommendation:** the gate's own phrase is "at least all **reliably
extractable**" NAR targets/payloads/linkers — read narrowly, our current
tables ARE the reliably-extractable set given the mechanisms actually
built (suffix inference + registry lookup + this phase's text-
corroboration ladder); read broadly (comprehensive coverage of NAR's
full 316-antigen/522-payload/589-linker universe), it is clearly not
met. This is a genuine ambiguity in the gate's own wording that the
reviewer should resolve explicitly rather than have this audit assume
an answer. Either way: **target resolution for new candidates remains
0/16, a real, disclosed, currently-open gap** (see Section 7 for why
this does not block Phase 6 but does block a freeze verdict) — closing
it needs a new target-identification mechanism (a capability gap), not
more of what already exists.

## 4. Gate 4 — Ours-only value (non-trivial, provenance-preserving entities absent from NAR)

**MET, but the honest composition is narrower than Phase 3/5a's own
framing implied — a real finding from this audit, not previously
checked.**

**The clean, strong signal: 29 `ADC_PLATFORM` entities (Phase 5e).**
NAR's own reference schema (Antigen/Antibody/Payload/Linker/Target
component pages) has **no platform-entity category at all** — this is
categorical, not a name-level miss. 297 real evidence mentions across
`conference_abstract_corpus`/`pubmed`/`europe_pmc` back these entities,
3 corroborated across independent corpora. This is the single strongest
"beyond NAR" claim this project can currently make.

**The candidate-level claim needed re-checking, and mostly does not
hold.** Phase 3/5a's "16 new candidates" were framed as new discoveries;
this audit cross-referenced all 16 against NAR's own 702-asset universe
(canonical name + synonyms + dev codes + antibody-component name) and
found:

```
15/16 ALREADY IN NAR (just independently rediscovered by our own
      conference/CT.gov mechanism, under NAR's own dev-code-based
      canonical name in some cases, e.g. "bulumtatug fuvedotin" =
      NAR's "9MW-2821")
 1/16 (denintuzumab mafodotin) not matched against any NAR identifier
      field checked -- plausibly genuinely NAR-absent, not
      independently confirmed beyond this identifier check
```

This is not a negative finding about data quality — quite the opposite,
it is a **positive precision signal**: our own independent discovery
mechanism correctly finds real, legitimate ADCs that an independent
reference database (NAR) also documents, with 0 confirmed false
positives among the 16. But it means Gate 4's "ours-only value" claim
should rest on the platform layer (Section above) and this one
candidate, not on "16 new candidates" as a headline number — that
framing, while not incorrect about their VALIDATED status, overstated
their novelty relative to NAR specifically.

**Recommendation:** Gate 4 is met on the strength of the platform layer
alone. The candidate-layer novelty claim should be corrected in future
phase framing (not retroactively rewritten here — see Section 0's
precedent of leaving historical reports as historical record).

## 5. Gate 5 — Incremental update (two controlled delta runs demonstrate stability)

**NOT YET EVALUABLE — structurally, not as a gap.** `update_breadth`
orchestration and the delta-snapshot mechanism (Phase 6, `BREADTH_PLAN.md`
Parts 12–13) do not exist yet. This was anticipated from the start:
`BREADTH_PLAN.md`'s own capability table (Section 2, item 14) already
listed "Six freeze gates, re-run against real numbers" as "Not yet
evaluable — depends on 1–3," and Phase 6 has always come AFTER breadth
work in the plan's sequencing.

**Recommendation:** this is not a v1-blocker to entering Phase 6 — it is
the reverse. Gate 5 can only be evaluated by building and then running
Phase 6 twice; it is Phase 6's own acceptance criterion, not a
precondition for starting Phase 6.

## 6. Gate 6 — Precision (stratified audit of candidate promotions per entity type)

**Real numbers, not previously aggregated in one place:**

| Entity type | Promoted | Precision signal |
|---|---|---|
| `ADC_CANDIDATE` (known-registry) | 14 | 14/14 independently audited as real antibody ADCs in PR #17 (pre-dates this breadth initiative) |
| `ADC_CANDIDATE` (new, Phase 3/5a) | 16 | 15/16 cross-confirmed against NAR's independent 702-asset universe (Section 4); 0 confirmed false positives |
| `ADC_CANDIDATE` (correctly withheld) | 23 `NEEDS_REVIEW`, 0 `REJECTED` | 1 of these, zelenectide pevedotin, is confirmed `ADJACENT_CONJUGATE_MODALITY` (a Bicycle Toxin Conjugate, not a true ADC) and is correctly excluded from promotion by the modality gate (Phase 5b) — a genuine caught-before-promotion case, not a missed one |
| `ADC_PLATFORM` | 29 | 100% individually verified against a real quoted sentence during Phase 5e (by construction, not a post-hoc sample — see caveat below) |
| `ADC_PAYLOAD`/`ADC_LINKER` | 8 each | 8/8 payload classes, 7/8 linker classes independently corroborate against NAR's own vocabulary (Phase 5e coverage audit) — a consistency check, not a novel precision claim, since this is the same public USAN/INN nomenclature NAR also draws from |

**Caveat, disclosed rather than hidden**: the `ADC_PLATFORM` "100%
verified" figure was verified by the same person/process that built the
extraction, not an independent third-party auditor — real, and each
entry does have a real quoted sentence anyone can check, but this is
not the same evidentiary weight as an independent stratified sample
audit by someone who didn't build the mechanism. No adjacent-modality-
style promoted false positive has been found anywhere in this project's
history to date, across every phase's review cycles.

**Recommendation:** Gate 6 is reasonably well supported by real numbers,
but has never had a genuinely independent (non-builder) sample audit.
Recommend this as an explicit, lightweight v1.x task (e.g. a domain
expert spot-checks 10-15 promoted entities across types) rather than a
v1 blocker, since no evidence of a precision problem exists to justify
blocking on it now.

## 7. Blocks Phase 6 vs. blocks ACQUISITION_V1 freeze — kept as two separate questions

**ROUND-1 FIX.** An earlier draft of this report used a single "v1-blocker
vs. v1.x-defer" column, which is exactly the kind of conflation the
freeze gates exist to prevent: it let "Phase 6 can start" quietly stand
in for "breadth is done." These are two different questions with two
different answers, kept explicitly separate below.

| Gap | Blocks Phase 6 start? | Blocks ACQUISITION_V1 freeze? | Why |
|---|---|---|---|
| Gate 1 shortfall (43.4% vs. 95% target) | **No** | **Yes — open** | Materialization depth (WIPO/USPTO under 7% materialized) is a demonstrated major contributor, but Phase 2's 14-case diagnostic does not clear the remaining ~365 unresolved assets of every possible query/source/capability gap. Genuinely unmet, not merely "depth, so it's fine" |
| Gate 2's 2 unresolved Approved assets | **No** | **Yes — open** | 1 plausible ontology exclusion (photoimmunotherapy conjugate, pending explicit decision); 1 (Trastuzumab botidotin) an unresolved identifier/matching or observability gap with an undemonstrated cause — this case also surfaced a real NAR/ADCdb upstream metadata error (FDA vs. NMPA), worth reporting upstream independent of this repo |
| Gate 3's target-resolution gap for new candidates (0/16) | **No** | **Yes — open** | Requires a new target-identification mechanism (a real capability gap, not a depth gap), honestly disclosed since Phase 3, still 0/16 |
| Gate 4's candidate-novelty overstatement | **No** | **No — already corrected** | Reframing only, resolved in this report — the entities are still correctly VALIDATED, just not "beyond NAR"; the 29 platforms remain the real beyond-NAR claim |
| Gate 5 (delta system) | **N/A — this IS Phase 6** | **Not yet evaluable** | Cannot be tested before Phase 6 exists; Phase 6's own two controlled delta runs ARE gate 5's evaluation, not a precondition for starting Phase 6 |
| Gate 6's independent-audit gap | **No** | **Open, lower priority** | No evidence of a precision problem found; a real gap in rigor, not urgent enough to block anything |
| Patent-derived breadth mining (Part 8) | **No** | **Open (explicitly deferred since Phase 5)** | Never attempted, explicitly out of scope through Phase 5e |
| Zymeworks scientific-presentation source | **No** | **Open (explicitly deferred, Phase 5d)** | Real page found, deferred for markup fragility |
| Candidate-to-platform attribution | **No** | **Open** | Tried, produced a real false positive (Phase 5e), needs a better mechanism than time allowed this phase |

**No item above requires a new acquisition source or entity-type/table
to eventually close** — every open item is either more materialization
depth, a mechanism enhancement, a root-cause investigation broader than
Phase 2's sample, or explicitly Phase 6/8's own future charge. That is
why nothing here blocks *starting* Phase 6. It is not, on its own,
evidence that breadth is *sufficient* — Gates 1, 2, and 3 are genuinely,
currently open, not merely procedurally pending.

## 8. Verdict

```
PROCEED_TO_PHASE6: YES
ACQUISITION_V1_FREEZE_STATUS: NOT_YET_READY_TO_FREEZE
```

Current evidence supports starting Phase 6 (the 14-day delta system) --
no identified gap requires a new acquisition source or entity type, and
Gate 5 cannot be evaluated any other way. Current evidence does **not**
support `READY_TO_FREEZE_ACQUISITION_V1`: Gate 1 (43.4% vs. 95%), Gate 2
(19/21, 2 gaps with undemonstrated causes), and Gate 3 (0/16 new-candidate
target resolution) are genuinely open, not merely deferred as
administrative follow-up. The correct sequencing is: build Phase 6, run
it through (at minimum) two controlled delta cycles as Gate 5 itself
requires, and only then re-evaluate all six gates together for a real
freeze verdict — re-opening scope discussion mid-Phase-6 would be scope
creep the same way skipping this distinction now would be premature
closure.

This is a recommendation for the reviewer's own APPROVE/REQUEST_CHANGES
decision, per this project's standing governance model — not a
unilateral declaration in either direction.

## Reproduction

```bash
python3 tools/breadth/broad_recall.py \
    --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
    --data-dir DATA \
    --output reports/validation/breadth
```
