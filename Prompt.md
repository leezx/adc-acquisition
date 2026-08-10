# Task: Build a Source-by-Source ADC Evidence Acquisition Pipeline

You are building the raw evidence acquisition layer for a systematic antibody–drug conjugate (ADC) knowledgebase.

The conceptual collection strategy is based on the ADCdb methodology:

1. Search patent databases and patent organizations for ADC-related inventions.
2. Search pharmaceutical and biotechnology company R&D pipelines for ADC assets.
3. Search biomedical literature databases for ADC publications.
4. Retrieve biological activity evidence for identified ADCs from publications and patents.
5. Preserve sufficient provenance so downstream systems can reconstruct where every ADC claim and activity measurement came from.

The historical ADCdb publication reported 6,572 ADCs and 9,171 biological activities, but DO NOT treat those numbers as reproduction targets. We do not have the exact historical queries, source lists, deduplication logic, or extraction rules used by ADCdb.

Our objective is therefore:

> Build a reproducible, auditable, source-separated acquisition system that can systematically collect the raw public evidence needed to construct and continuously update an ADC knowledgebase.

This task is about DATA ACQUISITION, not final ADC knowledge extraction.

Do not attempt to infer final ADC records during downloading.

---

# 0. Fundamental Architecture

The pipeline MUST follow:

SOURCE
→ DISCOVERY
→ IDENTIFIER COLLECTION
→ RAW DOWNLOAD
→ METADATA NORMALIZATION
→ MANIFEST
→ DOWNSTREAM EXTRACTION

Each external source must be implemented as an independent acquisition job.

One source failure must never prevent other sources from running.

Examples:

```text
PubMed
WIPO / PATENTSCOPE
USPTO
EPO / Espacenet or OPS
ClinicalTrials.gov
Company pipelines
Company press releases
SEC filings
FDA
EMA
Crossref / Europe PMC / PMC
```

Do NOT build one giant crawler.

Instead build:

```text
jobs/
    pubmed/
    europe_pmc/
    patents_wipo/
    patents_uspto/
    patents_epo/
    clinicaltrials/
    company_pipeline/
    company_press_release/
    sec/
    fda/
    ema/
```

Each job must be independently executable.

---

# 1. Strict Separation Between Acquisition and Knowledge Extraction

This is critical.

The acquisition layer should answer:

> What source documents exist, where did they come from, when were they retrieved, and what raw information did the source provide?

It should NOT answer:

> What is the final canonical ADC?
> What is its linker?
> What is its payload?
> What biological activity should be trusted?
> Are two aliases the same molecule?

Those belong downstream.

During acquisition, preserve uncertainty.

Never discard a record merely because its ADC relevance is uncertain.

---

# 2. Global Directory Structure

Create a structure similar to:

```text
DATA/
    raw/
        pubmed/
        europe_pmc/
        patents_wipo/
        patents_uspto/
        patents_epo/
        clinicaltrials/
        company_pipeline/
        company_press_release/
        sec/
        fda/
        ema/

    manifests/
        pubmed.parquet
        europe_pmc.parquet
        patents_wipo.parquet
        patents_uspto.parquet
        patents_epo.parquet
        clinicaltrials.parquet
        company_pipeline.parquet
        company_press_release.parquet
        sec.parquet
        fda.parquet
        ema.parquet

    logs/

    checkpoints/

    source_registry/
        sources.yaml
```

If the repository has an established external-DATA convention, follow that convention instead.

Do not commit large downloaded datasets into the code repository.

---

# 3. Universal Manifest Contract

Every source-specific job must generate a normalized manifest.

Minimum fields:

```text
source
source_record_id
source_record_type
title
url
publication_or_release_date
retrieved_at
query_id
query_text
raw_file_path
raw_format
content_hash
download_status
http_status
license_or_access_note
parent_record_id
version
notes
```

Source-specific identifiers should also be retained:

```text
pmid
pmcid
doi
nct_id
patent_publication_number
patent_application_number
patent_family_id
company
regulatory_document_id
sec_accession_number
```

Do NOT force all source-specific fields into one universal table if doing so destroys information.

Keep:

```text
common manifest
+
source-specific metadata
```

---

# 4. Universal Acquisition Requirements

Every job must support:

```bash
--dry-run
--limit N
--resume
--since DATE
--until DATE
--output DIR
```

where technically applicable.

Each job must:

1. be restartable;
2. cache previously downloaded records;
3. avoid downloading unchanged records unnecessarily;
4. implement retries with exponential backoff;
5. respect source rate limits and Terms of Service;
6. prefer official APIs or bulk downloads over HTML scraping;
7. log failed identifiers;
8. never silently drop failures;
9. calculate file/content hashes;
10. preserve retrieval timestamps;
11. preserve the exact search query that produced each record.

No CAPTCHA bypassing.

No authentication circumvention.

No aggressive crawling.

If a source does not permit systematic downloading, record the limitation and use permitted APIs, metadata, links, or alternative official sources.

---

# 5. JOB 01 — PubMed

Objective:

Collect ADC-related biomedical literature metadata.

Use NCBI-supported interfaces.

Do not begin with the simplistic query:

```text
ADC
```

because it is highly ambiguous.

Construct explicit query families.

Examples:

```text
"antibody-drug conjugate"
"antibody drug conjugate"
"antibody-drug conjugates"
"antibody drug conjugates"
ADC AND antibody AND conjugate
immunoconjugate AND cytotoxic
```

Maintain the queries in configuration rather than hard-coding them.

Example:

```text
configs/pubmed_queries.yaml
```

Download at minimum:

```text
PMID
title
abstract
authors
journal
publication date
DOI
publication types
MeSH terms when available
```

Store original API/XML/JSON responses whenever practical.

Do not perform final ADC classification here.

Output:

```text
DATA/raw/pubmed/
DATA/manifests/pubmed.parquet
```

Validation report:

```text
number of queries
records/query
unique PMIDs
duplicate PMIDs across queries
records with abstracts
records without abstracts
records with DOI
date distribution
download failures
```

---

# 6. JOB 02 — Europe PMC / PMC Full Text

Objective:

Complement PubMed with legally accessible abstracts and full-text literature.

Use Europe PMC and/or PMC official APIs.

Search using the same controlled ADC query family where possible.

Preserve:

```text
PMID
PMCID
DOI
title
abstract
full-text availability
license
publication date
```

For open-access full text, download legally accessible XML whenever supported.

Do NOT bypass publisher paywalls.

Cross-reference PMID/DOI with PubMed, but do not delete duplicate source evidence.

A paper appearing in both PubMed and Europe PMC should retain both provenance records.

---

# 7. JOB 03 — WIPO Patent Acquisition

Objective:

Discover ADC-related patent documents/families represented in WIPO resources.

Search concepts including:

```text
"antibody-drug conjugate"
"antibody drug conjugate"
"antibody-drug conjugates"
immunoconjugate
antibody AND linker AND cytotoxin
antibody AND payload AND conjugate
```

Determine what official WIPO interface/API/bulk mechanism is legally and technically available.

Do NOT immediately implement fragile scraping if no stable public API exists.

First document:

```text
available interface
query capability
rate limits
download capability
document formats
family information availability
legal/access constraints
```

Collect where available:

```text
publication number
application number
priority date
publication date
title
abstract
applicant
inventor
IPC/CPC
patent family identifiers
source URL
```

If full patent documents are legally downloadable, preserve them separately.

Important:

Do NOT deduplicate patent families during acquisition.

Family normalization belongs downstream.

---

# 8. JOB 04 — USPTO Patent Acquisition

Build an independent USPTO acquisition process.

Use official USPTO-supported APIs/datasets where possible.

Collect ADC-related patent metadata and available documents.

Preserve:

```text
US publication/application number
title
abstract
applicant/assignee
inventors
filing date
priority information
CPC/IPC
claims/full text where legally and technically available
```

Keep USPTO provenance independent from WIPO.

Do not assume identical patent numbers represent independent inventions.

Do not resolve families yet.

---

# 9. JOB 05 — EPO Patent Acquisition

Build an independent EPO acquisition process using official supported resources such as OPS when available and permitted.

Collect:

```text
EP publication number
title
abstract
applicant
inventor
priority
publication date
classification
family metadata
available document links/content
```

Again:

ACQUIRE first.

Patent-family reconciliation happens downstream.

---

# 10. JOB 06 — ClinicalTrials.gov

Objective:

Acquire clinical ADC trial records independently of publications.

Use the official ClinicalTrials.gov API.

Construct both:

A. broad ADC queries;

B. known-asset lookup capability.

Search concepts should include:

```text
antibody-drug conjugate
antibody drug conjugate
ADC
```

but never rely on `ADC` alone for downstream relevance.

Collect the complete trial JSON where possible.

Normalized metadata should include:

```text
NCT ID
brief title
official title
study type
phase
overall status
conditions
interventions
sponsor
collaborators
enrollment
start date
primary completion date
completion date
primary outcomes
secondary outcomes
locations
references
last update date
```

Preserve historical/version information where accessible.

Do NOT yet decide whether:

```text
drug = ADC
trial = relevant
trial status = final asset status
```

Those are downstream decisions.

---

# 11. JOB 07 — Pharmaceutical Company Pipeline Pages

This is fundamentally different from database APIs.

Objective:

Systematically archive public R&D pipeline evidence from ADC-relevant pharmaceutical and biotechnology companies.

First create:

```text
configs/company_registry.yaml
```

Each company entry should contain:

```text
canonical_company_name
aliases
official_domain
pipeline_urls
investor_relations_url
press_release_url
active
notes
```

Start with a curated company registry rather than attempting unrestricted web crawling.

Pipeline job should archive:

```text
HTML
PDF
JSON if exposed publicly
retrieval date
source URL
company
document title
document date/version where identifiable
```

Important:

Company pipeline pages change over time.

Therefore snapshots are essential.

Never overwrite old snapshots.

Use:

```text
company/date/content_hash
```

or equivalent versioning.

The acquisition layer should preserve historical evidence that an asset appeared in a pipeline at a particular time.

---

# 12. JOB 08 — Company Press Releases / Investor Relations

Separate this from company pipeline pages.

Objective:

Acquire company-originated announcements concerning ADC assets.

Relevant categories include:

```text
clinical trial initiation
first patient dosed
Phase I/II/III results
regulatory submission
FDA/EMA approval
clinical hold
trial discontinuation
program termination
licensing
option agreements
acquisition
M&A
preclinical candidate nomination
IND clearance
```

Only collect from official company domains in this job.

Do not mix media reports into this source.

Preserve original:

```text
headline
release date
company
URL
HTML/PDF
retrieval timestamp
```

---

# 13. JOB 09 — SEC EDGAR

Objective:

Acquire legally authoritative company disclosures that may contain ADC program information.

Use official SEC EDGAR interfaces.

Potential document types:

```text
10-K
10-Q
8-K
S-1
20-F
6-K
exhibits
material licensing agreements
```

Maintain a company → CIK registry.

Preserve:

```text
CIK
accession number
filing type
filing date
company
document URL
raw filing
exhibits
```

Do not extract final ADC claims yet.

This source will later be particularly useful for:

```text
program discontinuation
licensing economics
milestones
asset ownership
clinical failures
acquisition history
```

---

# 14. JOB 10 — FDA

Objective:

Acquire official US regulatory evidence for approved or reviewed ADC products.

Identify appropriate FDA public datasets/pages for:

```text
approval letters
labels
Drugs@FDA records
review documents
safety communications
regulatory history
```

Preserve raw regulatory documents.

Key identifiers:

```text
product name
active ingredient
application number
approval date
supplement number when relevant
document type
```

Do not rely on manually maintained ADC lists as the primary evidence source.

---

# 15. JOB 11 — EMA

Build the analogous European regulatory acquisition process.

Collect where available:

```text
EPAR
product information
assessment reports
authorization history
withdrawal information
safety updates
```

Preserve raw PDFs/HTML and metadata.

---

# 16. JOB 12 — Crossref

Objective:

Provide DOI-centric literature discovery and metadata reconciliation.

This is complementary to PubMed, not a replacement.

Search ADC terminology and collect:

```text
DOI
title
authors
publisher
journal
publication date
type
references where available
```

Crossref records must remain source-attributed.

---

# 17. JOB 13 — Patent Bioactivity Evidence Corpus

This is a SECOND-PASS acquisition job.

It should NOT search the entire patent universe again.

Input:

```text
candidate ADC-related patent identifiers
```

generated from WIPO/USPTO/EPO discovery.

Objective:

Download the maximum legally accessible patent content needed for downstream bioactivity extraction.

Prioritize sections likely to contain:

```text
Examples
Experimental
Biological Example
In vitro
In vivo
Cytotoxicity
IC50
EC50
GI50
tumor growth inhibition
xenograft
binding
internalization
DAR
payload
linker
```

But DO NOT parse those values in the acquisition layer.

Simply ensure downstream extraction has the raw patent evidence.

---

# 18. JOB 14 — Publication Bioactivity Evidence Corpus

Second-pass literature acquisition.

Input:

```text
PMIDs
PMCIDs
DOIs
known ADC aliases
```

Objective:

Acquire legally accessible publication content likely to contain biological activity measurements.

The downstream system will later extract:

```text
clinical activity
in-vivo activity
cell-line activity
IC50
EC50
DC50 if relevant
tumor inhibition
response rate
PK/PD
toxicity
```

Again:

DO NOT perform final structured extraction here.

---

# 19. JOB 15 — Known ADC Asset Expansion

After the first discovery pass, another acquisition loop should operate from known asset names.

Input:

```text
canonical/temporary ADC name
aliases
development codes
target
company
```

Generate source-specific searches such as:

```text
"<ADC name>"
"<ADC alias>"
"<ADC name>" patent
"<ADC name>" trial
"<ADC name>" activity
"<ADC name>" cytotoxicity
"<ADC name>" xenograft
"<ADC name>" IC50
```

Execute those searches independently against appropriate source jobs.

This creates:

DISCOVERY PASS
→ temporary ADC candidates
→ ASSET-CENTRIC EXPANSION PASS

Do not conflate the two passes.

---

# 20. Query Provenance

Every discovered record MUST be traceable back to the query that discovered it.

Create:

```text
query_registry
```

with fields:

```text
query_id
source
query_version
query_text
created_at
active
purpose
```

Examples:

```text
PUBMED_ADC_001
PUBMED_ADC_002
WIPO_ADC_001
CTGOV_ADC_001
```

This matters because the search strategy will evolve.

We must later be able to ask:

> Why is this document in our corpus?

and receive an exact answer.

---

# 21. Incremental Updating

The system must support future scheduled updates.

Do not design this as a one-time historical download.

Every source should support an incremental acquisition model where technically possible:

```text
last successful run
→ source updates since last run
→ acquire new/changed records
→ append new manifest version
```

Never silently modify historical raw evidence.

---

# 22. Source Registry

Create:

```text
configs/sources.yaml
```

Example conceptual schema:

```yaml
pubmed:
  source_type: literature
  authority: primary_index
  acquisition_method: api
  enabled: true

clinicaltrials_gov:
  source_type: clinical_registry
  authority: primary_registry
  acquisition_method: api
  enabled: true

sec:
  source_type: corporate_regulatory
  authority: primary
  acquisition_method: api
  enabled: true
```

Include:

```text
source name
source class
official URL
API/bulk documentation
acquisition mechanism
authentication requirement
rate limit
license/access notes
raw formats
update strategy
implementation status
```

---

# 23. Data Integrity

Raw evidence must be immutable.

If the same source record changes:

DO NOT overwrite the old version.

Store a new snapshot.

Use content hashes to detect changes.

Conceptually:

```text
source_record_id
version 1
hash AAA

source_record_id
version 2
hash BBB
```

This allows historical reconstruction.

---

# 24. Deduplication Policy

There are two distinct concepts:

## Acquisition duplicate

Exactly the same source record downloaded twice.

This can be prevented through source ID + content hash.

## Knowledge duplicate

Different source records referring to the same ADC, trial, patent family, company asset, or experiment.

DO NOT resolve knowledge duplicates in the acquisition layer.

Examples:

```text
PMID A
ClinicalTrials.gov NCT B
WIPO patent C
Seagen pipeline D
FDA document E
```

may all describe the same ADC.

They must remain independent evidence objects.

---

# 25. Testing Requirements

Every source job needs tests for:

```text
query construction
pagination
rate limiting
retry behavior
resume/checkpoint behavior
manifest generation
duplicate download prevention
content hashing
malformed response handling
empty result handling
HTTP failure
partial download
schema validation
```

Use mocked responses for unit tests.

Do not require live internet access for the normal test suite.

Create a small optional integration test for live-source verification.

---

# 26. Per-Source Execution Report

After EACH source is implemented, generate:

```text
reports/acquisition/<source>.md
```

Required structure:

```text
# Source

## Acquisition mechanism

## Official endpoint / API / dataset

## Queries used

## Date coverage

## Records discovered

## Records downloaded

## Duplicates

## Missing fields

## Failed downloads

## Rate/access limitations

## Data quality observations

## Known coverage gaps

## Reproduction command
```

Do not hide coverage failures.

---

# 27. Master Coverage Report

Create:

```text
reports/acquisition/COVERAGE.md
```

with a matrix:

| Source | Type | Implemented | API/Bulk | Raw Download | Incremental | Records | Status |
|---|---|---|---|---|---|---:|---|
| PubMed | Literature | | | | | | |
| Europe PMC | Literature | | | | | | |
| WIPO | Patent | | | | | | |
| USPTO | Patent | | | | | | |
| EPO | Patent | | | | | | |
| ClinicalTrials.gov | Clinical | | | | | | |
| Company pipelines | Corporate | | | | | | |
| Company PR | Corporate | | | | | | |
| SEC | Regulatory | | | | | | |
| FDA | Regulatory | | | | | | |
| EMA | Regulatory | | | | | | |
| Crossref | Literature | | | | | | |

---

# 28. Execution Strategy — CRITICAL

DO NOT implement and run all sources simultaneously.

Work source-by-source.

For every source use exactly this workflow:

```text
STEP 1
Investigate the official access mechanism.

STEP 2
Write a short implementation plan.

STEP 3
Implement the downloader.

STEP 4
Write unit tests.

STEP 5
Run:
--dry-run

STEP 6
Run a tiny acquisition:
--limit 20

STEP 7
Inspect raw files and manifest manually/programmatically.

STEP 8
Run a medium acquisition:
--limit 500

STEP 9
Generate the source report.

STEP 10
Only after validation, perform the full acquisition.
```

Stop if fundamental source/API/access assumptions are wrong.

Do not compensate for a broken source by silently switching to arbitrary third-party websites.

---

# 29. Recommended Execution Order

Implement in this order:

```text
01 PubMed
02 Europe PMC / PMC
03 ClinicalTrials.gov
04 Crossref
05 SEC EDGAR
06 FDA
07 EMA
08 WIPO
09 USPTO
10 EPO
11 Company R&D pipelines
12 Company press releases / IR
13 Patent bioactivity corpus expansion
14 Publication bioactivity corpus expansion
15 Known-ADC asset-centric expansion
```

Reason:

The early sources have cleaner APIs and identifiers and can establish the initial ADC candidate universe.

Patent and company sources are substantially more heterogeneous and should be tackled after the common acquisition contracts have stabilized.

---

# 30. Important Scientific Constraint

Do not assume:

```text
mentioned ADC = real ADC asset
patent compound = experimentally synthesized
patent example = clinically relevant
trial intervention name = canonical ADC identity
pipeline presence = active development
company statement = independently validated fact
publication mention = original evidence
```

The acquisition layer preserves evidence.

The downstream evidence engine decides what the evidence means.

---

# 31. Final Deliverable

The final acquisition infrastructure should allow commands conceptually equivalent to:

```bash
python -m adc_acquisition pubmed --resume
python -m adc_acquisition clinicaltrials --resume
python -m adc_acquisition sec --resume
python -m adc_acquisition wipo --resume
python -m adc_acquisition company_pipeline --company seagen --resume
```

and eventually:

```bash
python -m adc_acquisition run-all --resume
```

However, `run-all` should merely orchestrate independent jobs.

It must not create coupling between them.

---

# 32. What You Should Do NOW

Do NOT begin downloading everything.

First:

1. inspect the existing repository architecture;
2. identify existing DATA/external-reference conventions;
3. create the source registry;
4. create the universal manifest contract;
5. create the acquisition job interface;
6. create checkpoint/logging infrastructure;
7. implement ONLY JOB 01: PubMed;
8. test it with 20 records;
9. show me:
   - files changed;
   - architecture;
   - exact PubMed queries;
   - 20-record test results;
   - manifest example;
   - tests;
   - unresolved issues.

STOP THERE.

Do not proceed to Europe PMC until I review the PubMed implementation.

The governing principle is:

> One source → one acquisition job → one raw evidence corpus → one manifest → one validation report.

We are building an auditable ADC evidence infrastructure, not a one-off web scraper.