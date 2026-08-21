# Conference Abstract Corpus (BREADTH_PLAN.md Phase 4)

## Acquisition mechanism

NOT a live scrape of AACR/ASCO/Crossref -- this job reuses an already-materialized
local historical corpus built by a separate, external workflow
(REPOS/aacr-abstract-workflow, outside this repo), per Part 6's explicit
instruction to search for reusable historical corpora before any new
download. That workflow queried Crossref for each meeting's own DOI prefix
(AACR: `10.1158/1538-7445.am<year>-*`; ASCO: `10.1200/jco.<year>.*.{15,16}_suppl.*`)
and applied an ADC-keyword regex filter -- see
`configs/conference_abstract_corpus_queries.yaml` for the exact, verified
filter text per source, including each filter's disclosed scope limitation
(AACR's is title-only; ASCO's is title+abstract). This job's own
contribution is making that corpus legible to this repo's three-table
acquisition architecture (content-version manifest, discovery ledger,
attempts ledger) and re-runnable idempotently.

Corpus root this run: `/Volumes/Stelligen_SSD/Stelligen/Zhixins-KB/2.Biotech/5.ADC_Expert`.

## Known scope limitations (disclosed, not silently narrowed)

**AACR's filter is TITLE-ONLY** (narrower than this repo's own PubMed/Europe
PMC title+abstract queries) -- an AACR abstract that discusses an ADC
substantively without the matched terms in its own title is not in this
corpus at all, and this job cannot recover it; the filtering already
happened upstream, outside this job's control.

**AACR 2026's schema diverges from 2016-2025**: 11 AACR
year-files were found; the 2026 file was built by PDF-extracting the AACR
2026 proceedings text ahead of Crossref indexing, so 307 of this
run's 2456 candidate records have no `doi` at all (identified
instead by `f"aacr:{year}:{abstract_number}"`) and no
`publication_or_release_date` -- not fabricated.

**No target/payload/linker/candidate extraction from this corpus's text is
done here** (Part 16 scope discipline) -- this job's only claim is "this
abstract, with this text, was findable in this historical corpus by this
query." Feeding this corpus's title/abstract text into
`tools/breadth/candidate_queue.py`'s USAN/INN suffix matching is deferred to
Phase 5.

## Candidate provenance this run

1286 AACR abstracts across 11 year-files,
1170 ASCO abstracts across 11 year-files.
2149 of 2456 candidate records have a doi; 2386 have abstract
text materialized (the rest have a title only -- disclosed, not treated as
equivalent evidence depth).

## Materialization this run

2456 unique candidate records. 0 new-or-changed (content_hash
recomputed and compared against the checkpoint on EVERY run -- cheap here since the
record is already loaded from a local file read, unlike a network-fetch job, so
there is no "trust a prior success without rechecking" fast-skip path),
2456 unchanged this run.

**This run's outcomes:** 0 success (newly materialized),
2456 skipped_unchanged -- 2456 total
attempted/fast-skipped outcomes (must equal the sum of these two; this job
has no network fetch step, so there is no `failed`/`not_available` outcome
class the way network-dependent jobs have).

## Sample materialized artifacts

- AACR 2016 1194 (10.1158/1538-7445.am2016-1194, version 1): Abstract 1194: Discovery and preclinical development of a highly potent NaPi2b-targeted antibody-dru
- AACR 2016 1195 (10.1158/1538-7445.am2016-1195, version 1): Abstract 1195: SGN-CD352A: A novel humanized anti-CD352 antibody-drug conjugate for the treatment of
- AACR 2016 1197 (10.1158/1538-7445.am2016-1197, version 1): Abstract 1197: Outstanding preclinical efficacy of a novel maytansinoid-antibody-drug conjugate targ
- AACR 2016 1198 (10.1158/1538-7445.am2016-1198, version 1): Abstract 1198: Characterization of a novel maytansinoid-antibody-drug conjugate targeting LAMP1 expr
- AACR 2016 1201 (10.1158/1538-7445.am2016-1201, version 1): Abstract 1201: Anti-B7-H3 antibody-drug conjugates as potential therapeutics for solid cancer
- AACR 2016 1207 (10.1158/1538-7445.am2016-1207, version 1): Abstract 1207: Preclinical development of 2nd generation HER2-directed antibody-drug conjugates
- AACR 2016 1211 (10.1158/1538-7445.am2016-1211, version 1): Abstract 1211: Killing cancer one cell at a time: Development and characterization of a novel antibo
- AACR 2016 1214 (10.1158/1538-7445.am2016-1214, version 1): Abstract 1214: Development of anti-5T4 antibody-drug conjugates, ZV05-ADCs for targeted cancer thera
- AACR 2016 1217 (10.1158/1538-7445.am2016-1217, version 1): Abstract 1217: Preclinical evaluation of a next-generation, EGFR targeting ADC that promotes regress
- AACR 2016 1220 (10.1158/1538-7445.am2016-1220, version 1): Abstract 1220: A novel PTK7-targeted antibody-drug conjugate eliminates tumor-initiating cells and i
- AACR 2016 1285 (10.1158/1538-7445.am2016-1285, version 1): Abstract 1285: Tumor associated macrophages can process antibody-drug conjugates and contribute to a
- AACR 2016 2082 (10.1158/1538-7445.am2016-2082, version 1): Abstract 2082: Fc-FcγR interaction impacts the clearance and antitumor activity of antibody-drug con
- AACR 2016 2113 (10.1158/1538-7445.am2016-2113, version 1): Abstract 2113: Caveolae-mediated endocytosis as a novel mechanism of resistance to T-DM1 ADC
- AACR 2016 2690 (10.1158/1538-7445.am2016-2690, version 1): Abstract 2690: A novel antibody-drug conjugate directed to the ALK receptor tyrosine kinase demonstr
- AACR 2016 2956 (10.1158/1538-7445.am2016-2956, version 1): Abstract 2956: Optimal PEGylation of an auristatin linker provides ADCs with improved pharmacologica
- AACR 2016 2959 (10.1158/1538-7445.am2016-2959, version 1): Abstract 2959: Peptide-linked indolino-benzodiazepine DNA-alkylating agents for use in antibody-drug
- AACR 2016 2960 (10.1158/1538-7445.am2016-2960, version 1): Abstract 2960: Potent <i>in vivo</i> activity of site-specific indolino-benzodiazepine antibody-drug
- AACR 2016 2964 (10.1158/1538-7445.am2016-2964, version 1): Abstract 2964: An anti-CD20 extracellular antibody-drug conjugate for the treatment of B-cell malign
- AACR 2016 2965 (10.1158/1538-7445.am2016-2965, version 1): Abstract 2965: <i>In vitro</i> and <i>in vivo</i> activity of a site-specific SeriMab antibody-drug 
- AACR 2016 2966 (10.1158/1538-7445.am2016-2966, version 1): Abstract 2966: Preclinical combinations of the antibody-drug conjugate SGN-LIV1A with chemotherapies

## Reproduction command

```bash
python -m adc_acquisition conference_abstract_corpus --output DATA
```
