#!/usr/bin/env python3
"""Phase 5e (reports/validation/BREADTH_PLAN.md Phase 5 Parts 5/11):
mines ADC_PLATFORM mentions and upgrades ADC_PAYLOAD/ADC_LINKER evidence
tiers from free text ALREADY acquired in this repo -- no new acquisition
source, no patent-derived mining (explicitly out of scope this phase,
BREADTH_PLAN Part 8).

Three independent mechanisms, all evidence-anchored (a hit requires a
literal, quoted match in already-downloaded text; nothing here is
inferred from a name's shape or guessed):

1. ADC_PLATFORM_KEYWORDS -- a curated, individually-verified dictionary
   of named bioconjugation/antibody-engineering platform terms, built by
   scanning `conference_abstract_corpus`/`pubmed`/`europe_pmc` free text
   for "<term> platform"/"<term> technology" co-occurrences, then reading
   each hit's own surrounding sentence to confirm it is genuinely
   introduced as a named delivery/conjugation technology (e.g. "This ADC
   was prepared using MediLink's TMALIN platform, a proprietary tumor
   microenvironment activable linker-payload platform") -- same
   positive-evidence-only discipline already established for
   ADJACENT_MODALITY_KEYWORDS (Phase 5b) and Job 12's HTML parser
   regexes ("captured directly from a live fetch... verified before
   being written here"). A generic naming-pattern rule ("capitalized
   word immediately before 'platform'") was tried and rejected: of ~80
   distinct pre-tokens found this way in the real corpus, roughly two
   thirds were generic English words/abbreviations/acronyms (ADC, DAR,
   IgG, CRISPR, ISAC, ATAC, This, The, Our, Novel...), not a platform
   brand -- an automatic rule this noisy would misclassify far too often
   for an evidence-gated project. Every entry below has a real quoted
   sentence backing it (see reports/validation/breadth/
   PHASE5E_COMPONENT_FEASIBILITY_UNIVERSE.md section on platform mining
   for the full quote per entry).

   Deliberately EXCLUDED even though found by the same scan: named
   platforms that are NOT antibody/conjugation/delivery technology --
   discovery engines, screening platforms, imaging/spatial-biology
   platforms, biomarker panels, PDX mouse-model platforms (e.g. GNOCLE,
   MIntTM, COMET, OncoPanel, MiniPDX, Cancer DataMiner, iScreener) -- per
   BREADTH_PLAN's own ADC_PLATFORM definition ("a named proprietary
   conjugation/technology platform"), which this module reads narrowly
   as the ADC's own construction technology, not an adjacent research
   tool used somewhere in the same paper. Also excluded: bare "Araris"
   (a company name, not a distinct branded platform term in the one
   abstract where it appeared) and bare "SYN"/"SMAC"/"CAB" (collision-
   prone short forms of SYNtecan E / SMACTM / Conditionally Active
   Biologics -- only the fuller, disambiguating surface form is matched,
   same "ambiguous_identifiers never searched standalone" discipline
   already established for configs/known_adc_assets.yaml).

2. PAYLOAD_TEXT_SIGNALS / LINKER_TEXT_SIGNALS -- per-USAN-suffix literal
   chemistry-name keywords (e.g. "MMAE" for -vedotin, "SPDB" for
   -soravtansine). Used to upgrade a suffix-INFERRED payload/linker to
   TEXT_OBSERVED when the SAME evidence record that discovered a
   candidate ALSO explicitly names that chemistry in the LOCAL context
   (candidate_queue.local_context_for_span()) around that candidate's
   own mention -- never the whole record, for the same cross-
   contamination reason Phase 5b's round-1 fix already established for
   modality keywords.

3. PAYLOAD_MOA_TARGET_BY_SUFFIX -- PAYLOAD_MOA_TARGET (BREADTH_PLAN
   Phase 1's ontology split: the payload's mechanism-of-action target,
   NEVER merged into ADC_TARGET/adc_targets.tsv) is only populated for
   the 6 of 8 suffix classes with an uncontroversial, well-established
   public-pharmacology molecular target (auristatins/maytansinoids ->
   tubulin; SN-38/exatecan derivatives -> topoisomerase I). Deliberately
   left BLANK for ozogamicin (calicheamicin, a DNA-damaging enediyne
   antibiotic) and tesirine (a PBD dimer, a DNA-crosslinking agent) --
   neither has a single discrete protein target in the same sense as the
   other six; asserting one would be a guess this project's evidence-
   gated discipline exists to avoid, not a documented fact.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 3. PAYLOAD_MOA_TARGET (Phase 1 ontology split -- never merged into
#    ADC_TARGET/adc_targets.tsv). Independent public USAN/INN-payload-class
#    pharmacology, not copied from or derived against the NAR vault.
# ---------------------------------------------------------------------------
PAYLOAD_MOA_TARGET_BY_SUFFIX = {
    "vedotin": "Tubulin",
    "mafodotin": "Tubulin",
    "emtansine": "Tubulin",
    "soravtansine": "Tubulin",
    "govitecan": "DNA topoisomerase 1 (TOP1)",
    "deruxtecan": "DNA topoisomerase 1 (TOP1)",
    # "ozogamicin" (calicheamicin) and "tesirine" (PBD dimer) are DNA-damaging
    # agents without a single discrete protein MoA target -- honestly left
    # unmapped rather than guessed.
}

# ---------------------------------------------------------------------------
# 2. Literal chemistry-name signals used to upgrade suffix-INFERRED
#    payload/linker to TEXT_OBSERVED when found in a candidate's own local
#    evidence context. Case-sensitive substrings chosen to avoid matching
#    unrelated prose (e.g. bare "SN" or "DM" would be far too generic).
# ---------------------------------------------------------------------------
PAYLOAD_TEXT_SIGNALS = {
    "vedotin": ["MMAE", "monomethyl auristatin E"],
    "mafodotin": ["MMAF", "monomethyl auristatin F"],
    "emtansine": ["DM1", "mertansine"],
    "soravtansine": ["DM4", "ravtansine"],
    "ozogamicin": ["calicheamicin"],
    "govitecan": ["SN-38", "SN38"],
    "tesirine": ["PBD dimer", "pyrrolobenzodiazepine"],
    "deruxtecan": ["exatecan", "DXd"],
}
LINKER_TEXT_SIGNALS = {
    "vedotin": ["valine-citrulline", "val-cit", "vc linker"],
    "mafodotin": ["maleimidocaproyl"],
    "emtansine": ["SMCC"],
    "soravtansine": ["SPDB"],
    "ozogamicin": ["AcBut"],
    "govitecan": ["CL2A"],
    "tesirine": [],  # no suffix-specific keyword more precise than "cleavable linker" (too generic to be a useful signal)
    "deruxtecan": ["GGFG", "tetrapeptide-based linker", "tetrapeptide linker"],
}


def payload_linker_text_observed(local_context: str, suffix: str) -> tuple[str | None, str | None]:
    """Returns (matched_payload_keyword, matched_linker_keyword) found in
    `local_context` for this suffix's registered signals, or (None, None)
    if neither is present. `local_context` must already be scoped to ONE
    candidate mention (candidate_queue.local_context_for_span()), never a
    whole record."""
    payload_hit = next((kw for kw in PAYLOAD_TEXT_SIGNALS.get(suffix, []) if kw in local_context), None)
    linker_hit = next((kw for kw in LINKER_TEXT_SIGNALS.get(suffix, []) if kw in local_context), None)
    return payload_hit, linker_hit


# ---------------------------------------------------------------------------
# 1. ADC_PLATFORM_KEYWORDS -- curated, individually-verified named
#    bioconjugation/antibody-engineering platforms. canonical_label ->
#    list of literal surface-form variants to match (case-sensitive).
#    Every entry verified live against reports/validation/breadth/
#    PHASE5E_COMPONENT_FEASIBILITY_UNIVERSE.md's quoted evidence.
# ---------------------------------------------------------------------------
ADC_PLATFORM_KEYWORDS: dict[str, list[str]] = {
    "Dolaflexin": ["Dolaflexin"],
    "Dolasynthen": ["Dolasynthen"],
    "Immunosynthen": ["Immunosynthen"],
    "Synthemer": ["Synthemer"],
    "Fleximer": ["Fleximer"],
    "SeriMab": ["SeriMab"],
    "TMALIN": ["TMALIN"],
    "GlycoConnect": ["GlycoConnect", "Glycoconnect"],
    "HydraSpace": ["HydraSpace"],
    "SYNtecan E": ["SYNtecan E", "SyntecanE"],
    "ConjuAll": ["ConjuAll"],
    "AxcynCYS": ["AxcynCYS"],
    "BrickADC": ["BrickADC"],
    "Mtoxin": ["MtoxinTm", "Mtoxin™"],
    "PermaLink": ["PermaLink"],
    "MuSC": ["MuSC™", "MuSCTM"],
    "TMEAlinker": ["TMEAlinker"],
    "StarLinker": ["StarLinkerTM", "StarLinker™"],
    "EuCODE": ["EuCODE"],
    "C-LOCK": ["C-LOCK"],
    "SMAC": ["SMACTM", "SMAC™"],  # bare "SMAC" excluded -- collides with SMAC-mimetic apoptosis literature
    "CROSSCONJU": ["CROSSCONJU", "CrossConju"],
    "ThioBridge": ["ThioBridge"],
    "Azymetric": ["AzymetricTM", "Azymetric™"],
    "CAPAC": ["CAPAC"],
    "Nanolattix Biolattix": ["Nanolattix Biolattix"],
    "Conditionally Active Biologics (CAB)": ["Conditionally Active Biologics", "CAB technology", "CAB-based"],
    "Ligase-Dependent Conjugation (iLDC)": ["Ligase-Dependent Conjugation", "iLDC"],
    "Tub-Tag": ["Tub-Tag"],
}


def find_platform_mentions_in_text(text: str) -> list[tuple[str, str, int, int]]:
    """Returns [(canonical_label, matched_variant, start, end), ...] for
    every ADC_PLATFORM_KEYWORDS surface-form variant literally present in
    `text` -- case-sensitive (these are stylized brand names; a case-
    insensitive match would reintroduce the generic-word collision risk
    this dictionary was built specifically to avoid)."""
    hits = []
    for canonical_label, variants in ADC_PLATFORM_KEYWORDS.items():
        for variant in variants:
            for m in re.finditer(re.escape(variant), text):
                hits.append((canonical_label, variant, m.start(), m.end()))
    return hits
