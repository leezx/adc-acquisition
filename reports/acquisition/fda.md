# FDA (Job 06)

## Acquisition mechanism

openFDA structured product label full-text search (`GET /drug/label.json`) for discovery, Drugs@FDA submissions API (`GET /drug/drugsfda.json`) for reconciliation, plus direct retrieval of the actual regulatory documents (labels, approval letters, review documents) from FDA's Drugs@FDA document archive. Official REST interfaces; an API key is optional (raises the daily quota, never required).

## Official endpoint / API / dataset

https://api.fda.gov/drug/label.json — https://api.fda.gov/drug/drugsfda.json — https://open.fda.gov/apis/drug/drugsfda/

## Discovery strategy — not a manually maintained ADC list

Prompt.md section 14 explicitly prohibits relying on a manually maintained ADC drug list as the primary evidence source. FDA's own structured pharmacologic-class tags (`openfda.pharm_class_epc`/`pharm_class_cs`) turned out NOT to be reliably populated for ADCs when checked live (only 2 of 15 known ADCs carry a class tag at all). Instead, discovery is full-text search of the FDA-approved label's own `mechanism_of_action` and `description` sections for "antibody-drug conjugate" (configs/fda_queries.yaml) — verified live to catch all 15 major approved ADCs. See configs/fda_queries.yaml for the full verification notes.

## Applications (product/sponsor identity, see `fda_applications.parquet`)

15 application(s) reconciled this run: 15 succeeded (or unchanged), 0 not found in Drugs@FDA despite a label match, 0 failed on a network error. A label match that fails to reconcile still leaves a durable discovery-ledger row (`fda_applications_discovery.parquet`) — the identifier is never lost, only its content-materialization outcome is recorded separately (`fda_applications_attempts.parquet`).

- BLA125388: ADCETRIS (BRENTUXIMAB VEDOTIN), sponsor: SEATTLE GENETICS
- BLA125427: KADCYLA (ADO-TRASTUZUMAB EMTANSINE), sponsor: GENENTECH
- BLA761040: BESPONSA (INOTUZUMAB OZOGAMICIN), sponsor: WYETH PHARMS INC
- BLA761060: MYLOTARG (GEMTUZUMAB OZOGAMICIN), sponsor: WYETH PHARMS INC
- BLA761115: TRODELVY (SACITUZUMAB GOVITECAN-HZIY), sponsor: IMMUNOMEDICS INC
- BLA761121: POLIVY (POLATUZUMAB VEDOTIN-PIIQ), sponsor: GENENTECH
- BLA761137: PADCEV (ENFORTUMAB VEDOTIN-EJFV), sponsor: ASTELLAS
- BLA761137: PADCEV (ENFORTUMAB VEDOTIN-EJFV), sponsor: ASTELLAS
- BLA761139: ENHERTU (FAM-TRASTUZUMAB DERUXTECAN-NXKI), sponsor: DAIICHI SANKYO
- BLA761196: ZYNLONTA (LONCASTUXIMAB TESIRINE-LPYL), sponsor: ADC Therapeutics SA
- BLA761208: TIVDAK (TISOTUMAB VEDOTIN-TFTV), sponsor: SEAGEN
- BLA761310: ELAHERE (MIRVETUXIMAB SORAVTANSINE-GYNX), sponsor: IMMUNOGEN INC
- BLA761384: EMRELIS (TELISOTUZUMAB VEDOTIN-TLLV), sponsor: ABBVIE INC
- BLA761394: DATROWAY (DATOPOTAMAB DERUXTECAN-DLNK), sponsor: DAIICHI SANKYO INC
- BLA761440: BLENREP (BELANTAMAB MAFODOTIN-BLMF), sponsor: GLAXOSMITHKLINE LLC
- BLA761460: DECNUPAZ (PIVEKIMAB SUNIRINE-PVZY), sponsor: ABBVIE INC

## Submissions discovered

24 label-search hits across 2 discovery queries; 102 unique submissions after reconciling each discovered application_number's full Drugs@FDA submission history.

## Submissions downloaded

82 new/changed submission snapshots, 20 skipped as unchanged (matched checkpoint content hash).

## Duplicates

46 submissions were attributed to more than one discovery query (expected overlap between the mechanism_of_action/description full-text queries hitting the same label, not a data-quality concern).

### Label hits per discovery query

- FDA_LABEL_DESC_001: 9
- FDA_LABEL_MOA_001: 15

## Missing fields

- none observed in this run

- application distribution: BLA125388: 19, BLA125427: 14, BLA761040: 2, BLA761060: 5, BLA761115: 12, BLA761121: 4, BLA761137: 13, BLA761139: 16, BLA761196: 5, BLA761208: 4, BLA761310: 3, BLA761384: 1, BLA761394: 2, BLA761440: 1, BLA761460: 1
- submission class distribution: Efficacy: 44, Labeling: 40, Manufacturing (CMC): 3, Type 1 - New Molecular Entity: 13, Type 2 - New Active Ingredient: 1, Type 4 - New Combination: 1

## Documents (independent artifact, see `fda_documents.parquet`)

223 document fetches attempted this run (183 new/changed, 38 unchanged, 2 failed). Documents (labels, approval letters, review documents, medication guides, ...) are tracked as their own content-version manifest, keyed by `{submission_key}:{doc_id}` with `parent_record_id` pointing back to the submission — never as a field on the submission row itself, so a document fetch failure or a later successful retry never touches the submission's own content-version snapshot.

## Failed downloads

0 (see DATA/logs/fda_failures.log and fda_submissions_attempts.parquet (status=failed)). Failed attempts never occupy a content-manifest version slot. Note: a submission's own row can never itself fail to materialize (its "content" is metadata already in hand once the parent application's Drugs@FDA record was fetched) — only document-level fetches, and whole-application-record fetches (tracked separately above), can fail.

## Rate/access limitations

openFDA: 240 requests/min either way; 1,000 requests/day without an API key, 120,000/day with one (verified live). `FDA_API_KEY` is optional, read from the environment if present. fda.gov's web front end (not api.fda.gov) runs bot detection that blocks the default `requests` User-Agent — `jobs/fda/client.py` sends a descriptive one on every request.

## Data quality observations

- A submission's `submission_type`/`submission_number` pair (e.g. ORIG-1, SUPPL-81) is FDA's own regulatory-milestone identifier; an amendment/supplement is its own submission entry, not a patch to the original.
- Some older `application_docs` URLs redirect to a dead page on FDA's modern site (observed live: an "Other Important Information from FDA" doc from 2012 404s after a 301 redirect) — a genuine FDA-side historical link-rot gap, surfaced as an expected logged `failed` attempt, not a crash.
- `--since`/`--until` filter by each submission's own `submission_status_date`; `--resume`'s cursor advances unconditionally every run (same failure-safe design as SEC EDGAR's Job 05, applied here from the start) — any submission not yet successfully materialized, or with an unresolved document failure, is unioned back into scope regardless of date, with fresh/in-range submissions always prioritized over that backlog within a `--limit` budget.

## Known coverage gaps

- Discovery only covers currently FDA-*approved* products with a structured product label — an ADC that was submitted/reviewed but never approved (no label exists) would not be discovered this way. FDA Drug Safety Communications and Complete Response Letters (openFDA's separate CRL dataset) are not yet acquired here; Prompt.md's "reviewed" and "safety communications" scope would need a separate discovery path for non-approved products.
- No terminal-failure category is classified yet for FDA (unlike SEC's confirmed-permanent `no_primary_document`) — none has been observed live; the --resume backlog protections (fresh-priority ordering) still prevent starvation even without one.

## Reproduction command

```bash
python -m adc_acquisition fda --limit 102 --output DATA
```
