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

## Result: genuinely new assets found (not raw record counts)

Real, confirmed ADCs surfaced despite the noisy search terms:
- **RC48-ADC** (disitamab vedotin) -- multiple trials across bladder,
  gastric, breast cancer, and NSCLC
- **F0002-ADC**
- **Loncastuximab tesirine** (already known via ADC Therapeutics, but now
  independently confirmed with its own China CDE registration)
- **ATG-022** (Claudin 18.2 ADC), **STI-6129**, **SSGJ-612**

Measured via `_overlap_with_existing_sources` in `jobs/china_drug_trials/
report.py`: near-zero expected overlap with `clinicaltrials.parquet`/
`who_ictrp.parquet` source_record_ids (different ID namespaces) -- any
nonzero overlap would itself be a surprising finding worth investigating.

41 registration numbers materialized this round (20 + 20 + 1 across 3
downloaded files, deduplicated).

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

## Tests

29 new tests (8 parser + 21 job), including a regression test mirroring
WHO ICTRP's content-hash lesson: a registration number re-downloaded
under a new filename/export_date with unchanged real content stays
`skipped_unchanged`, never spuriously version-bumped.

Full suite: 643 passed.

## Live verification

Ran the real job against the 3 actual downloaded files
(`DATA/raw/chinadrugtrials/`, gitignored) -- 41/41 materialized
successfully, `records_failed=0` (no network fetch step at all this
round, so no failure class is even possible). `DATA/manifests/
china_drug_trials*.parquet` and `reports/acquisition/china_drug_trials.md`
committed with this PR, matching the WHO ICTRP precedent of committing a
real first-run manifest.
