# USPTO (Job 09)

## Acquisition mechanism

USPTO's own Open Data Portal (data.uspto.gov, "Patent File Wrapper" API) is the current official mechanism — PatentsView (api.patentsview.org) was shut down 2026-03-20 and now redirects to ODP's own migration guide; developer.uspto.gov is also decommissioned. A free USPTO.gov account + API key is required (`X-API-KEY` header, verified live), but unlike WIPO PATENTSCOPE there is no automation ban — registration-gated, not prohibited.

## Official endpoint / dataset

https://data.uspto.gov/ — `patent/applications/search` (discovery), `patent/applications/{applicationNumber}` (full bibliographic record), `patent/applications/{applicationNumber}/documents` (file wrapper documents).

## Discovery strategy — free-text queries per Prompt.md's listed search concepts

configs/uspto_queries.yaml (5 queries, same concepts as Job 08/WIPO): singular/plural "antibody-drug conjugate(s)" phrase, "immunoconjugate", "antibody AND linker AND cytotoxin" (0 results in USPTO's corpus, verified live — not a bug, kept for provenance parity), "antibody AND payload AND conjugate". USPTO's free-text search covers full specification content, not just titles.

## Applications discovered

2726 unique applications matched across 5 queries this run.

- 10250998: Sensitization of cancer cells to immunoconjugate-induced cell death by transfection with il -13 receptor alpha chain (status: Abandoned  --  Failure to Respond to an Office Action)
- 10546304: ANTI-CD70 ANTIBODY-DRUG CONJUGATES AND THEIR USE FOR THE TREATMENT OF CANCER AND IMMUNE DISORDERS (status: Patented Case)
- 10632151: Anti-CD20 antibody-drug conjugates for the treatment of cancer and immune disorders (status: Abandoned  --  Failure to Respond to an Office Action)
- 11141344: Antibody-drug conjugates and methods (status: Abandoned  --  After Examiner's Answer or Board of Appeals Decision)
- 11311591: Antibody drug conjugates and methods (status: Abandoned  --  Failure to Respond to an Office Action)
- 11342937: HETEROCYCLIC-SUBSTITUTED BIS-1,8 NAPHTHALIMIDE COMPOUNDS, ANTIBODY DRUG CONJUGATES, AND METHODS OF USE (status: Patent Expired Due to NonPayment of Maintenance Fees Under 37 CFR 1.362)
- 11471457: PSMA antibody-drug conjugates (status: Abandoned  --  Failure to Respond to an Office Action)
- 11498139: Immunoconjugate formulations (status: Patent Expired Due to NonPayment of Maintenance Fees Under 37 CFR 1.362)
- 11677029: ANTIBODY DRUG CONJUGATE METABOLITES (status: Patented Case)
- 11735376: ANTI-CD70 ANTIBODY-DRUG CONJUGATES AND THEIR USE FOR THE TREATMENT OF CANCER AND IMMUNE DISORDERS (status: Abandoned  --  Failure to Respond to an Office Action)
- 12052938: ANTIBODY-DRUG CONJUGATES AND METHODS (status: Patented Case)
- 12088066: Antibody-Drug Conjugates and Methods of Use (status: Abandoned  --  Failure to Respond to an Office Action)
- 12092036: MACROCYCLIC DEPSIPEPTIDE ANTIBODY-DRUG CONJUGATES AND METHODS (status: Abandoned  --  Failure to Respond to an Office Action)
- 12097508: IMMUNOCONJUGATE FOR HUMAN CD66 FOR THE TREATMENT OF MULTIPLE MYELOMA AND OTHER HAEMATOLOGICAL MALIGNANCIES (status: Patented Case)
- 12116457: CYSTEINE ENGINEERED ANTI-MUC16 ANTIBODIES AND ANTIBODY DRUG CONJUGATES (status: Patented Case)

## Materialization this run

10 new/changed, 0 unchanged, 0 failed. Unlike Job 08 (WIPO), every discovered application is refetched and hash-compared every run (prosecution status/assignments/continuity data genuinely change over time) — 0 of this run's candidates were unresolved retries from a previous failure, 20 were already-resolved reverify candidates (scheduled strictly after fresh/backlog under a --limit budget, so they can never starve out a genuinely new application).

## Documents (independent artifact, see `uspto_documents.parquet`)

22 Specification-document candidates considered this run (22 newly fetched, 0 already resolved and skipped with NO HTTP request, 0 failed) — filtered to `documentCode == "SPEC"` (the actual filed claims/full-text document; other file wrapper document types — filing receipts, fee worksheets, notices, office actions, ... — are a separate, not-yet-acquired concern). Documents are processed for every application reconciled this run, independent try/except from the application's own outcome. Document versioning is IDENTITY-based, not hash-based: USPTO's `/download` endpoints dynamically re-render the PDF/XML on every request (verified live — different bytes on each of two immediately-successive fetches of the same document), so a document is skipped once its `documentIdentifier` has one successful attempt, rather than being refetched and hash-compared like every other document artifact in this repo.

## Failed downloads

0 (see DATA/logs/uspto_failures.log and uspto_attempts.parquet, status=failed). Failed attempts never occupy a manifest version slot, and are retried on every future run regardless of --resume's date cursor (which never narrows USPTO's search itself — see module docstring).

## Rate/access limitations

Weekly quotas verified live via the account's own consumption dashboard: 5,000,000 metadata retrievals, 1,200,000 document retrievals. A short-window HTTP 429 was observed during rapid successive live-verification calls despite this generous weekly ceiling, so a conservative per-second pace is used regardless (jobs/uspto/client.py). Search page size is capped at 100/request, and a full unrestricted page can trip a 6MB response-payload cap due to each record's large event-history log — discovery uses a minimal `fields=` projection to stay well under it.

## Data quality observations

- `--since`/`--until` filter discovery itself via USPTO's own bracket-range date syntax (`applicationMetaData.filingDate:[...]`), applied server-side only when the caller supplies them explicitly. `--resume`'s implicit cursor never narrows the search this way (would make an unresolved backlog item whose filing predates the cursor undiscoverable) — it and the plain default both run a full undated sweep every run.
- Abstract text is not directly exposed in the bibliographic metadata; it would require parsing the Specification document's own full text (not yet done — see known coverage gaps).

## Known coverage gaps

- Abstract text is not directly available as a structured metadata field — only title, applicants, inventors, filing/publication dates, CPC classification, and foreign priority are captured as structured fields; the Specification document (raw PDF/XML) is preserved separately but not yet parsed for abstract/claims text extraction.
- Only Specification (`SPEC`) documents are acquired — Office Actions, examiner citations, and other file wrapper document types are a separate, not-yet-acquired concern.
- Patent family/continuity resolution is deliberately NOT performed here (Prompt.md: "Do not resolve families yet") — `parentContinuityBag`/`foreignPriorityBag` data is preserved as raw fields instead.

## Reproduction command

```bash
python -m adc_acquisition uspto --limit 20 --output DATA
```
