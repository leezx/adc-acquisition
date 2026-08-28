# Company Press Releases (Job 12)

## Acquisition mechanism

No official API exists for any of these IR newsrooms — "fundamentally different from database APIs" (Prompt.md's own framing, same as Job 11). Every company's `press_release_url` (`configs/company_registry.yaml`, shared with Job 05/SEC and Job 11) is a curated LISTING page; the individual releases behind it are discovered by walking that listing's pagination, using a per-company `press_release_template` to select the correct parser (jobs/company_press_release/parser.py). Only releases whose own URL stays on the company's registered `official_domain` (or a subdomain of it) are accepted — "do not mix media reports into this source" (Prompt.md).

## Registered companies this run

- Zymeworks Inc. (zymeworks): https://ir.zymeworks.com/news-releases
- Sutro Biopharma, Inc. (sutro_biopharma): https://ir.sutrobio.com/news-events/news-releases [q4_ir_media]
- ADC Therapeutics SA (adc_therapeutics): https://ir.adctherapeutics.com/news [workiva_ir_newsroom]
- AbbVie Inc. (abbvie): https://news.abbvie.com/ [workiva_ir_newsroom]
- Pfizer Inc. (pfizer): https://www.pfizer.com/newsroom/press-releases [pfizer_drupal_newsroom]

## Materialization this run

3542 releases discovered across 5 companies. 3542 never-attempted (fresh), 0 unresolved-retry (backlog), 0 pending recovery (raw durable but ledger stale), 0 already successful and skipped with no request. 3520 newly downloaded (new or changed content), 0 unchanged, 22 failed.

## Sample materialized releases (most recent 20 by company)

- ADC Therapeutics SA: ADC Therapeutics Reports Second Quarter 2026 Financial Results and Provides Operational Updates (2026-08-13, https://ir.adctherapeutics.com/2026-08-13-ADC-Therapeutics-Reports-Second-Quarter-2026-Financial-Results-and-Provides-Operational-Updates, version 1)
- ADC Therapeutics SA: ADC Therapeutics to Host Second Quarter 2026 Financial Results Conference Call on August 13, 2026 (2026-08-06, https://ir.adctherapeutics.com/2026-08-06-ADC-Therapeutics-to-Host-Second-Quarter-2026-Financial-Results-Conference-Call-on-August-13,-2026, version 1)
- ADC Therapeutics SA: ADC Therapeutics Announces New Employee Inducement Grant (2026-07-01, https://ir.adctherapeutics.com/2026-07-01-ADC-Therapeutics-Announces-New-Employee-Inducement-Grant, version 1)
- ADC Therapeutics SA: ADC Therapeutics Announces Completion of Enrollment in LOTIS-7 Phase 1b ZYNLONTA® Combination Trial (2026-06-30, https://ir.adctherapeutics.com/2026-06-30-ADC-Therapeutics-Announces-Completion-of-Enrollment-in-LOTIS-7-Phase-1b-ZYNLONTA-R-Combination-Trial, version 1)
- ADC Therapeutics SA: ADC Therapeutics Announces Strategic Reorganization to Support ZYNLONTA® Growth Opportunities and Regulatory Priorities (2026-06-24, https://ir.adctherapeutics.com/2026-06-24-ADC-Therapeutics-Announces-Strategic-Reorganization-to-Support-ZYNLONTA-R-Growth-Opportunities-and-Regulatory-Priorities, version 1)
- ADC Therapeutics SA: ADC Therapeutics Announces Results From LOTIS-5 Phase 3 Confirmatory Clinical Trial of ZYNLONTA® in Combination with Rituximab in Relapsed or Refractory Diffuse Large B-Cell Lymphoma (2026-06-03, https://ir.adctherapeutics.com/2026-06-03-ADC-Therapeutics-Announces-Results-From-LOTIS-5-Phase-3-Confirmatory-Clinical-Trial-of-ZYNLONTA-R-in-Combination-with-Rituximab-in-Relapsed-or-Refractory-Diffuse-Large-B-Cell-Lymphoma, version 1)
- ADC Therapeutics SA: ADC Therapeutics Reports First Quarter 2026 Financial Results and Provides Operational Updates (2026-05-04, https://ir.adctherapeutics.com/2026-05-04-ADC-Therapeutics-Reports-First-Quarter-2026-Financial-Results-and-Provides-Operational-Updates, version 1)
- ADC Therapeutics SA: ADC Therapeutics Makes Grants to New Employees Under Inducement Plan (2026-05-01, https://ir.adctherapeutics.com/2026-05-01-ADC-Therapeutics-Makes-Grants-to-New-Employees-Under-Inducement-Plan, version 1)
- ADC Therapeutics SA: ADC Therapeutics to Host First Quarter 2026 Financial Results Conference Call on May 4, 2026 (2026-04-27, https://ir.adctherapeutics.com/2026-04-27-ADC-Therapeutics-to-Host-First-Quarter-2026-Financial-Results-Conference-Call-on-May-4,-2026, version 1)
- ADC Therapeutics SA: ADC Therapeutics Announces New Employee Inducement Grant (2026-04-01, https://ir.adctherapeutics.com/2026-04-01-ADC-Therapeutics-Announces-New-Employee-Inducement-Grant, version 1)
- ADC Therapeutics SA: ADC Therapeutics Reports Fourth Quarter and Full Year 2025 Financial Results and Provides Operational Update (2026-03-10, https://ir.adctherapeutics.com/2026-03-10-ADC-Therapeutics-Reports-Fourth-Quarter-and-Full-Year-2025-Financial-Results-and-Provides-Operational-Update, version 1)
- ADC Therapeutics SA: ADC Therapeutics to Host Fourth Quarter and Full Year 2025 Financial Results Conference Call on March 10, 2026 (2026-03-03, https://ir.adctherapeutics.com/2026-03-03-ADC-Therapeutics-to-Host-Fourth-Quarter-and-Full-Year-2025-Financial-Results-Conference-Call-on-March-10,-2026, version 1)
- ADC Therapeutics SA: ADC Therapeutics Makes Grants to New Employees Under Inducement Plan (2026-03-02, https://ir.adctherapeutics.com/2026-03-02-ADC-Therapeutics-Makes-Grants-to-New-Employees-Under-Inducement-Plan, version 1)
- ADC Therapeutics SA: ADC Therapeutics to Participate in March Investor Conferences (2026-02-24, https://ir.adctherapeutics.com/2026-02-24-ADC-Therapeutics-to-Participate-in-March-Investor-Conferences, version 1)
- ADC Therapeutics SA: ADC Therapeutics Announces Amended HealthCare Royalty Financing Agreement (2026-02-23, https://ir.adctherapeutics.com/2026-02-23-ADC-Therapeutics-Announces-Amended-HealthCare-Royalty-Financing-Agreement, version 1)
- ADC Therapeutics SA: ADC Therapeutics Makes Grants to New Employees Under Inducement Plan (2026-02-02, https://ir.adctherapeutics.com/2026-02-02-ADC-Therapeutics-Makes-Grants-to-New-Employees-Under-Inducement-Plan, version 1)
- ADC Therapeutics SA: ADC Therapeutics Provides Preliminary Fourth Quarter and Full Year 2025 Revenue and Cash Estimates and Recent Corporate Updates (2026-01-08, https://ir.adctherapeutics.com/2026-01-08-ADC-Therapeutics-Provides-Preliminary-Fourth-Quarter-and-Full-Year-2025-Revenue-and-Cash-Estimates-and-Recent-Corporate-Updates, version 1)
- ADC Therapeutics SA: ADC Therapeutics to Participate in the 44th Annual J.P. Morgan Healthcare Conference (2026-01-08, https://ir.adctherapeutics.com/2026-01-08-ADC-Therapeutics-to-Participate-in-the-44th-Annual-J-P-Morgan-Healthcare-Conference, version 1)
- ADC Therapeutics SA: ADC Therapeutics Announces New Employee Inducement Grant (2026-01-02, https://ir.adctherapeutics.com/2026-01-02-ADC-Therapeutics-Announces-New-Employee-Inducement-Grant, version 1)
- ADC Therapeutics SA: ADC Therapeutics Announces Updated Data from LOTIS-7 Phase 1b Clinical Trial of ZYNLONTA® in Combination with Bispecific Antibody Supporting Potential Best-in-Class Regimen in Patients with Relapsed/Refractory Diffuse Large B-cell Lymphoma (2025-12-03, https://ir.adctherapeutics.com/2025-12-03-ADC-Therapeutics-Announces-Updated-Data-from-LOTIS-7-Phase-1b-Clinical-Trial-of-ZYNLONTA-R-in-Combination-with-Bispecific-Antibody-Supporting-Potential-Best-in-Class-Regimen-in-Patients-with-Relapsed-Refractory-Diffuse-Large-B-cell-Lymphoma, version 1)

## Failed downloads

22 (see DATA/logs/company_press_release_failures.log and company_press_release_attempts.parquet, status=failed). A failure never occupies a manifest version slot, and is retried on every future run.

## Discovery failures

A company's own listing fetch/parse failing (network error, non-200 status, an unregistered template, a known template's first page parsing to zero items — usually template drift, not "nothing new" — or hitting the MAX_PAGES safety cap) is isolated to that company: it does not abort other companies' discovery or block materializing whatever was already found.

- zymeworks: UNKNOWN_TEMPLATE -- listing page reachable but no press_release_template registered
- abbvie: MAX_PAGES_REACHED -- hit MAX_PAGES=200 safety cap -- some history may not have been walked this run

## Known access limitation

Zymeworks' registered press_release_url (ir.zymeworks.com/news-releases) is on a subdomain that is currently entirely unreachable (confirmed live 2026-08-17: a direct request with a descriptive User-Agent hangs to a read timeout, distinct from a bot-detection block) — every attempt is recorded as a normal, logged `failed` attempt, not silently dropped.

## Known coverage gaps

- Individual press-release BODY TEXT is not extracted — only the raw page snapshot and the listing page's own headline/date are preserved. Categorizing releases (clinical trial initiation, regulatory approval, licensing, etc. — Prompt.md's own list) is downstream knowledge extraction (Prompt.md section 1), not acquisition.
- AbbVie's and Pfizer's press-release feeds cover their ENTIRE newsroom (all therapeutic areas), not just ADC-relevant announcements — same "acquire broadly, filter downstream" caveat already documented for their pipeline pages (Job 11).
- Seagen, ImmunoGen, and Mersana have no standalone press-release feed of their own (all acquired/absorbed, `press_release_url: null`), same as their pipeline-page situation.

## Reproduction command

```bash
python -m adc_acquisition company_press_release --output DATA
```
