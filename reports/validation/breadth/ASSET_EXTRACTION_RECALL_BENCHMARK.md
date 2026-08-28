# Asset-Extraction Recall Benchmark

Per PR #32 (formalizing `nar702_broad_recall.tsv` as a standing asset-extraction benchmark, per the reviewer's explicit request). Answers: of the NAR Phase1+ assets our ACQUISITION system already proved are present in the corpus (`BROAD_DISCOVERED`), how many did our own ASSET EXTRACTOR (`candidate_queue.py` + `tools/catalog/build_adc_asset_universe.py`) actually turn into a `MULTISOURCE_CONFIRMED` catalog entry? A miss here is an extraction-pattern gap, NEVER an acquisition/source gap -- the target set is restricted to assets already proven corpus-present.

Target set (Phase1+ AND BROAD_DISCOVERED): 275
Extractor-matched (MULTISOURCE_CONFIRMED): 188
Extractor recall: 188/275 = 68.4%

Stop criterion: >= 90% -- NOT YET MET.

## Remaining misses, by cause

- DEV_CODE_SHAPED: 75
- UNCOVERED_SUFFIX: 7
- SUFFIX_COVERED_BUT_STILL_MISSED: 3
- OTHER_UNCLASSIFIED: 2

- `DEV_CODE_SHAPED`: development-code-named asset our dev-code signal did not catch in its current corpus text (may be a spelling/format variant the fragment regex doesn't cover, or the grammatical relationship to "ADC"/"antibody-drug conjugate" is looser than this signal's tight-grammar requirement).
- `UNCOVERED_SUFFIX`: a generic two-word name ending in a USAN/INN stem not yet in `ADC_SUFFIX_PAYLOAD_CLASS` (a long tail of single-occurrence stems remains uncovered by design -- only stems confirmed against multiple distinct NAR assets are added).
- `SUFFIX_COVERED_BUT_STILL_MISSED`: the suffix IS documented, but the specific candidate still wasn't exact-matched to this NAR row (e.g. the acquired text only contains an alias/dev-code form, not the canonical generic name itself).
- `OTHER_UNCLASSIFIED`: does not fit the above shape heuristics; needs individual inspection.

Every miss above is classified into one of these categories -- none are attributed to "the corpus doesn't have this asset," since the target set is restricted to assets already proven `BROAD_DISCOVERED`.
