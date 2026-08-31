# China CDE / chinadrugtrials.org.cn (source-coverage expansion)

## Acquisition mechanism

NOT a live query against chinadrugtrials.org.cn -- this job reads a
MANUALLY downloaded search-results export file (the results page's own
"下载" button) dropped into `--corpus-dir`. AUTOMATION PERMISSION STATUS
for this domain is UNKNOWN (no robots.txt exists; the platform's own
Disclaimer page could not be read from this environment) -- until that is
resolved, this job makes zero network requests to chinadrugtrials.org.cn.
See this job's own module docstring for the full access-model writeup and
`configs/china_drug_trials_queries.yaml` for the EXACT search terms used
to produce each export file this run read (verbatim, supplied by the
human who ran each search).

Corpus dir this run: `DATA/raw/chinadrugtrials` (3 export file(s) read).

## Records by query

- CHINADRUGTRIALS_001: 20
- CHINADRUGTRIALS_002: 20
- CHINADRUGTRIALS_LEGACY_UNKNOWN_001: 1

**Disclosed finding -- neither query is confirmed precise**: the bare
"ADC" query matches an internal drug-code numbering prefix used for
unrelated products ("ADC189"/"ADC118"/"ADC308" -- an influenza antiviral,
an HIV drug, an endometriosis drug) and the unrelated "AADC" acronym
(expected). More surprisingly, the TARGETED "抗体药物偶联物" query ALSO
returned results with no plausible ADC connection at all (ethambutol, an
anti-tuberculosis drug; an HIV combination pill) -- not explainable by
acronym ambiguity, suggesting the site's search matches a field not
visible in list-page columns (likely a protocol/reference number, not
drug content). Both queries' full result sets are kept as-is under this
repo's "acquire broadly, filter downstream" principle -- see
`configs/china_drug_trials_queries.yaml`'s own file-level comment for the
full writeup and a recommended improved search strategy for a future
round (known ADC asset names/development codes and known ADC company/
applicant names, rather than a single broad term).

## Registry-ID namespace overlap diagnostic (NOT an asset-novelty metric)

41 new China-CDE registry records acquired from a previously
uncovered registry namespace this run:

- clinicaltrials: 0 of 41 registration numbers also appear there
- who_ictrp: 0 of 41 registration numbers also appear there

Near-zero overlap is EXPECTED: CDE's registration numbers live in a
completely different ID namespace from ClinicalTrials.gov's NCT numbers
and WHO ICTRP's own cross-registry TrialIDs (a ChiCTR-sourced WHO ICTRP
trial is a DIFFERENT Chinese registry from CDE's own mandatory drug-trial
disclosure platform) -- any nonzero overlap here would itself be a
surprising finding worth investigating, not routine double-counting.
**This measures registry-ID coverage only** -- it does NOT establish that
any given record's underlying drug is a genuinely new ADC asset (that
would require a real identity crosswalk against
`DATA/catalog/adc_asset_universe.tsv`, not attempted here; see
`_overlap_with_existing_sources`'s own docstring). ADC-relevant records
observed in this run's export include RC48-ADC, F0002-ADC, loncastuximab
tesirine, ATG-022, STI-6129, and SSGJ-612 -- reported as observed content,
not asserted as novel assets.

## Known, disclosed limitations (not silently narrowed)

**Manual export, not live/scheduled acquisition.** This job's own
`--since`/`--until`/`--resume` flags are no-ops beyond default behavior --
"freshness" is entirely a function of how recently a human re-ran the
download, not this job's own cadence. See module docstring for the
interim-access-model rationale.

**List-only fields, no detail-page data this round.** The search-results
export gives only 6 columns (registration_number, trial_status, drug_name,
indication, public_title) -- applicant/sponsor, phase, enrollment, and a
stable per-trial detail URL all live only on the detail page, which this
acquisition-only round does not fetch (see module docstring). A follow-up
increment can add detail-page materialization keyed off the SAME
registration_number identity established here.

**No target/payload/linker/candidate extraction from this source yet**
(same acquisition/extraction boundary every other job in this repo draws
first) -- deferred to a follow-up increment, once this job's own
materialization is reviewed and stable.

## Materialization this run

41 unique candidate trials (deduplicated by CDE's own
registration_number; a registration number appearing in more than one
downloaded export keeps the MOST RECENTLY DATED file's version).
41 new-or-changed, 0 unchanged this run.

**This run's outcomes:** 41 success (newly materialized),
0 skipped_unchanged -- 41 total
attempted/fast-skipped outcomes (must equal the sum of these two; this job
has no network fetch step, so there is no `failed`/`not_available` outcome
class the way network-dependent jobs have).

## Sample materialized trials

- CTR20160864 (进行中 招募完成, query=CHINADRUGTRIALS_001): 米诺膦酸片 -- 评价米诺膦酸片治疗绝经后妇女骨质疏松多中心临床试验
- CTR20171568 (进行中 招募中, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇片 -- 盐酸乙胺丁醇片人体生物等效性研究
- CTR20180438 (已完成, query=CHINADRUGTRIALS_001): 注射用重组人源化抗HER2单抗-MMAE偶联剂 -- RC48-ADC治疗HER2阳性局部晚期或转移性尿路上皮癌患者的II期临床研究
- CTR20180477 (已完成, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇片 -- 盐酸乙胺丁醇片在空腹条件下的人体生物等效性研究
- CTR20180492 (已完成, query=CHINADRUGTRIALS_001): 注射用重组人源化抗HER2单抗-MMAE偶联剂 -- RC48-ADC治疗HER2阳性局部晚期或转移性乳腺癌Ⅱ期和治疗HER2阳性存在肝转移的晚期乳腺癌Ⅲ期临床研究
- CTR20180844 (已完成, query=CHINADRUGTRIALS_001): 注射用重组人源化抗HER2单抗-MMAE偶联剂 -- RC48-ADC治疗HER2过表达局部晚期或转移性胃癌II期临床研究
- CTR20180866 (进行中 尚未招募, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇片 -- 盐酸乙胺丁醇片生物等效性试验
- CTR20181712 (已完成, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇片 -- 盐酸乙胺丁醇片空腹生物等效性试验
- CTR20182469 (已完成, query=CHINADRUGTRIALS_001): RC48-ADC -- RC48-ADC治疗HER2过表达局部晚期或转移性尿路上皮癌的II期临床研究
- CTR20190341 (进行中 招募中, query=CHINADRUGTRIALS_001): F0002-ADC -- F0002-ADC药物I期临床试验
- CTR20190414 (已完成, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇片 -- 盐酸乙胺丁醇片人体生物等效性试验
- CTR20190939 (已完成, query=CHINADRUGTRIALS_001): 注射用重组人源化抗HER2单抗-MMAE偶联剂 -- RC48-ADC治疗HER2表达或HER2突变的晚期NSCLC有效性及安全性的Ib期
- CTR20192057 (进行中 招募完成, query=CHINADRUGTRIALS_001): 注射用重组人源化抗HER2单抗-MMAE偶联剂（RC48-ADC） -- RC48-ADC单药用于至少一线化疗失败的HER2表达型晚期胆道癌的研究
- CTR20192596 (已完成, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇片 -- 盐酸乙胺丁醇片生物等效性试验
- CTR20192667 (进行中 招募完成, query=CHINADRUGTRIALS_001): 注射用重组人源化抗HER2单抗-MMAE偶联剂 -- RC48-ADC治疗HER2阴性尿路上皮癌患者的临床研究
- CTR20200700 (已完成, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇片 -- 盐酸乙胺丁醇片生物等效性试验
- CTR20201496 (进行中 招募完成, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇胶囊 -- 盐酸乙胺丁醇胶囊人体生物等效性预试验
- CTR20202133 (进行中 招募完成, query=CHINADRUGTRIALS_001): 盐酸乙胺丁醇胶囊 -- 盐酸乙胺丁醇胶囊人体生物等效性试验
- CTR20211724 (主动终止, query=CHINADRUGTRIALS_001): 注射用Loncastuximab tesirine -- 评价Loncastuximab Tesirine对复发或难治性弥漫性大B细胞淋巴瘤（DLBCL）患者有效性和安全性研究
- CTR20213319 (已完成, query=CHINADRUGTRIALS_001): ADC189片 -- ADC189 片在中国健康受试者中的安全性、耐受性、药代动力学特征及食物影响试验

## Reproduction command

```bash
python -m adc_acquisition china_drug_trials --corpus-dir DATA/raw/chinadrugtrials --output DATA
```
