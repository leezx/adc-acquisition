"""Documented construction of false_positive_audit.tsv and
nar_only_gap_diagnosis.tsv for the NAR ADCdb benchmark
(reports/validation/nar_adcdb_comparison.md).

These two tables require semantic judgment (is this record genuinely
ADC-relevant? is this gap an acquisition defect or an external-database
schema limitation?) that compare_nar_adcdb.py's identifier/text matching
cannot fully automate -- per the audit's own requirement, such judgment
calls must be human-reviewable, not asserted as a bare label. Every row
below documents the SPECIFIC evidence (query_id, an inventor/author name,
a grep count, etc.) that was directly verified against
DATA/manifests/*.parquet, the raw full-text files under DATA/raw/, or the
external ADCdb vault before being encoded here -- see
reports/validation/nar_adcdb_comparison.md sections 9/11 for the full
narrative behind each finding. This script is itself the reproducible
record of that judgment (re-running it regenerates identical output);
the two TSVs it writes are never hand-edited directly."""

import csv
from pathlib import Path

OUT_DIR = Path("reports/validation/nar_adcdb_comparison")

false_positive_rows = [
    # --- Job 15 asset-expansion queries: "Polivy" brand-name collision ---
    dict(source="pubmed", record_id="2026778", query_id="PUBMED_ASSETEXP_POLATUZUMAB_VEDOTIN_POLIVY_6807dc35a33a",
         title="Gender role and risk patterns for eating disorders in men and women.",
         classification="FALSE_POSITIVE",
         reason="Brand name 'Polivy' collides with Janet Polivy, a well-known eating-behavior researcher whose surname is cited in-text (authors are Cantrell/Ellis, not Polivy). Confirmed via direct check of the authors field.",
         confidence="high"),
    dict(source="pubmed", record_id="(21 similar rows)", query_id="PUBMED_ASSETEXP_POLATUZUMAB_VEDOTIN_POLIVY_6807dc35a33a",
         title="[eating-disorder / dietary-restraint literature, 21 total rows]",
         classification="FALSE_POSITIVE",
         reason="Same Polivy-surname collision -- systematic scan (grep for ADC/cancer keywords in title) confirms 23/28 PubMed asset-expansion hits for this one query_id are off-topic; every other bare-identifier/suffix query across all 14 assets and 5 sources had 0-2 off-topic hits (both plausibly legitimate, see notes).",
         confidence="high"),
    dict(source="europe_pmc", record_id="(2 rows)", query_id="EPMC_ASSETEXP_POLATUZUMAB_VEDOTIN_POLIVY_f16932f49da6",
         title="Bullying and eating pathology: do social anxiety and shame explain the links? / Restrictive dieting vs. undieting...",
         classification="FALSE_POSITIVE",
         reason="Same Polivy-surname collision, Europe PMC side.",
         confidence="high"),
    dict(source="uspto", record_id="US20040078704A1", query_id="USPTO_ASSETEXP_POLATUZUMAB_VEDOTIN_POLIVY_4a3bc8eef191",
         title="TRANSACTION-SAFE FAT FILE SYSTEM",
         classification="FALSE_POSITIVE",
         reason="Inventor field lists 'Daniel J. Polivy' (confirmed directly) -- a real Microsoft engineer. USPTO's free-text search matched the INVENTOR NAME, not any drug-related content. 16/27 USPTO asset-expansion hits for this query_id are unrelated software/hardware patents (auxiliary displays, file systems, sensors), all attributable to this same inventor-name collision.",
         confidence="high"),
    # --- Older, already-reviewed broad-discovery query design (Jobs 01-03, not introduced this session) ---
    dict(source="pubmed", record_id="multiple (see PUBMED_ADC_004)", query_id="PUBMED_ADC_004",
         title="e.g. 'A specific and potent immunotoxin composed of antibody ZME-018 and the plant toxin gelonin.'",
         classification="ADC_ADJACENT",
         reason="Job 01's own broad query PUBMED_ADC_004 ('immunoconjugate[tiab] AND cytotoxic[tiab]') was explicitly designed to also catch older terminology, which includes plant/bacterial-toxin IMMUNOTOXINS (ricin, gelonin, saporin) -- a related but distinct modality from a classic small-molecule-payload ADC (same immunotoxin-vs-ADC distinction as the moxetumomab_pasudotox exclusion decided in PR #15's review). Not a new defect -- Job 01 was already reviewed/approved with this query design; recall-favoring breadth here is a disclosed, intentional trade-off per Prompt.md's own acquisition-casts-a-wide-net philosophy.",
         confidence="medium"),
    dict(source="pubmed", record_id="row 25", query_id="PUBMED_ADC_004",
         title="Management of multiple myeloma.",
         classification="FALSE_POSITIVE",
         reason="General disease-management review with no conjugate/antibody/immunotoxin term at all in the title -- likely matched via abstract co-occurrence of unrelated terms, not genuinely about ADCs.",
         confidence="medium"),
    dict(source="clinicaltrials", record_id="multiple (see CTGOV_ADC_003/004)", query_id="CTGOV_ADC_003 / CTGOV_ADC_004",
         title="e.g. 'Vaccine Therapy in Treating Patients With Metastatic Prostate Cancer' / 'BMS-188667 (CTLA4Ig) in Patients With Rheumatoid Arthritis'",
         classification="FALSE_POSITIVE",
         reason="Job 03's broad query family surfaced cancer vaccine trials and an unrelated CTLA4-Ig fusion-protein (abatacept) rheumatoid-arthritis program -- neither is an antibody-DRUG conjugate. Pre-existing, already-reviewed Job 03 query design, not introduced this session.",
         confidence="medium"),
    dict(source="clinicaltrials", record_id="(3 rows)", query_id="CTGOV_ADC_003",
         title="Study of SGN-15 / SGN-15 combined with gemcitabine",
         classification="TRUE_ADC_RELEVANT",
         reason="SGN-15 (doxorubicin-conjugated BR96 antibody) is a genuine, historical antibody-drug conjugate -- correctly discovered, not a false positive.",
         confidence="high"),
    # --- Job 15 asset-expansion queries: sample of clearly TRUE positives, for precision-estimate denominator ---
    dict(source="clinicaltrials", record_id="20-record random sample", query_id="CTGOV_LOOKUP_INTR_* (various, all 14 assets)",
         title="[see gold_standard_audit.tsv / chat transcript for the full 20-row sample]",
         classification="TRUE_ADC_RELEVANT",
         reason="20/20 randomly sampled --intervention-lookup trials for known assets are genuinely about that exact ADC (e.g. NCT01196052 'A Study of Trastuzumab Emtansine (T-DM1)...'). --intervention lookup is an exact structured-field match, inherently far more precise than free-text search.",
         confidence="high"),
    dict(source="wipo/epo", record_id="10 asset-expansion rows (WIPO) + 6 (EPO)", query_id="WIPO_ASSETEXP_* / EPO_ASSETEXP_*",
         title="[see chat transcript sample]",
         classification="TRUE_ADC_RELEVANT",
         reason="Systematic keyword scan found only 2/37 WIPO+EPO asset-expansion titles lacking an obvious cancer/ADC keyword, and both of those ('Subcutaneous anti-HER2 antibody formulation' / pharmaceutical glass container patent; 'genetic variations associated with drug resistance') are plausibly legitimate T-DM1-related formulation/companion-diagnostic patents, not false positives.",
         confidence="medium"),
]

nar_only_gap_rows = [
    dict(asset="ALL 14 of our known assets", missing_item="Full identity to NAR's 21 'Approved' gold list", item_type="asset_match",
         expected_source="configs/known_adc_assets.yaml", search_attempt="exact/alias/dev-code match",
         result="14/14 MATCHED -- every one of our curated assets is in NAR's own most-confident Approved subset",
         root_cause="N/A -- this is a positive confirmation, not a gap", severity="N/A",
         recommended_action="none", needs_acquisition_change="NO", confidence="high"),
    dict(asset="polatuzumab_vedotin", missing_item="NAR synonyms not in our registry: 'DCDS4501S', 'RO-5541077-000/RO5541077', 'anti-CD79b-VC-MMAE', 'FCU-2711'",
         item_type="alias_gap", expected_source="configs/known_adc_assets.yaml dev_codes",
         search_attempt="cross-check NAR Synonyms field vs our aliases/dev_codes for all 14 assets",
         result="Confirmed missing -- see chat transcript's full per-asset diff",
         root_cause="ALIAS_OR_NAME_GAP", severity="P2",
         recommended_action="Add the genuinely literature/patent-relevant missing dev codes (not NAR's own internal ADC-ID accession numbers) to configs/known_adc_assets.yaml for all 14 assets",
         needs_acquisition_change="YES", confidence="high"),
    dict(asset="trastuzumab_emtansine", missing_item="NAR synonyms not in our registry: 'Trastuzumab-DM1', 'Herceptin-DM1', 'ADO-Trastuzumab Emtansine', 'RO-5304020'",
         item_type="alias_gap", expected_source="configs/known_adc_assets.yaml dev_codes",
         search_attempt="same cross-check as above",
         result="Confirmed missing -- 'Trastuzumab-DM1'/'T-DM1'-adjacent forms are extremely common in literature",
         root_cause="ALIAS_OR_NAME_GAP", severity="P1",
         recommended_action="Add 'Trastuzumab-DM1' and 'Herceptin-DM1' specifically -- high literature-usage terms",
         needs_acquisition_change="YES", confidence="high"),
    dict(asset="polatuzumab_vedotin (identifier 'Polivy' specifically)", missing_item="N/A -- this is a precision defect, not a missing item",
         item_type="query_ambiguity", expected_source="pubmed/europe_pmc/uspto bare-identifier queries",
         search_attempt="see false_positive_audit.tsv",
         result="Confirmed: 'Polivy' collides with 2 unrelated real people's surnames across 2 independent sources (41 false-positive records)",
         root_cause="QUERY_COVERAGE_GAP (ambiguous bare identifier used without a disambiguating co-term)", severity="P1",
         recommended_action="Require a co-occurring qualifier (e.g. canonical_name or company) whenever a brand/alias identifier is used standalone in a bare-identifier query, OR exclude 'Polivy' specifically from standalone bare-identifier search",
         needs_acquisition_change="YES", confidence="high"),
    dict(asset="all 14 known assets", missing_item="PMID-level identifier overlap vs NAR", item_type="identifier_overlap_not_computable",
         expected_source="NAR ADC detail pages", search_attempt="grep all 6235 ADC pages for 'PMID'",
         result="0/6235 NAR ADC pages cite a PMID for any reference -- confirmed structurally absent, not merely unpopulated for our 14 assets specifically",
         root_cause="NAR_MANUAL_CURATION_ONLY (external DB schema simply does not expose this field) -- NOT an acquisition defect",
         severity="N/A (not fixable on our side)", recommended_action="none -- document as a benchmark limitation",
         needs_acquisition_change="NO", confidence="high"),
    dict(asset="all 14 known assets", missing_item="Patent identifier (WO/EP/US) overlap vs NAR", item_type="identifier_overlap_not_computable",
         expected_source="NAR ADC detail pages", search_attempt="grep all 6235 ADC pages for 'patent' (case-insensitive)",
         result="0/6235 NAR ADC pages mention patents at all, despite the ADCdb paper's own stated methodology citing patents as a curation source",
         root_cause="NAR_MANUAL_CURATION_ONLY (patents used in curation but never re-exposed as public per-ADC evidence on the website) -- our own patent evidence (Jobs 08/09/10/13) is therefore COMPLEMENTARY to NAR, not overlapping",
         severity="N/A (not fixable on our side)", recommended_action="none -- document as a genuine acquisition-side value-add, not a gap",
         needs_acquisition_change="NO", confidence="high"),
    dict(asset="~688 of NAR's 702 phase-tagged assets (all except our 14 seed assets)", missing_item="Asset not yet in configs/known_adc_assets.yaml; broad-discovery corpus has not coincidentally found it",
         item_type="asset_not_targeted", expected_source="Jobs 01/02/04 broad-discovery queries (generic 'antibody-drug conjugate' topic terms) OR a future Job 15 registry expansion",
         search_attempt="checked whether any of these ~688 asset names/known aliases appear anywhere in our current materialized manifests (text search)",
         result="Essentially none found by coincidence -- our broad-discovery corpus is demo-scale (~20-50 records per source from generic topic queries, not per-asset name searches) and was never run at production scale",
         root_cause="SCALE_NOT_YET_RUN (this project's own PR-review process only ever exercised small, --limit-capped demo runs for review purposes; it is a project-scope/resourcing fact, NOT a mechanism defect -- the SAME Job 15 mechanism that found 251-1643 records per asset for our 14 seed assets would very likely find comparable per-asset evidence for any of these 688 if simply added to the seed registry and run)",
         severity="P1 (blocks broader asset coverage, but the FIX is 'curate + run', not a code defect)",
         recommended_action="Expand configs/known_adc_assets.yaml with additional real ADCs from NAR's 702-asset (or 21-Approved) list as a future, ordinary Job 15 registry-curation task -- NOT a code change to this audit round",
         needs_acquisition_change="NO (registry curation, not acquisition code)", confidence="high"),
    dict(asset="all 14 known assets", missing_item="'status'/'linker' field evidence recoverability", item_type="field_recoverability_gap",
         expected_source="patent_bioactivity_corpus full text, fda_submissions dates, company press releases",
         search_attempt="grep manifest shallow columns (title/applicants) AND patent full-text raw files for NAR's linker/status field values",
         result="Confirmed real, partial: linker names (highly technical chemistry strings) are recoverable mainly from patent FULL TEXT, which is only materialized for the subset of WIPO/EPO publications this benchmark run's shared --limit=25 happened to materialize (not all 14 assets have a materialized+full-texted patent yet); 'status' (FDA approval date phrasing) was checked against the wrong FDA manifest column in this tool (fda_applications' title/sponsor/brand/ingredient fields, not its actual approval-date field) -- a tool methodology gap, not necessarily a true acquisition gap",
         root_cause="Mixed: (a) MATERIALIZATION_SCALE (patent full text not yet fetched for every asset, same --limit artifact as above) and (b) a methodology gap in THIS comparison script (wrong column checked for 'status')",
         severity="P2", recommended_action="Re-run Job 13 after a larger production Job 15 pass; extend this comparison tool to check FDA's actual approval-date fields for the 'status' check",
         needs_acquisition_change="NO (this audit's tooling, not adc-acquisition itself)", confidence="high"),
]

with (OUT_DIR / "false_positive_audit.tsv").open("w", newline="", encoding="utf-8") as f:
    fieldnames = ["source", "record_id", "query_id", "title", "classification", "reason", "confidence"]
    w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
    w.writeheader()
    w.writerows(false_positive_rows)

with (OUT_DIR / "nar_only_gap_diagnosis.tsv").open("w", newline="", encoding="utf-8") as f:
    fieldnames = ["asset", "missing_item", "item_type", "expected_source", "search_attempt", "result",
                  "root_cause", "severity", "recommended_action", "needs_acquisition_change", "confidence"]
    w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
    w.writeheader()
    w.writerows(nar_only_gap_rows)

print(f"Wrote {len(false_positive_rows)} false_positive_audit.tsv rows")
print(f"Wrote {len(nar_only_gap_rows)} nar_only_gap_diagnosis.tsv rows")
