# China CDE drug clinical trial registry acquisition (V1.1 #36A)

## Why

WHO ICTRP (this repo's other new 2026-08 source) aggregates ChiCTR, but
ChiCTR is a SEPARATE registry from CDE's own mandatory drug-trial
disclosure platform (chinadrugtrials.org.cn) -- confirmed live, disjoint
ID namespaces (ChiCTR: `ChiCTR2600000001`; CDE: `CTR20262727`). ADC
development is heavily China-weighted right now, and an asset can enter
Phase 1/2, priority review, or approval in China well before it appears
on ClinicalTrials.gov or at a Western conference. This closes that
structural blind spot.

## Access-model research (live, before writing any code)

chinadrugtrials.org.cn's functional pages (search form, results listing,
disclaimer) are a client-side-rendered SPA that returns empty content to
a plain HTTP fetch -- this project's tools cannot read them directly. No
`robots.txt` exists on the domain (404, not a Disallow list). The
platform's own Disclaimer page could not be read from this environment.
**AUTOMATION PERMISSION STATUS: UNKNOWN** -- neither confirmed-permitted
nor confirmed-prohibited. `nmpa.gov.cn` itself was found completely
unreachable from this environment (connection-level block) and is out of
scope entirely for this round.

Given that ambiguity, this job makes **zero network requests** to
chinadrugtrials.org.cn -- identical in spirit to this repo's WHO ICTRP
job, it reads a manually-downloaded search-results export file that a
human produces via the results page's own "下载" (download) button.

## What the export actually is

Despite the `.xls` extension, the downloaded file is Microsoft's legacy
SpreadsheetML XML format, not a real binary Excel file -- confirmed by
inspecting 3 real files the reviewer downloaded on 2026-08-31 (41 total
rows across two search terms). 6 columns: registration_number,
trial_status, drug_name, indication, public_title (+ a display sequence
number, dropped). No hyperlink/internal-UUID data exists in the export at
all -- applicant/sponsor, phase, enrollment, and a stable detail-page URL
all live only on a per-trial detail page not included in this export.

## Scope: acquisition foundation only (no detail-page fetching)

This round (#36A) materializes only the 6 list-page fields, keyed on
CDE's own `registration_number` (e.g. `CTR20262727`) as the stable
identity -- never the internal detail-page UUID. Detail-page fields
(applicant, phase, enrollment) require a live page visit per record,
which this round deliberately does not do given the UNKNOWN
automation-permission status above. A follow-up increment (#36B) can add
detail-page materialization once terms/access are clearer, keyed off the
same registration_number.

## Disclosed finding: neither search term is precise

Two confirmed search terms were run: a bare `"ADC"` acronym search and a
targeted `"抗体药物偶联物"` (Chinese for "antibody-drug conjugate") search.
Inspecting all 41 real rows found **both** produced substantial false
positives:
- Bare `"ADC"`: matches an internal drug-code numbering prefix used by
  some sponsor(s) for unrelated products (`ADC189`/`ADC118`/`ADC308` --
  an influenza antiviral, an HIV drug, an endometriosis drug) and the
  unrelated `AADC` (enzyme-deficiency) acronym.
- Targeted `"抗体药物偶联物"`: **also** returned results with no plausible
  ADC connection at all -- `盐酸乙胺丁醇片` (ethambutol, an anti-
  tuberculosis drug) and an HIV combination pill. This is NOT explainable
  by acronym ambiguity and indicates chinadrugtrials.org.cn's search
  matches a field not visible in list-page columns (most likely a
  protocol/reference number, not drug content).

Both queries' full result sets are materialized as-is, per this repo's
"acquire broadly, filter downstream" principle -- see
`configs/china_drug_trials_queries.yaml`'s own file-level comment for the
full writeup. Recommended improved strategy for a future round: search by
known ADC asset names/development codes and known ADC company/applicant
names, rather than a single broad term.

## Result: registry-ID namespace coverage (not an asset-novelty claim)

41 new China-CDE registry records acquired from a previously uncovered
registry namespace (20 + 20 + 1 across 3 downloaded files, deduplicated).
Measured via `_overlap_with_existing_sources` in `jobs/china_drug_trials/
report.py`: near-zero expected overlap with `clinicaltrials.parquet`/
`who_ictrp.parquet` source_record_ids (different ID namespaces) -- any
nonzero overlap would itself be a surprising finding worth investigating.

**This is a registry-ID coverage measurement, not an ADC-asset-novelty
claim** -- zero source_record_id overlap only proves these records came
from a namespace this repo didn't already track, not that each record's
underlying drug is a new ADC asset (that requires a real identity
crosswalk against `DATA/catalog/adc_asset_universe.tsv`, not attempted
this round). ADC-relevant records observed in the export include RC48-ADC
(disitamab vedotin, multiple trials across bladder/gastric/breast/NSCLC),
F0002-ADC, loncastuximab tesirine (a drug this repo already tracks via
ADC Therapeutics -- reported here only as an observed CDE registration,
not a new asset), ATG-022, STI-6129, and SSGJ-612.

## Per-export-file query attribution (reusing the WHO ICTRP round-1 fix)

Unlike WHO ICTRP's own default download filename (which self-encodes a
date), CDE's downloaded file has no project-meaningful default name -- a
human must name each file and register it, alongside its actual export
date, under whichever query produced it, in
`configs/china_drug_trials_queries.yaml`'s per-query `exports: [{filename,
export_date}, ...]` list. Every `*.xls` file present under `--corpus-dir`
that isn't registered is a hard `RuntimeError`, never a silent guess --
directly reusing the exact mechanism (`_load_export_filename_query_map`/
`_query_for`) just built for WHO ICTRP's own round-1 fix, generalized
from date-keyed to filename-keyed.

**Round-1 fix #1 (reviewer-flagged, this PR)**: `chinadrugtrials-Aug31-3.xls`'s
single record was originally attributed to `CHINADRUGTRIALS_002` by
inferring its search provenance FROM THE RECORD'S OWN CONTENT (its title
names "TROP2 抗体药物偶联物") -- a direct violation of this file's own
"never re-derive or guess `query_text`" rule. Fixed: this file now gets
its own `CHINADRUGTRIALS_LEGACY_UNKNOWN_001` query
(`query_text: "UNKNOWN/UNVERIFIED"`), matching the precedent WHO ICTRP's
own `WHO_ICTRP_001` legacy entry already established.

**Round-1 fix #2 (reviewer-flagged, this PR)**: the discovery ledger was
built from the content-deduped `trial_by_regnum` dict, so a registration
number discovered via TWO DIFFERENT queries' export files would silently
collapse to only the WINNING file's query in the discovery ledger --
erasing the other query's own real discovery of that record. Fixed:
`_load_all_trials` now also returns `observations`, a list of every
`(registration_number, export_filename)` pair actually seen (deduped only
within a single file, never across files/queries), and the discovery
ledger is built from that -- content dedup (one current manifest snapshot
per registration number) and discovery-ledger completeness (every real
observation retained) are now correctly separate concerns. Two new
regression tests cover this exact scenario plus the within-file-duplicate
non-inflation case.

## Tests

31 new tests (8 parser + 23 job), including a regression test mirroring
WHO ICTRP's content-hash lesson (a registration number re-downloaded
under a new filename/export_date with unchanged real content stays
`skipped_unchanged`, never spuriously version-bumped) and the two round-1
regression tests for the discovery-ledger fix described above.

Full suite: 645 passed.

## Live verification

Ran the real job against the 3 actual downloaded files
(`DATA/raw/chinadrugtrials/`, gitignored) -- 41/41 materialized
successfully, `records_failed=0` (no network fetch step at all this
round, so no failure class is even possible). `DATA/manifests/
china_drug_trials*.parquet` and `reports/acquisition/china_drug_trials.md`
committed with this PR, matching the WHO ICTRP precedent of committing a
real first-run manifest.
