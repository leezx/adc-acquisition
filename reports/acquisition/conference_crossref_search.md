# Conference Crossref Search (live ESMO/ASH/EHA/SABCS discovery)

## Acquisition mechanism

LIVE Crossref `/works?` collection queries, one per (conference, query
term) pair, restricted to each conference's own journal ISSN -- see this
job's own module docstring and `configs/conference_crossref_search.yaml`
for why this is tractable despite Crossref's free-text search being
unusable for unrestricted whole-of-Crossref topic discovery (see
`configs/crossref_reconciliation_sources.yaml`).

Query terms this run (4): "antibody-drug conjugate", "antibody drug conjugate", "ADC", "ADCs"

Conferences searched:
- **ESMO**: Annals of Oncology (ISSN 0923-7534), signature=`no_issue_and_s_page`
- **ASH**: Blood (ISSN 0006-4971), signature=`issue_contains_supplement`
- **EHA**: HemaSphere (ISSN 2572-9241), signature=`issue_starts_with_s`
- **SABCS**: Cancer Research (ISSN 0008-5472, 1538-7445), signature=`doi_suffix_contains`(value='sabcs')

## Records by conference

- ASH: 772
- ESMO: 540
- SABCS: 111
- EHA: 64

## Conference-attribution signature rejections (NOT ADC-relevance filtering)

Container/ISSN match alone is not conference attribution -- these
candidates matched the journal + search term but were structurally
determined (via each conference's own deterministic signature) to be a
different document (a regular research article, or a different congress's
abstract sharing the same journal) and were excluded from this job's
scope entirely, not acquired-and-disclosed the way ADC-relevance
imprecision is handled elsewhere in this repo:

- ESMO: 57 candidates matched the ISSN/query search but failed the conference's own signature check
- ASH: 172 candidates matched the ISSN/query search but failed the conference's own signature check
- EHA: 142 candidates matched the ISSN/query search but failed the conference's own signature check
- SABCS: 5770 candidates matched the ISSN/query search but failed the conference's own signature check

## Disclosed finding -- most materialized titles don't contain a
## recognizable ADC term (precision, not just recall, is affected)

Title-only diagnostic (NOT a precision measurement -- see
`_ADC_TITLE_HINT_RE`'s own caveat in this job's report.py; a title missing
every listed term can still be substantively about ADCs): only
306 of 1487 (21%) of this run's materialized titles contain a recognizable
ADC-relevant term at all. This is the concrete, in-the-wild confirmation
of `configs/crossref_reconciliation_sources.yaml`'s own documented warning
that Crossref's `query.bibliographic` is relevance-ranked, NOT a
phrase/boolean search -- even restricted to one journal's ISSN, a query
like "antibody-drug conjugate" can rank a work highly for loosely matching
"antibody" or "drug" alone, especially in a large single-journal
collection like Blood's own ASH Annual Meeting supplement. Per this
repo's "acquire broadly, filter downstream" principle (also applied to
China CDE's own two disclosed-imprecise search terms), the full result
set is still materialized as-is -- relevance filtering is left to a
downstream consumer, not silently narrowed here.

## Known, disclosed limitations (not silently narrowed)

**Relevance-ranked search, not phrase/boolean.** Even within one
ISSN-restricted journal collection, Crossref's `query.bibliographic` does
not guarantee exhaustive recall of every genuinely ADC-relevant abstract
in that journal -- the same disclosed recall-ceiling shape as this repo's
existing ASCO Stage-1 candidate-fetch limitation
(`configs/conference_abstract_corpus_queries.yaml`). See the disclosed
finding immediately above for this run's own concrete precision evidence.

**ASH signature covers the current issue-labeling convention only.**
Verified live back through 2018 ("Supplement N"); older, differently
labeled ASH annual-meeting abstracts are not captured this round.

**No target/payload/linker/candidate extraction from this source yet**
(same acquisition/extraction boundary every other job in this repo draws
first) -- deferred to a follow-up increment.

## Materialization this run

1487 unique candidate works discovered and signature-confirmed
(deduplicated by DOI). 1487 newly materialized,
0 skipped_unchanged this run.

## Sample materialized works

- [ASH] 10.1182/blood-2022-155852 (Supplement 1, p.10641-10642): Adrenoleukodystrophy Protein (ALDP) Antibody Formation and Graft Loss in Gene Therapy for 
- [ASH] 10.1182/blood-2022-155880 (Supplement 1, p.10801-10802): Disease-Specific Analysis of Drug Approval Delay in Hematologic Malignancies between Japan
- [ASH] 10.1182/blood-2022-155918 (Supplement 1, p.11295-11296): Quantitative Estimation of the <i>In Vivo</i> Equivalent Factor VIII Activity of NXT007, a
- [ASH] 10.1182/blood-2022-156316 (Supplement 1, p.12918-12919): Novel First-in-Class Drug ONC201 As a Post-Transplant Maintenance for AML and MDS: A Phase
- [ASH] 10.1182/blood-2022-156350 (Supplement 1, p.3871-3872): The Anti-HIV Drug Nelfinavir Exhibits Synergistic Activity with Tyrosine Kinase Inhibitors
- [ASH] 10.1182/blood-2022-156487 (Supplement 1, p.6769-6770): Comedication of Proton Pump Inhibitors and Dasatinib Is Common in CML but XS004, a Novel A
- [ASH] 10.1182/blood-2022-156995 (Supplement 1, p.12524-12524): Establishment of Patient-Derived Xenograft (PDX) Zebrafish Model of Multiple Myeloma and I
- [ASH] 10.1182/blood-2022-157011 (Supplement 1, p.9461-9463): CD19 4-1BBL (RO7227166) a Novel Costimulatory Bispecific Antibody Can be Safely Combined w
- [ASH] 10.1182/blood-2022-157262 (Supplement 1, p.6290-6290): Comparison of Data from Fresh and Frozen AML Samples for Functional Drug Testing
- [ASH] 10.1182/blood-2022-157316 (Supplement 1, p.4187-4188): Newly Diagnosed, Untreated, Multiple Myeloma (MM) Patient Samples Already Harbor Cereblon 
- [ASH] 10.1182/blood-2022-157485 (Supplement 1, p.2091-2092): RG6234: A Novel 2:1 GPRC5D T Cell Bispecific Antibody Exhibits Best in Class Potential for
- [ASH] 10.1182/blood-2022-157497 (Supplement 1, p.3716-3717): Phase I Study of the Anti-Btla Antibody Tifcemalimab As a Single Agent or in Combination w
- [ASH] 10.1182/blood-2022-157525 (Supplement 1, p.7264-7266): Initial Results of Dose Escalation of ISB 1342, a Novel CD3xCD38 Bispecific Antibody, in P
- [ASH] 10.1182/blood-2022-157634 (Supplement 1, p.6927-6929): In Vivo Drug Incorporation and Intracellular Dynamics of Injectable Versus Oral Azacytidin
- [ASH] 10.1182/blood-2022-157672 (Supplement 1, p.3151-3152): HDAC Inhibition Involves CD26 Induction on Multiple Myeloma Cells Via the c-Myc/Sp1-Mediat
- [ASH] 10.1182/blood-2022-157713 (Supplement 1, p.4444-4446): Trial in Progress: REGN5458, a BCMAxCD3 Bispecific Antibody, in a Phase Ib Multi-Cohort St
- [ASH] 10.1182/blood-2022-157726 (Supplement 1, p.1570-1571): Fully Myeloablative Antibody-Drug Conjugates Condition for Hematopoietic Stem Cell Transpl
- [ASH] 10.1182/blood-2022-157730 (Supplement 1, p.8176-8177): Drug-Induced Autoimmune Hemolytic Anemia: Detection of New Signals in the World Pharmacovi
- [ASH] 10.1182/blood-2022-157767 (Supplement 1, p.611-613): No Evidence of BCMA Expression Loss or Systemic Immune Impairment after Treatment with the
- [ASH] 10.1182/blood-2022-157862 (Supplement 1, p.9323-9324): Preliminary Safety and Efficacy Evaluation of IMM0306, a CD47 and CD20 Bispecific Monoclon

## Notes

- none

## Reproduction command

```bash
python -m adc_acquisition conference_crossref_search --output DATA
```
