# Company registry expansion (V1.1 source-coverage expansion, item #36)

## Why

`configs/company_registry.yaml` had only 8 curated companies (all from the
initial Job 05/SEC/Job 11/Job 12 build-out). The reviewer's own
`DATA/raw/company_list.md` (P0/P1-prioritized, ~92 companies with
representative ADC assets) identified this as a structural blind spot: the
master catalog (`DATA/catalog/adc_asset_universe.tsv`) already names well
over 100 distinct Phase1+ sponsor companies, most of which had no
`company_registry.yaml` entry at all and therefore were never in scope for
the company-pipeline/press-release/scientific-presentations acquisition
jobs.

## What changed

**93 new company entries** added to `configs/company_registry.yaml`
(101 total, up from 8), covering:
- Western big pharma with ADC programs (Astellas, AstraZeneca, BMS,
  Daiichi Sankyo, Roche, Genentech, Gilead, GSK, Merck & Co., Sanofi,
  Takeda, Eli Lilly, J&J, Genmab, BioNTech, Merck KGaA/EMD Serono, Eisai)
- M&A-adjacent entities with structural `parent_company_id` links:
  ProfoundBio -> Genmab, Ambrx -> J&J, Araris -> Taiho Oncology (in
  addition to the pre-existing Seagen -> Pfizer, ImmunoGen -> AbbVie,
  Mersana -> Day One links)
- ~20 Chinese ADC originators/biotechs (Hengrui, Kelun-Biotech, Hansoh,
  Innovent, CSPC, RemeGen, Akeso, Mabwell, Alphamab, Junshi, CStone,
  Harbour BioMed, and more)
- ~40 Western small/mid-cap ADC biotechs (MacroGenics, CytomX, Pyxis
  Oncology, ALX Oncology, OBI Pharma, Byondis, TORL BioTherapeutics, and
  more)

Every entry was live-verified via WebFetch against the company's own
official domain, following this file's existing discipline: never guess a
URL, write `NONE_FOUND`/leave `null` when unconfirmed, and disclose access
limitations (bot-protection timeouts, expired/self-signed TLS certs,
Cloudflare challenges) explicitly in each entry's `notes` rather than
silently working around or ignoring them.

**36 aliases added** to existing/new entries so the exact-normalized-name
matching this repo already uses (`registered_identifier_index`, reused
from `compare_nar_adcdb.normalize_name`, deliberately never fuzzy) can
actually resolve catalog sponsor-name variants (e.g. "Bristol Myers
Squibb Co" vs. the registry's "Bristol-Myers Squibb Company") to the
right registry entry.

**Bug fix**: `build_company_universe_rows()` in
`tools/validation/company_registry_gap_analysis.py` only matched catalog
mentions against a company's `canonical_name`, silently ignoring
`aliases` -- inconsistent with `registered_identifier_index()` (used
elsewhere in the same file), whose own docstring says matching should be
against "every registered company's own canonical_name + aliases." Found
while adding the 36 aliases above (added aliases had no effect on the
company-universe report until this was fixed). Now matches via every
identifier a company owns and aggregates counts/examples/stages across
any mention-name variant. Two new regression tests added.

## Round-1 fix: audit tool was overclaiming "active ADC company"

The reviewer flagged that `build_company_universe_rows()`'s
`UNREGISTERED_ACTIVE_ADC_COMPANY` status (and its `highest_active_stage`/
`active_adc_count` fields) asserted more than the underlying data
supports: the master catalog's `company` field is a broad
associated-company field, not checked against `development_status` and
not distinguishing originator / licensee / manufacturer / CMO / historical
company from an active current developer. Live output proved this wasn't
theoretical -- CDMO/manufacturing entities (BSP Pharmaceuticals SpA,
Baxter Oncology GmbH) and long-terminated-portfolio companies (Agensys,
Stemcentrx, MedImmune) all appeared indistinguishable from a genuine
active ADC developer, which would produce a false "new active company,
add to registry" signal in a future cadence run.

Fixed by renaming (no corporate-role resolution attempted, no re-research
of the 114 remaining gaps, no registry entries removed):
- `UNREGISTERED_ACTIVE_ADC_COMPANY` -> `UNREGISTERED_PHASE1_PLUS_COMPANY_MENTION`
- `highest_active_stage` -> `highest_phase1_plus_stage_observed`
- `active_adc_count` -> `phase1_plus_asset_mention_count`

and updating `COMPANY_REGISTRY_GAP.md`'s own language + adding an explicit
caveat paragraph to both the report and the module docstring: this audit
is a high-recall candidate list for human registry review, not proof that
every listed entity is a current developer/sponsor.

## Result (measured by genuinely-new-assets-found, not raw record counts)

Re-running `tools/validation/company_registry_gap_analysis.py
--run-date 2026-08-31`:

| | Before | After |
|---|---|---|
| Companies registered | 8 | 101 |
| Distinct company names associated with Phase1+ catalog rows, matched | 7 | 94 |
| `UNREGISTERED_PHASE1_PLUS_COMPANY_MENTION` | 201 | 114 |

87 previously-unregistered, catalog-associated company names are now
matched against the registry and in scope for the company-pipeline/
press-release/scientific-presentations acquisition jobs -- some fraction
of the remaining 114 are expected to be manufacturers/historical
companies rather than registry-worthy developers, per the caveat above;
this PR does not attempt to sort that out.

## Known gaps (disclosed, not silently dropped)

- **PrimeLink BioTherapeutics**: no discoverable web presence via any
  method tried (WebSearch, direct domain guesses, search-engine
  fallbacks). Registered with `official_domain: null` so
  `REGISTERED_INCOMPLETE` status surfaces it for a future retry, rather
  than being silently excluded from tracking.
- **Chengdu Kanghong Pharmaceutical**: `kanghong.com` was unreachable via
  7+ distinct fetch methods (direct HTTPS/HTTP, web.archive.org,
  reader-proxy). Ticker (SZSE:002773) is third-party-sourced only.
- **Mythic Therapeutics**: verified to have executed a General Assignment
  for the Benefit of Creditors (2025-11-21) and is liquidating all
  assets -- registered with `active: false` rather than removed, so its
  historical presence in the catalog stays explainable.
- **Tubulis -> Gilead** and **Day One -> Servier**: acquisitions
  announced but NOT confirmed closed as of this research round (Tubulis)
  or the acquirer is out of this round's research scope (Servier) --
  left as independently-tracked, active entries (`parent_company_id:
  null`) rather than asserting a completed acquisition that wasn't
  verified.
- A number of well-known SEC-reporting companies (Astellas, AstraZeneca,
  BMS, Gilead, GSK, Merck & Co., Sanofi, Takeda, MacroGenics, and others)
  still show `ciks: []` -- CIKs were only added when a research agent's
  own notes explicitly confirmed a specific number; NOT backfilled from
  outside knowledge. A future incremental pass should re-verify these
  live via EDGAR.
- `press_release_template`/`presentations_template` are left `null` for
  every new entry -- template identification requires deeper per-company
  HTML-structure verification not attempted in this research round (see
  this file's existing comment for the small number of known reused
  templates). Live-verified this is non-fatal: `company_press_release`/
  `company_scientific_presentations` log a clear `UNKNOWN_TEMPLATE`
  discovery failure and continue, rather than crashing.

## Live verification

Ran `company_pipeline` for real against a diverse sample (`genmab`,
`hengrui`, `harbour_biomed`, `macrogenics`, `roche`) -- all 5 succeeded
with `records_downloaded=1, records_failed=0`. Ran `company_press_release`
and `company_scientific_presentations` against `genmab`/`macrogenics` --
both correctly no-op with a logged `UNKNOWN_TEMPLATE` discovery failure
(expected, since no template was identified this round) rather than
erroring.

Full test suite: 622 passed.
