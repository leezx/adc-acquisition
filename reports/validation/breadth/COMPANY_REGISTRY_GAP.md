# Company Registry Gap Analysis

Reproducible audit (`tools/validation/company_registry_gap_analysis.py`) comparing every distinct company name mentioned by a Phase1+ (`highest_stage` in Approved/Phase3/Phase2/Phase1) row in `DATA/catalog/adc_asset_universe.tsv` against `configs/company_registry.yaml`'s own canonical_name/aliases (exact normalized match only, never fuzzy).

- Companies currently registered: 101
- Distinct Phase1+ sponsor/company names in the catalog: 208
- Of those, already registered: 94
- Of those, NOT registered (the gap): 114

## Top 30 unregistered Phase1+ sponsors, by asset count

Not auto-added -- each still needs the same live research (CIK, official domain, pipeline/press-release/investor-relations URLs) every existing registry entry required.

| Phase1+ assets | Company name | Example assets |
|---|---|---|
| 5 | BSP Pharmaceuticals SpA | Telisotuzumab vedotin; Patritumab deruxtecan; Sacituzumab govitecan; Brentuximab vedotin; Loncastuximab tesirine |
| 5 | Baxter Oncology GmbH | Enfortumab vedotin; Patritumab deruxtecan; Trastuzumab deruxtecan; Oportuzumab monatox; Datopotamab deruxtecan |
| 5 | Shanghai Miracogen Inc | CMG-901; MRG-002; MRG-004A; Becotatug vedotin; MRG-001 |
| 4 | Agensys, Inc | AGS-16C3F; Sirtratumab vedotin; AGS-67E; Vandortuzumab vedotin |
| 4 | Bayer AG | Anetumab ravtansine; BAY-1862864; Aprutumab ixadotin; Lupartumab amadotin |
| 4 | Stemcentrx, Inc | SC-007; Tamrintamab pamozirine; SC-002; Cofetuzumab pelidotin |
| 3 | KLUS Pharma, Inc | Sacituzumab tirumotecan; SKB-315; Trastuzumab botidotin |
| 3 | Novartis AG | HKT-288; PCA-062; LOP-628 |
| 3 | Novartis Pharma AG | HKT-288; NJH-395; LOP-628 |
| 3 | Suzhou Suncadia Biopharmaceuticals Co., Ltd | Trastuzumab rezetecan; SHR-A1921; SHR-A2009 |
| 2 | ARS Pharmaceuticals, Inc | SBT-6290; Pertuzumab zuvotolimod |
| 2 | Amgen, Inc | AMG-224; CDX-014 |
| 2 | BioAtla, Inc | Ozuriftamab vedotin; Mecbotamab vedotin |
| 2 | BioIntegrator LLC | CON-4619; BI-CON-02 |
| 2 | Biocytogen Pharmaceuticals (Beijing) Co., Ltd | RC-118; DM001 |
| 2 | Chugai Pharmaceutical Co., Ltd | Trastuzumab emtansine; Polatuzumab vedotin |
| 2 | EMD Serono Research & Development Institute, Inc | M-1231; M-9140 |
| 2 | Hangzhou Zhongmeihuadong Pharmaceutical Co., Ltd | Mirvetuximab soravtansine; HDP-101 |
| 2 | Immunomedics, Inc | Sacituzumab govitecan; Labetuzumab govitecan |
| 2 | MedImmune LLC | MEDI-3726; MEDI-2228 |
| 2 | MorphoSys AG | Anetumab ravtansine; PCA-062 |
| 2 | Nanjing Shunxin Pharmaceutical Co., Ltd | TQB2103; TQB2102 |
| 2 | Novocodex Biopharmaceuticals Co., Ltd | ARX-305; ARX-788 |
| 2 | Overland Pharmaceutical (Shanghai) Co., Ltd | Loncastuximab tesirine; Mipasetamab uzoptirine |
| 2 | Rakuten Medical, Inc | Cetuximab sarotalocan; RM-1995 |
| 2 | Sichuan Kelun Pharmaceutical Co., Ltd | Sacituzumab tirumotecan; Trastuzumab botidotin |
| 2 | Silverback Therapeutics, Inc | SBT-6290; Pertuzumab zuvotolimod |
| 2 | Synthon BV | SYD-1875; Trastuzumab duocarmazine |
| 2 | Tallac Therapeutics, Inc | TAC-001; ALTA-002 |
| 2 | Wyeth Pharmaceuticals LLC | Gemtuzumab ozogamicin; Inotuzumab ozogamicin |
