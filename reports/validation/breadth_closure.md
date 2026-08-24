# Breadth-Layer Closure Audit — Phase 1–5e vs. the Six Freeze Gates

Per `reports/validation/BREADTH_PLAN.md` Phase 7 ("Final breadth benchmark
+ freeze decision") and the reviewer's explicit instruction after PR #27's
APPROVE: put the cumulative Phase 1–5e results against all six acceptance
gates (`BREADTH_PLAN.md` Section 4), decide which gaps are v1 blockers vs.
explicit v1.x deferrals, and use that to inform whether Phase 6 (the
14-day delta system) should start next.

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

**Recommendation:** this gate is a genuine, real, disclosed gap — but it
is a **depth** problem (materialize more of what's already discovered),
not a **breadth** problem (add a new source/capability). Phase 6's own
periodic re-runs are the natural mechanism to keep closing it over time;
treating "95%" as a precondition for Phase 6 would be circular, since
Phase 6 is part of how it gets closed further.

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
  match only, in `conference_abstract_corpus` + `pubmed`). This is a
  genuinely recent approval (FDA, October 2025) — the gap is plausibly
  just recency (evidence hasn't accumulated/materialized yet for a
  ~10-month-old approval), not a modality or query issue. A real,
  disclosed, likely time-resolving gap.

**Recommendation:** effectively 20/21 (95.2%) once Cetuximab sarotalocan
is treated as a probable ontology exclusion (pending an explicit
decision) — Gate 2 is close to met and the one clear residual gap
(Trastuzumab botidotin) is the kind Phase 6's periodic re-runs should
close on their own as more literature accumulates.

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
an answer. Either way: **target resolution for new candidates is a real,
disclosed, unclosed gap** — recommend v1.x, since closing it needs a new
target-identification mechanism (a capability gap), not more of what
already exists.

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

## 7. V1-blocker vs. v1.x-defer classification

| Gap | Classification | Why |
|---|---|---|
| Gate 1 shortfall (43.4% vs. 95%) | **Defer to v1.x**, closed incrementally by Phase 6 | Diagnosed as materialization-depth (esp. WIPO/USPTO 6.7% materialized), not a missing capability or confirmed query defect |
| Gate 2's 2 unresolved Approved assets | **Defer to v1.x** | 1 plausible ontology exclusion (photoimmunotherapy conjugate), 1 likely recency (Oct 2025 approval) |
| Gate 3's target-resolution gap for new candidates | **Defer to v1.x** | Requires a new target-identification mechanism (capability gap), honestly disclosed since Phase 3 |
| Gate 4's candidate-novelty overstatement | **Already corrected here, no further action needed** | Reframing only — the entities themselves are still correctly VALIDATED, just not "beyond NAR" |
| Gate 5 (delta system) | **Not a gap — Phase 6's own deliverable** | Cannot be evaluated before Phase 6 exists by definition |
| Gate 6's independent-audit gap | **Defer to v1.x**, lightweight | No evidence of a precision problem; nice-to-have rigor, not urgent |
| Patent-derived breadth mining (BREADTH_PLAN Part 8) | **Defer to v1.x** (already explicitly deferred every phase since Phase 5) | Never attempted; explicitly out of scope through Phase 5e |
| Zymeworks scientific-presentation source | **Defer to v1.x** (already explicitly deferred, Phase 5d) | Real page found, deferred for markup fragility |
| Candidate-to-platform attribution | **Defer to v1.x** | Tried, produced a real false positive (Phase 5e), needs a better mechanism (usage-verb pattern matching) than time allowed this phase |

**No item on this list requires a new acquisition source or a new
entity-type/table to close** — every deferred gap is either (a) more
depth on an existing source, (b) a mechanism enhancement to existing
extraction, or (c) explicitly Phase 6/8's own charge already. This is
the concrete basis for the recommendation below.

## 8. Recommendation

The breadth-layer architecture (source set, entity-type schema, ontology
splits, evidence-tier ladder) is now broad and mature enough to support
Phase 6's incremental delta system — no gap identified above requires a
NEW source or entity type to close, only more depth on what already
exists or mechanisms Phase 6/8 already own. Recommend: proceed to Phase
6 (`update_breadth` orchestration), treating Gate 1/2's residual
recall gaps as things Phase 6's own periodic re-runs will keep closing,
not preconditions blocking its start.

This is a recommendation for the reviewer's own APPROVE/REQUEST_CHANGES
decision, per this project's standing governance model — not a
unilateral `READY_TO_FREEZE_ACQUISITION_V1` declaration.

## Reproduction

```bash
python3 tools/breadth/broad_recall.py \
    --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
    --data-dir DATA \
    --output reports/validation/breadth
```
