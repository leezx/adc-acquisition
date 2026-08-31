# WHO ICTRP (source-coverage expansion)

## Acquisition mechanism

NOT a live query against WHO ICTRP -- this job reads a MANUALLY exported
`ICTRP-Results-YYYYMMDD.xml` file (WHO's own Search Portal "Export results
to XML" button, https://trialsearch.who.int/) dropped into `--corpus-dir`.
Real, automated/scheduled ("crawling") access to WHO ICTRP requires WHO-
issued credentials (email ictrpinfo@who.int) -- until that access exists,
this job makes zero network requests to WHO. See this job's own module
docstring for the full access-model writeup and
`configs/who_ictrp_queries.yaml` for the EXACT search terms/filters used
to produce the export file(s) this run read (verbatim, supplied by the
human who ran the search -- this job cannot re-derive it).

Corpus dir this run: `DATA/raw/WHO_ICTRP` (1 export file(s) read).

## Why this source: real, measured global-registry coverage this run

Of 292 distinct trials in the export(s):

- ClinicalTrials.gov: 203
- EU Clinical Trials Register: 33
- Clinical Trials Information System: 19
- JPRN: 18
- ChiCTR: 5
- CTRI: 4
- NL-OMON: 4
- ANZCTR: 2
- ISRCTN: 2
- REPEC: 1
- REBEC: 1

**89 of 292 trials (30%) come from a
`Source_Register` OTHER than ClinicalTrials.gov** -- genuinely new global
trial coverage Job 03 (ClinicalTrials.gov) structurally cannot reach on
its own, this repo's exact motivating case for adding this source.

Of the 203 ClinicalTrials.gov-sourced trials in this export
(TrialID == NCT number for these), 200 are ALREADY in our own Job 03
`clinicaltrials.parquet` (expected/healthy overlap, not double-counted as
new source coverage), and 3 are NOT yet in our own Job
03 manifest -- worth investigating as a possible Job 03 recall gap in a
future round, not this job's own scope.

## Known, disclosed limitations (not silently narrowed)

**Manual export, not live/scheduled acquisition.** This job's own
`--since`/`--until`/`--resume` flags are no-ops beyond default behavior --
"freshness" is entirely a function of how recently a human re-ran the
export, not this job's own cadence. See module docstring for the interim-
access-model rationale.

**`other_records` is a flag, not a resolved cross-reference.** WHO ICTRP
marks a trial `other_records=Yes` when it believes a linked/duplicate
registration exists in another registry, but the export does not carry
that OTHER registry's own TrialID -- this job cannot deduplicate across
those linked registrations, only record the flag as-is (materialized in
the `other_records` column).

**No target/payload/linker/candidate extraction from this source yet**
(same acquisition/extraction boundary every other job in this repo draws
first) -- deferred to a follow-up increment, once this job's own
materialization is reviewed and stable.

## Materialization this run

292 unique candidate trials (deduplicated by WHO ICTRP's own
cross-registry TrialID; a trial appearing in more than one dated export
file keeps the MOST RECENTLY DATED file's version). 0
new-or-changed, 292 unchanged this run.

**This run's outcomes:** 0 success (newly materialized),
292 skipped_unchanged -- 292 total
attempted/fast-skipped outcomes (must equal the sum of these two; this job
has no network fetch step, so there is no `failed`/`not_available` outcome
class the way network-dependent jobs have).

## Sample materialized trials

- ANZCTR ACTRN12620000592943 (version 1): Phase I Dose Finding Study in Patients with HER2-Positive Advanced Solid Tumors
- ANZCTR ACTRN12624000918527 (version 1): Fluorodeoxyglucose (FDG) and human epidermal growth factor receptor 2 (HER2) positron emission tomog
- CTRI CTRI/2022/05/042713 (version 1): Study to Investigate Alternative Dosing Regimens of Belantamab Mafodotin in 
Participants with Relap
- CTRI CTRI/2023/04/051319 (version 1): Safety and Effectiveness assessment of Trastuzumab emtansine of Zydus Lifesciences Ltd for the treat
- CTRI CTRI/2024/07/070945 (version 1): Study to Assess the Safety of Trastuzumab Deruxtecan in  Indian Patients with Unresectable or Metast
- CTRI CTRI/2026/06/113048 (version 1): Efficacy and safety assessment of iza-bren, a bi-specific antibody-drug conjugate  versus treatment 
- ChiCTR ChiCTR2400083481 (version 1): Clinical trial of a novel antibody-drug conjugate (ADC) in combination with low-dose apatinib for th
- ChiCTR ChiCTR2500106965 (version 1): A study on the treatment of high-risk non-muscle-invasive bladder cancer with antibody-drug conjugat
- ChiCTR ChiCTR2600120399 (version 1): An Open-label, Multi-center Phase I Study to Evaluate the Safety, Tolerability, Pharmacokinetics, Im
- ChiCTR ChiCTR2600121898 (version 1): A prospective, multicenter clinical study of Herombopag in the treatment of thrombocytopenia caused 
- ChiCTR ChiCTR2600124881 (version 1): Trastuzumab Rezetecan Antibody-Drug Conjugate Combined with Retlirafusp a in Patients with HER2-Posi
- Clinical Trials Information System CTIS2022-500508-23-00 (version 1): Anti-CEACAM5 ADC M9140 in Advanced Solid Tumors
- Clinical Trials Information System CTIS2023-504630-22-00 (version 1): Clinical Study of Antibody-Drug Conjugate MYTX-011 in Subjects With Non-Small Cell Lung Cancer
- Clinical Trials Information System CTIS2023-504898-20-00 (version 1): A multicenter, open label, two cohort, single arm, phase II study to evaluate the efficacy and safet
- Clinical Trials Information System CTIS2023-507781-13-00 (version 1): Safety, pharmacokinetics, and preliminary efficacy of BYON4413 in acute myeloid 
leukemia and myelod
- Clinical Trials Information System CTIS2023-510390-33-00 (version 1): Sacituzumab Govitecan in primary HER2-negative breast cancer (SASCIA)
- Clinical Trials Information System CTIS2024-511238-11-00 (version 1): A study to characterise the safety, tolerability and efficacy of LY4170156 in subjects with advanced
- Clinical Trials Information System CTIS2024-512368-79-00 (version 1): I-DXd in Patients With Pretreated Extensive-Stage Small Cell Lung Cancer (ES-SCLC)
- Clinical Trials Information System CTIS2024-513687-26-00 (version 1): Anti-GD2 ADC M3554 in Advanced Solid Tumors
- Clinical Trials Information System CTIS2024-514746-36-00 (version 1): Phase 1 dose-escalation trial of OMTX705, an anti-fibroblast activation protein antibody-drug conjug

## Reproduction command

```bash
python -m adc_acquisition who_ictrp --corpus-dir DATA/raw/WHO_ICTRP --output DATA
```
