#!/usr/bin/env python3
"""Phase 3 (reports/validation/BREADTH_PLAN.md Part 9), extended in Phase 5:
a high-recall DISCOVERY CANDIDATE queue, built entirely from evidence
already in this repo (`configs/known_adc_assets.yaml` +
`DATA/manifests/clinicaltrials.parquet` + `DATA/manifests/
conference_abstract_corpus.parquet`, the last added by Phase 4 and wired in
here in Phase 5) -- still no NEW acquisition source added by this script
itself.

Two-stage design, per Part 9: DISCOVERY CANDIDATE -> VALIDATED FEASIBILITY
ENTITY. This script builds the candidate queue only (`candidate_queue.tsv`);
`tools/breadth/feasibility_entities.py` consumes it and decides what
actually becomes a feasibility entity. Fuzzy-only promotion is explicitly
avoided (Part 9): every candidate here is either (a) already independently
curated/verified (`configs/known_adc_assets.yaml`, carried over from prior
audits), (b) matched via a documented USAN/INN naming-convention stem
against CT.gov's clean, structured `intervention_names` field, or (c)
matched via that SAME stem against conference-abstract free-text prose --
category (c) is a strictly noisier signal than (b) (free text has far more
incidental false-positive co-occurrences than a controlled field) and is
therefore routed to `NEEDS_REVIEW`, never `AUTO_HIGH_CONFIDENCE`, unless a
name is ALSO confirmed via (b).

ADC_SUFFIX_PAYLOAD_CLASS below is public pharmaceutical-nomenclature
knowledge (USAN/INN stems for antibody-drug-conjugate payload/linker
classes), independent of and not copied from the NAR ADCdb benchmark used
in Phases 1-2 -- confirmed empirically against all 8 distinct suffixes
present among our own 14 active known assets' canonical names. This list
is NOT claimed to be exhaustive; newer/rarer stems will still be missed by
design.

PR #31 (BREADTH_PLAN.md addendum) adds a SECOND, independent discovery
signal alongside (b)/(c) above: development-code-named assets (e.g.
"BAT-8008", "TAK-500"), found via a tight grammatical co-occurrence with
"antibody-drug conjugate"/"ADC" in pubmed.parquet/europe_pmc.parquet/
conference_abstract_corpus.parquet free text -- see
build_dev_code_candidates()'s docstring for why this is a categorically
different (and structurally necessary) signal from the USAN/INN suffix
match: a development code carries no payload/linker-class-identifying
suffix at all, so signal (b)/(c) cannot find it by construction, no matter
how many more sources are added. Like (c), this is free-text co-occurrence
and is therefore ALWAYS routed to NEEDS_REVIEW, never auto-promoted.

ROUND-1 FIX: raw CT.gov intervention strings are not clean single-drug
names -- they can be combination-regimen labels ("Pembrolizumab +
Enfortumab Vedotin"), trial-arm labels ("Arm A: Belantamab Mafodotin"), or
radiolabeled-tracer variants ("89Zr-Patritumab deruxtecan"). Matching a
suffix against the WHOLE raw string, and deduplicating on the whole raw
string, both overcounted: known assets slipped through as spurious "new"
candidates, and a radiolabeled variant of a genuinely new candidate could
end up as its own separate, duplicate entity. `extract_adc_generic_name()`
now extracts the canonical two-word generic name FIRST, and every
downstream step (known-asset suppression, suffix lookup, dedup key)
operates on that extracted name, not the raw string.

Usage:
    python3 tools/breadth/candidate_queue.py \
        --known-assets-file configs/known_adc_assets.yaml \
        --data-dir DATA \
        --output DATA/feasibility
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

from adc_acquisition.hashing import sha256_bytes

# Documented USAN/INN stems for antibody-drug-conjugate payload/linker
# classes -- general pharmaceutical-nomenclature knowledge, not derived
# from or copied out of the NAR ADCdb vault used in Phases 1-2. Split into
# separate payload/linker maps (rather than one combined description) so
# tools/breadth/feasibility_entities.py can populate ADC_CANDIDATE's
# distinct payload_if_known/linker_if_known fields directly.
ADC_SUFFIX_PAYLOAD_CLASS = {
    "vedotin": "MMAE (monomethyl auristatin E)",
    "mafodotin": "MMAF (monomethyl auristatin F)",
    "emtansine": "DM1 (maytansinoid)",
    "soravtansine": "DM4 (maytansinoid)",
    "ozogamicin": "calicheamicin",
    "govitecan": "SN-38 (topoisomerase-1 inhibitor, irinotecan metabolite)",
    "tesirine": "a PBD (pyrrolobenzodiazepine) dimer",
    "deruxtecan": "an exatecan derivative (topoisomerase-1 inhibitor)",
    # PR #32 additions -- each confirmed empirically against MULTIPLE
    # distinct NAR reference-universe canonical names (same discipline as
    # the original 8), not a single one-off: "ravtansine" (6 NAR assets,
    # e.g. Indatuximab ravtansine, Anetumab ravtansine, Tusamitamab
    # ravtansine), "mertansine" (3, e.g. Cantuzumab mertansine, Bivatuzumab
    # mertansine -- earlier-generation ImmunoGen DM1 conjugates, publicly
    # documented as using a disulfide-based linker rather than emtansine's
    # later SMCC linker), "talirine" (3, e.g. vadastuximab talirine,
    # Serclutamab talirine), "duocarmazine" (2, e.g. Vobramitamab
    # duocarmazine). Inserted AFTER "soravtansine" so a name ending in
    # "...soravtansine" is still matched to that MORE SPECIFIC suffix
    # first (find_suffix_matches() returns the first dict-order match, and
    # "soravtansine" itself ends in "ravtansine" as a substring).
    "ravtansine": "DM4 (maytansinoid)",
    "mertansine": "DM1 (maytansinoid)",
    "talirine": "a PBD (pyrrolobenzodiazepine) dimer",
    "duocarmazine": "a duocarmycin analog (DNA minor-groove alkylating agent)",
}
ADC_SUFFIX_LINKER_CLASS = {
    "vedotin": "valine-citrulline cleavable linker (typical)",
    "mafodotin": "maleimidocaproyl non-cleavable linker (typical)",
    "emtansine": "SMCC non-cleavable linker (typical)",
    "soravtansine": "SPDB-based cleavable linker (typical)",
    "ozogamicin": "acid-cleavable AcBut linker (typical)",
    "govitecan": "cleavable CL2A linker (typical)",
    "tesirine": "cleavable linker (typical)",
    "deruxtecan": "cleavable GGFG peptide linker (typical)",
    "ravtansine": "SPDB-based cleavable linker (typical)",
    "mertansine": "disulfide-based cleavable linker (typical for earlier -mertansine-class conjugates)",
    "talirine": "cleavable linker (typical)",
    "duocarmazine": "cleavable linker (typical)",
}

NON_DRUG_INTERVENTION_TERMS = {
    "surgery", "radiation therapy", "radiotherapy", "chemotherapy", "placebo", "observation",
    "best supportive care", "biopsy procedure", "quality-of-life assessment", "questionnaire administration",
    "laboratory biomarker analysis", "conventional surgery", "standard of care",
}

# Empirically observed false-positive PREFIX words when scanning free-text
# conference-abstract title+abstract for a "<word> <suffix>" bigram (Phase
# 5: reports/validation/BREADTH_PLAN.md Part 4/9 continuation) -- derived
# directly from a real scan of the 2,456-record conference_abstract_corpus
# (jobs/conference_abstract_corpus), NOT a hypothetical/general English
# stopword list, and NOT claimed exhaustive. This class of false positive
# does not occur for CT.gov's clean intervention_names field (a controlled,
# short field, not free prose) -- e.g. "novel vedotin", "the deruxtecan
# arm", "payload tesirine" are common in abstract prose but never appear as
# a CT.gov intervention_names entry.
TEXT_SCAN_STOPWORD_PREFIXES = {
    "and", "investigational", "to", "payload", "the", "novel", "of", "a", "as", "other",
    "with", "than", "directed", "benchmarking", "free", "fab", "inhibitor", "agent", "drug",
    "validated", "conventional", "established", "eliminate", "by", "included", "against",
    "that", "where", "targeted", "or", "based", "for", "enables", "ev", "ado", "nontargeting",
    "maleimide", "links", "cytotoxins", "control", "concept", "poison", "standard", "exatecan",
    "vcmmae", "mmae", "mmaf", "dxd",
}

# ADC modality taxonomy (Phase 5b, reports/validation/BREADTH_PLAN.md Part
# 5): documented, VERIFIED phrases identifying a conjugate drug class that
# is related to but distinct from a classical antibody-drug conjugate --
# see reports/validation/breadth/ADC_MODALITY_TAXONOMY.md for the full
# taxonomy and why this is a positive-keyword-evidence check, never a
# naming-pattern guess (a "the vehicle word ends in -mab" rule was
# considered and rejected as unsafe -- checked against the real queue and
# found 3 already-CT.gov-confirmed antibody ADCs whose vehicle word does
# NOT end in -mab, which this project cannot verify live). Case-
# insensitive substring match against text LOCAL to one specific
# candidate mention (round-1 fix: the raw intervention string itself for
# CT.gov; a sentence/window around the mention for conference text, via
# local_context_for_span() -- NEVER the whole shared title/abstract,
# which would let one candidate's modality phrase wrongly tag an
# unrelated candidate mentioned elsewhere in the same record), NOT the
# candidate name itself.
ADJACENT_MODALITY_KEYWORDS = {
    "bicycle toxin conjugate": "BICYCLE_TOXIN_CONJUGATE",
    "bicycle drug conjugate": "BICYCLE_TOXIN_CONJUGATE",
    "peptide-drug conjugate": "PEPTIDE_DRUG_CONJUGATE",
    "peptide drug conjugate": "PEPTIDE_DRUG_CONJUGATE",
    "small molecule drug conjugate": "SMALL_MOLECULE_DRUG_CONJUGATE",
    "small-molecule drug conjugate": "SMALL_MOLECULE_DRUG_CONJUGATE",
    "radioligand therapy": "RADIOCONJUGATE",
    "radioconjugate": "RADIOCONJUGATE",
    "degrader-antibody conjugate": "DEGRADER_ANTIBODY_CONJUGATE",
}


def detect_adjacent_modalities(text: str) -> set[str]:
    """Case-insensitive scan of `text` for every ADJACENT_MODALITY_KEYWORDS
    phrase present -- returns the set of matched modality labels (empty if
    none), never a guess from the candidate name's own shape."""
    lowered = text.lower()
    return {label for phrase, label in ADJACENT_MODALITY_KEYWORDS.items() if phrase in lowered}


def load_known_registry(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("assets", [])


def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def known_identifier_set(assets: list[dict]) -> set[str]:
    out = set()
    for a in assets:
        out.add(normalize_name(a["canonical_name"]))
        for alias in a.get("aliases") or []:
            out.add(normalize_name(alias))
        for code in a.get("dev_codes") or []:
            out.add(normalize_name(code))
    return out


def mentions_known_asset(name: str, known_ids: set[str]) -> bool:
    """True if a known asset's identifier is EMBEDDED in this intervention
    string -- CT.gov intervention_names frequently records a combination
    regimen or trial-arm label (e.g. "Pembrolizumab + Enfortumab Vedotin",
    "Arm A: Belantamab Mafodotin") rather than a clean single-drug name.
    An exact normalized-string match alone misses these and would
    otherwise surface an already-known asset as a spurious "new"
    candidate -- confirmed empirically: every messy/combo-looking string
    in an initial run turned out to be exactly this, not a genuinely new
    but messily-labeled candidate. Substring containment (in either
    direction, to also catch a known canonical_name that itself carries
    extra qualifying text) is intentionally used only for this KNOWN-id
    suppression check -- never for asset-to-asset matching/promotion,
    which stays strict elsewhere in this pipeline."""
    normalized = normalize_name(name)
    return any(kid in normalized or normalized in kid for kid in known_ids if len(kid) >= 6)


def find_suffix_matches(name: str) -> str | None:
    normalized = name.lower().strip()
    for suffix in ADC_SUFFIX_PAYLOAD_CLASS:
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            return suffix
    return None


_ALNUM_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def extract_adc_generic_name(raw_name: str) -> str | None:
    """Extract the two-word ADC generic name (antibody-stem word + the
    payload/linker-suffix word) from a raw CT.gov intervention string,
    discarding combination-regimen partners, trial-arm labels, and
    radiolabel/isotope prefixes -- e.g.:

      "Pembrolizumab + Enfortumab Vedotin"  -> "Enfortumab Vedotin"
      "Arm A: Ladiratuzumab vedotin"        -> "Ladiratuzumab vedotin"
      "89Zr-Patritumab deruxtecan"          -> "Patritumab deruxtecan"

    Works by tokenizing on any non-alphanumeric character (so "+", "-",
    ":", "," all act as separators) and taking the LAST adjacent token
    pair where the second token ends in a documented ADC suffix -- an
    isotope-label token (e.g. "89Zr") is never adjacent to the suffix
    token itself, so it is dropped without any separate isotope-specific
    stripping logic. Returns None if no such pair exists (e.g. a bare
    suffix word with nothing preceding it, or no suffix at all) -- a raw
    string with no extractable generic name is not a usable candidate."""
    tokens = _ALNUM_TOKEN_RE.findall(raw_name)
    match = None
    for i in range(len(tokens) - 1):
        second = tokens[i + 1]
        if any(second.lower().endswith(suffix) for suffix in ADC_SUFFIX_PAYLOAD_CLASS):
            match = f"{tokens[i]} {tokens[i + 1]}"
    return match


def _iter_adc_generic_name_matches(text: str):
    """Yields (label, start, end) for every valid adjacent token-pair match
    in `text` -- same filter rules as extract_all_adc_generic_names_from_text()
    (below), which is a thin dedup wrapper around this. `start`/`end` are
    the character span of the matched "first second" pair WITHIN `text`,
    exposed so a caller (Phase 5b's modality classification) can localize
    evidence to just THIS ONE mention, not the whole record -- unlike
    extract_all_adc_generic_names_from_text()'s deduped list, every
    occurrence is yielded here (not just the first), since a candidate
    mentioned twice in one record can have modality evidence near either
    occurrence.

    Filter rules -- the prefix token is dropped if:
    - it's a documented TEXT_SCAN_STOPWORD_PREFIXES false positive
      (case-insensitive) -- necessary here in a way it is NOT for
      extract_adc_generic_name(), because free prose contains far more
      incidental "<common word> <suffix>" co-occurrences than a
      controlled, short intervention-name field does (verified
      empirically against the real corpus: "novel vedotin", "the
      deruxtecan arm", "payload tesirine", etc.);
    - it IS ITSELF one of the documented ADC_SUFFIX_PAYLOAD_CLASS suffix
      words (e.g. "emtansine deruxtecan", "exatecan deruxtecan" --
      prose listing two payload/chemistry classes side by side, not an
      antibody-stem name);
    - it's purely numeric (e.g. "38 govitecan" -- a page/volume/dose
      number the suffix word happens to follow, not a name); or
    - it's shorter than 5 characters (every real USAN/INN antibody-stem
      word in this corpus is well over that; short prefixes observed in
      practice are abbreviation fragments like "E vedotin", "M
      Deruxtecan", not full names)."""
    tokens = list(_ALNUM_TOKEN_RE.finditer(text))
    for i in range(len(tokens) - 1):
        first_m, second_m = tokens[i], tokens[i + 1]
        first, second = first_m.group(), second_m.group()
        first_lower = first.lower()
        if first_lower in TEXT_SCAN_STOPWORD_PREFIXES or first_lower in ADC_SUFFIX_PAYLOAD_CLASS:
            continue
        if first.isdigit() or len(first) < 5:
            continue
        if any(second.lower().endswith(suffix) for suffix in ADC_SUFFIX_PAYLOAD_CLASS):
            yield f"{first} {second}", first_m.start(), second_m.end()


def extract_all_adc_generic_names_from_text(text: str) -> list[str]:
    """Like extract_adc_generic_name(), but for free-text PROSE (a
    conference abstract's title+abstract) that can genuinely mention
    MULTIPLE distinct ADC generic names in one record -- returns every
    DISTINCT name found by _iter_adc_generic_name_matches() (deduplicated
    by normalized form, first-seen casing kept), not just the last one the
    way extract_adc_generic_name() does for a short CT.gov intervention
    string."""
    seen: dict[str, str] = {}
    for label, _start, _end in _iter_adc_generic_name_matches(text):
        seen.setdefault(normalize_name(label), label)
    return list(seen.values())


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def local_context_for_span(text: str, start: int, end: int, window: int = 300) -> str:
    """Text most likely to be evidence FOR one specific candidate mention
    (its `[start, end)` character span within a longer record's full
    text) -- round-1 fix for a real cross-contamination bug: modality
    keywords were previously detected against the WHOLE title+abstract
    and applied to EVERY candidate extracted from that record, so one
    candidate's own adjacent-modality phrase (e.g. "Bicycle Toxin
    Conjugate") could wrongly tag a completely unrelated candidate
    mentioned elsewhere in the same abstract -- which the promotion gate
    would then use to permanently exclude a genuinely strict ADC.

    Takes the INTERSECTION of two independent boundings, because either
    one alone can fail: (1) the sentence containing the mention (split on
    [.!?] followed by whitespace -- a deliberately over-eager splitter:
    a FALSE split only narrows the window, which is safe for this
    purpose, while a MISSED split would let a different candidate's
    context leak back in, which is not); (2) a fixed +/-`window`
    character radius, bounding the worst case where sentence splitting
    finds no nearby boundary at all (e.g. one long unpunctuated run)."""
    boundaries = [m.end() for m in _SENTENCE_SPLIT_RE.finditer(text)]
    sentence_start = max((b for b in boundaries if b <= start), default=0)
    sentence_end = min((b for b in boundaries if b >= end), default=len(text))
    fixed_start = max(0, start - window)
    fixed_end = min(len(text), end + window)
    lo = max(sentence_start, fixed_start)
    hi = min(sentence_end, fixed_end)
    return text[lo:hi]


# PR #31 (BREADTH_PLAN.md addendum): a SECOND, INDEPENDENT discovery
# signal, alongside the USAN/INN suffix signal above -- catches ADC assets
# whose name is an alphanumeric DEVELOPMENT CODE (e.g. "BAT-8008",
# "TAK-500", "ADCT-901", "GQ-1001", "DXC-004A", "ZL-6201" -- all real NAR
# reference-universe assets the suffix signal structurally cannot find,
# since none end in a documented USAN/INN payload-class stem). Reused
# across pubmed.parquet/europe_pmc.parquet/conference_abstract_corpus.parquet
# title+abstract text (the only sources with inline text in their committed
# manifests -- company_press_release/company_pipeline/company_scientific_
# presentations reference raw_file_path on disk, not inline text, and
# DATA/raw/ is gitignored/not reproducible from a fresh clone, so scanning
# those is explicitly deferred pending a materialized full-text companion
# table, same pattern as europe_pmc_fulltext.parquet).
#
# A development-code-shaped token is extremely common and mostly NOT a
# drug (clinical trial acronyms like "KEYNOTE-057"/"TROPiCS-02", cell
# lines like "MB-231"/"HCT-116", target/biomarker symbols like
# "CD-30"/"PSMA-617"/"COVID-19" all match the same alphanumeric-code
# shape) -- a loose same-sentence/window co-occurrence with "ADC"/
# "antibody-drug conjugate" was tried FIRST and rejected: verified against
# the real corpus, it produced 542 candidate tokens, the large majority of
# which were exactly this class of false positive. The patterns below
# instead require a TIGHT grammatical relationship -- the code must
# either be the explicit subject of "<code> is/was a(n) ... ADC" (e.g.
# "TAK-500 is a novel immune cell-directed antibody-drug conjugate"),
# immediately follow "ADC"/"antibody-drug conjugate" as its named referent
# (e.g. "the ADC candidate BAT-8008"), or appear in an APPOSITIVE
# construction with no is/was verb (e.g. "ZL-6201, a novel LRRC15-
# targeting antibody drug conjugate (ADC)" -- PR #32 addition, a real,
# common conference-abstract-title construction the original two patterns
# did not cover) -- verified against the real corpus to cut the loose scan
# down to 117 tokens (original two patterns) / 463 tokens (with the
# appositive pattern + hyphen-optional fragment below), spot-checked as
# essentially all genuine development codes.
#
# PR #32: the fragment itself now also matches WITHOUT a hyphen (e.g.
# "BAT8008", the exact real-text spelling that caused BAT-8008 to be
# missed in PR #31 -- confirmed via reports/validation/breadth/
# nar702_broad_recall.tsv that BAT-8008 is genuinely present in the
# acquired corpus, just spelled without its hyphen there). The hyphenless
# branch requires >=3 digits (vs. >=2 for the hyphenated branch) as the
# false-positive guard a hyphen boundary would otherwise provide --
# verified empirically this excludes "HER2"/"CD30"/"IL15"/"COVID19"-class
# target/biomarker symbols (1-2 digits) while still matching genuine
# hyphenless codes like "BAT8008"/"GQ1001"/"HKT288" (3+ digits).
# Round-1-of-PR#32 fix: two more real dev-code shapes found in the real
# corpus but missed by the original fragment -- a single letter directly
# after the hyphen, before the digit run (e.g. "SHR-A2102", "BG-C0902",
# "ADCE-B05"), and a single-UPPERCASE-LETTER-ONLY hyphenless prefix (e.g.
# "M7437" -- the original hyphenless prefix required >=2 characters, one
# wildcard + one mandatory uppercase, so a bare single letter never
# matched). `_DEV_CODE_PREFIX` unifies both fragments' prefix shape: 0-3
# wildcard alnum chars, exactly one MANDATORY uppercase letter (never
# relaxed -- this is what excludes all-lowercase/all-digit false
# positives like page ranges or p-values), then 0-3 more wildcard chars.
_DEV_CODE_PREFIX = r"[A-Za-z0-9]{0,3}[A-Z][A-Za-z0-9]{0,3}"
# Round-2-of-PR#32 fix (reviewer-identified identity-correctness blocker):
# some real ADC identifiers are a TWO-SEGMENT compound
# "<COMPANY_CODE>-<MOLECULE_CODE>" (e.g. "REGN5093-M114", "HRA00129-C004"
# -- a company/platform antibody code, a hyphen, then a payload/conjugate-
# specific molecule code). Each segment on its own is independently
# dev-code-shaped, so without a dedicated compound alternative the single-
# segment alternatives below match each half as a SEPARATE fragment
# (confirmed empirically: `_DEV_CODE_FRAGMENT.finditer("REGN5093-M114")`
# returned two non-overlapping matches, "REGN5093" and "M114") -- which is
# an identity-correctness bug, not a recall gap: it fabricates two
# candidate entities where the real corpus only ever discusses ONE (every
# "REGN5093"/"M114"/"HRA00129..HRA00130"/"C004" occurrence in the real
# acquired corpus is the FULL compound form -- verified directly against
# europe_pmc.parquet/conference_abstract_corpus.parquet before writing this
# fix), and collapses genuinely DISTINCT compounds that happen to share a
# molecule-code suffix (four distinct real "HRA*-C004" candidates --
# HRA00129/HRA00184/HRA00242/HRA00130 -- were all being written as one
# "C004" row, since normalize_name() strips the hyphen and the truncated
# trailing fragment alone carries no company-code half to disambiguate).
#
# `_DEV_CODE_SEGMENT` requires a digit run be present WITHIN the segment
# (unlike the hyphenated-single alternative's optional single letter after
# the hyphen), so the compound alternative can ONLY fire when BOTH halves
# independently look like a full dev-code segment -- it does not fire for
# an ordinary single hyphenated code like "SHR-A2102" or "BAT-8008" (the
# "SHR"/"BAT" half has no digit run of its own, so `_DEV_CODE_SEGMENT`
# fails to match it, and the alternation falls through to the existing
# single-segment alternatives exactly as before). Placed FIRST in the
# alternation so the regex engine's ordered-alternative matching prefers
# the longest, fully-compound form at a given start position over either
# single-segment alternative -- this is what makes the full compound
# ("REGN5093-M114") the atomic candidate label instead of either half, and
# lets it correctly join the existing exact-identifier NAR-resolution path
# (NAR's own record for REGN5093-M114 already lists "REGN5093M114"/
# "REGN 5093 M114"/"REGN5093- M114" as synonyms, all of which normalize
# to the same string as this compound label).
#
# Deliberately NOT extended to three-or-more-segment names (out of scope
# for this fix, per the reviewer's explicit instruction) -- a name like
# that remains the disclosed, deferred limitation.
_DEV_CODE_SEGMENT = rf"{_DEV_CODE_PREFIX}\d{{2,7}}[A-Za-z]{{0,2}}"
_DEV_CODE_COMPOUND_FRAGMENT = rf"{_DEV_CODE_SEGMENT}-{_DEV_CODE_SEGMENT}"
_DEV_CODE_FRAGMENT = (
    rf"(?:{_DEV_CODE_COMPOUND_FRAGMENT}"
    rf"|{_DEV_CODE_PREFIX}-[A-Za-z]?\d{{2,7}}[A-Za-z]{{0,2}}"
    rf"|{_DEV_CODE_PREFIX}\d{{3,7}}[A-Za-z]{{0,2}})"
)
_DEV_CODE_ADC_CODE_FIRST_RE = re.compile(
    rf"\b({_DEV_CODE_FRAGMENT})\b,?\s+(?:is|was)\s+(?:an?\s+)?"
    r"(?:novel\s+|investigational\s+|first-in-class\s+)*(?:(?i:antibody[- ]drug conjugate)|ADC)\b"
)
_DEV_CODE_ADC_TERM_FIRST_RE = re.compile(
    rf"\b(?:(?i:antibody[- ]drug conjugate)|ADC)\b(?:\s+candidate)?,?\s+({_DEV_CODE_FRAGMENT})\b"
)
# PR #32: appositive construction, no is/was verb -- the word-count cap
# ({0,6} words between "a/an" and the ADC term) bounds the match to a
# short descriptive phrase (e.g. "a novel LRRC15-targeting"), not an
# arbitrary run-on across unrelated sentence content.
_DEV_CODE_ADC_APPOSITIVE_RE = re.compile(
    rf"\b({_DEV_CODE_FRAGMENT})\b,\s+(?:a|an)\s+(?:[A-Za-z0-9/-]+\s+){{0,6}}?(?:(?i:antibody[- ]drug conjugate)|ADC)\b"
)
# A prefix like "5E"/"1E" in "5E-33"/"1E-32" is scientific notation (a
# p-value), not a development code -- the only false-positive CLASS the
# tight grammatical pattern above did not already rule out empirically.
_SCI_NOTATION_PREFIX_RE = re.compile(r"^\d*[Ee]$")


def _iter_dev_code_adc_mentions(text: str):
    """Yields (code, start, end) for every developement-code+ADC-context
    match in `text`, deduplicated by character span (the patterns can
    both match the same code at the same position from opposite
    directions in some phrasings)."""
    seen_spans: set[tuple[int, int]] = set()
    for pattern in (_DEV_CODE_ADC_CODE_FIRST_RE, _DEV_CODE_ADC_TERM_FIRST_RE, _DEV_CODE_ADC_APPOSITIVE_RE):
        for m in pattern.finditer(text):
            code = m.group(1)
            # Scientific-notation guard only applies to the hyphenated
            # form ("5E-33"/"1E-32", a p-value) -- the hyphenless fragment
            # already requires >=3 trailing digits, which no realistic
            # scientific-notation exponent in this corpus's prose has.
            prefix = code.split("-", 1)[0]
            if _SCI_NOTATION_PREFIX_RE.match(prefix):
                continue
            span = m.span(1)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            yield code, span[0], span[1]


def build_dev_code_candidates(manifest: pd.DataFrame, source_name: str, known_ids: set[str]) -> dict[str, dict]:
    """Same output shape as build_ctgov_suffix_candidates()/
    build_conference_suffix_candidates() (nct_ids/conference_ids/phases/
    contexts/first_seen/sources/adjacent_modalities), so it can flow
    through the SAME merge/promotion pipeline below, keyed by the
    development code itself rather than a generic two-word name.

    known-asset suppression here is EXACT normalized match, not
    mentions_known_asset()'s substring containment: a development code
    (e.g. "SGN-35") is the candidate's ENTIRE label, not a longer wrapper
    string a known name might be embedded in, and containment's >=6-char
    safety threshold (needed there to avoid short-fragment false matches
    against a longer name) would let a 5-character code like "SGN-35"
    (normalize_name -> "sgn35") slip through unsuppressed even though it
    is exactly Brentuximab vedotin's own registered dev_code.

    PR #32 fix: a dev code belonging to an already-discovered SUFFIX-
    matched candidate (e.g. "CDX-011" is glembatumumab vedotin's own dev
    code) is now caught by `parenthetical_alias_crosswalk()` below and
    merged into that candidate rather than appearing here as a separate
    entry -- this function itself is unchanged, the caller in main()
    applies the crosswalk before/after this function runs."""
    candidates: dict[str, dict] = {}
    for _, row in manifest.iterrows():
        title = row.get("title") or ""
        abstract = row.get("abstract") or ""
        text = f"{title} {abstract}"
        for code, start, end in _iter_dev_code_adc_mentions(text):
            if normalize_name(code) in known_ids:
                continue
            key = normalize_name(code)
            entry = candidates.setdefault(key, dict(
                label=code, nct_ids=set(), conference_ids=set(), phases=set(),
                first_seen=None, contexts=set(), sources=set(), adjacent_modalities=set(),
            ))
            entry["sources"].add(source_name)
            entry["conference_ids"].add(row["source_record_id"])
            entry["contexts"].add(str(title)[:150])
            local_context = local_context_for_span(text, start, end)
            entry["adjacent_modalities"] |= detect_adjacent_modalities(local_context)
            date = _clean_date_string(row.get("publication_or_release_date"))
            if date and (entry["first_seen"] is None or date < entry["first_seen"]):
                entry["first_seen"] = date
    return candidates


def merge_dev_code_candidates(*candidate_dicts: dict[str, dict]) -> dict[str, dict]:
    """Same idea as merge_suffix_candidates(), for dev-code candidates
    (no `suffix` field to carry, so kept as its own small function rather
    than overloading that one with an optional field)."""
    merged: dict[str, dict] = {}
    for candidates in candidate_dicts:
        for key, c in candidates.items():
            entry = merged.setdefault(key, dict(
                label=c["label"], nct_ids=set(), conference_ids=set(),
                phases=set(), contexts=set(), first_seen=None, sources=set(), adjacent_modalities=set(),
            ))
            entry["sources"] |= c["sources"]
            entry["nct_ids"] |= c["nct_ids"]
            entry["conference_ids"] |= c["conference_ids"]
            entry["phases"] |= c["phases"]
            entry["contexts"] |= c["contexts"]
            entry["adjacent_modalities"] |= c["adjacent_modalities"]
            if c["first_seen"] and (entry["first_seen"] is None or c["first_seen"] < entry["first_seen"]):
                entry["first_seen"] = c["first_seen"]
    return merged


_DEV_CODE_FULL_MATCH_RE = re.compile(rf"^{_DEV_CODE_FRAGMENT}$")
# "antibody[- ]drug conjugate" is matched case-insensitively (CT.gov
# titles are often title-cased, e.g. "Antibody Drug Conjugate"); the bare
# "ADC" abbreviation stays case-SENSITIVE (uppercase-only) to avoid
# matching a stray lowercase "adc" substring inside an unrelated word.
_ADC_PHRASE_RE = re.compile(r"antibody[- ]drug conjugate", re.IGNORECASE)
_ADC_ABBREVIATION_RE = re.compile(r"\bADC\b")


def _has_adc_context(text: str) -> bool:
    return bool(_ADC_PHRASE_RE.search(text) or _ADC_ABBREVIATION_RE.search(text))


def build_ctgov_dev_code_candidates(ct_manifest: pd.DataFrame, known_ids: set[str]) -> dict[str, dict]:
    """PR #32: a THIRD path to the same dev-code candidate shape, using
    CT.gov's clean, structured `intervention_names` field instead of free
    prose. Unlike build_dev_code_candidates() (which requires a TIGHT
    grammatical relationship because free text is noisy), a controlled
    field entry that is ITSELF exactly development-code-shaped (a full-
    string match, not embedded in a sentence) only needs the SAME trial's
    own brief_title/official_title/conditions to independently establish
    ADC context -- verified against the real corpus (669 dev-code-shaped
    intervention_names entries total, 55 with real ADC context in the
    same trial's own title/conditions fields, spot-checked as genuine
    -- e.g. STRO-002, SKB264 -- not clinical-trial-acronym noise, since
    intervention_names is a controlled drug-name field, not free prose)."""
    candidates: dict[str, dict] = {}
    for _, row in ct_manifest.iterrows():
        names = row.get("intervention_names")
        if names is None:
            continue
        conditions = row.get("conditions")
        cond_text = " ".join(str(c) for c in conditions) if conditions is not None else ""
        trial_context = f"{row.get('brief_title') or ''} {row.get('official_title') or ''} {cond_text}"
        if not _has_adc_context(trial_context):
            continue
        for raw_name in names:
            if not raw_name:
                continue
            code = str(raw_name).strip()
            if not _DEV_CODE_FULL_MATCH_RE.match(code):
                continue
            if normalize_name(code) in known_ids:
                continue
            key = normalize_name(code)
            entry = candidates.setdefault(key, dict(
                label=code, nct_ids=set(), conference_ids=set(), phases=set(),
                first_seen=None, contexts=set(), sources={"clinicaltrials"}, adjacent_modalities=set(),
            ))
            entry["nct_ids"].add(row["nct_id"])
            entry["contexts"].add(str(row.get("brief_title") or "")[:150])
            entry["adjacent_modalities"] |= detect_adjacent_modalities(trial_context)
            posted = _clean_date_string(row.get("study_first_post_date"))
            if posted and (entry["first_seen"] is None or posted < entry["first_seen"]):
                entry["first_seen"] = posted
    return candidates


_CODE_BEFORE_PAREN_RE = re.compile(rf"\b({_DEV_CODE_FRAGMENT})\s*\(([^)]{{1,80}})\)")


def parenthetical_alias_crosswalk(
    text_corpora: list[tuple[pd.DataFrame, list[str]]], candidate_labels: list[str],
) -> dict[str, set[str]]:
    """PR #32 (deterministic alias/dev-code crosswalk, per the reviewer's
    explicit request): scientific text overwhelmingly cross-references an
    already-named ADC and its development code via direct parenthetical
    co-reference -- "glembatumumab vedotin (CDX-011)" / "CDX-011
    (glembatumumab vedotin)" -- verified against the real corpus for
    exactly this case (7 real europe_pmc/conference_abstract_corpus
    occurrences found). This is TEXT-EVIDENCE-derived, never a hardcoded
    external pharma-knowledge crosswalk: `candidate_labels` is every
    label ALREADY discovered by the suffix/known-registry signals (never
    guessed), and only a dev-code-shaped token found directly adjacent in
    parentheses to one of those labels is recorded as its alias.

    Performance note: an earlier version compiled one `label\\s*\\(...\\)
    |...\\s*\\(label\\)` regex PER candidate label and ran all of them
    against every row -- the second (code-comes-first) branch has no
    literal anchor before its bounded `[^)]{1,80}` quantifier, so the
    engine retries it at every character position, costing ~1.5ms per
    (label, row) pair regardless of match -- with dozens of labels across
    tens of thousands of rows this took 10+ minutes. Fixed by making
    exactly ONE pass per row: one combined-alternation regex anchored on
    the (fast, literal) label text for the "label (code)" direction, and
    one regex anchored on the (fast, bounded) dev-code fragment for the
    "code (label)" direction, checking the parenthetical content against
    the label set via an O(1) dict lookup in Python instead of a second
    per-label regex.

    Returns {normalize_name(candidate_label): {alias_code, ...}}. Does
    NOT resolve typo/misspelling duplicates (e.g. "Trastuzmab
    deruxtecan") -- those have no parenthetical co-reference to exploit
    and remain the disclosed, deferred limitation from PR #30/#31."""
    aliases: dict[str, set[str]] = {}
    if not candidate_labels:
        return aliases
    normalized_label_keys = {normalize_name(label) for label in candidate_labels}
    label_before_paren_re = re.compile(
        r"\b(" + "|".join(re.escape(label) for label in candidate_labels) + r")\s*\(([^)]{1,80})\)",
        re.IGNORECASE,
    )

    for df, cols in text_corpora:
        if df.empty:
            continue
        for row in df.itertuples(index=False):
            text = " ".join(str(getattr(row, c, "") or "") for c in cols)
            for m in label_before_paren_re.finditer(text):
                key = normalize_name(m.group(1))
                for piece in re.split(r"[;,]", m.group(2)):
                    piece = piece.strip()
                    if _DEV_CODE_FULL_MATCH_RE.match(piece):
                        aliases.setdefault(key, set()).add(piece)
            for m in _CODE_BEFORE_PAREN_RE.finditer(text):
                code = m.group(1)
                if _SCI_NOTATION_PREFIX_RE.match(code.split("-", 1)[0]):
                    continue
                for piece in re.split(r"[;,]", m.group(2)):
                    piece_key = normalize_name(piece.strip())
                    if piece_key in normalized_label_keys:
                        aliases.setdefault(piece_key, set()).add(code)
    return aliases


def apply_alias_crosswalk(
    suffix_candidates: dict[str, dict], dev_code_candidates: dict[str, dict], alias_crosswalk: dict[str, set[str]],
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Merges every dev-code candidate whose key is a discovered alias of
    an existing suffix candidate (per parenthetical_alias_crosswalk())
    INTO that suffix candidate's own evidence (sources/nct_ids/
    conference_ids/contexts/adjacent_modalities/first_seen), then removes
    it from dev_code_candidates so it is never emitted as a separate,
    duplicate row. Returns (updated_suffix_candidates,
    remaining_dev_code_candidates) -- both new dicts, inputs untouched.

    This can genuinely upgrade a suffix candidate's own validation_status
    (e.g. a conference-only NEEDS_REVIEW candidate whose dev-code alias
    was independently found in clinicaltrials.parquet gains a
    "clinicaltrials" source), which is correct: it IS new, independent
    evidence for that same real asset, not a coincidence."""
    code_to_owner_key = {
        normalize_name(alias): owner_key
        for owner_key, aliases in alias_crosswalk.items() for alias in aliases
    }
    suffix_candidates = {k: dict(v) for k, v in suffix_candidates.items()}
    for k, v in suffix_candidates.items():
        for field in ("nct_ids", "conference_ids", "phases", "contexts", "sources", "adjacent_modalities"):
            suffix_candidates[k][field] = set(v[field])

    remaining_dev_code: dict[str, dict] = {}
    for dev_key, dev_entry in dev_code_candidates.items():
        owner_key = code_to_owner_key.get(dev_key)
        if owner_key is None or owner_key not in suffix_candidates:
            remaining_dev_code[dev_key] = dev_entry
            continue
        owner = suffix_candidates[owner_key]
        owner["sources"] |= dev_entry["sources"]
        owner["nct_ids"] |= dev_entry["nct_ids"]
        owner["conference_ids"] |= dev_entry["conference_ids"]
        owner["contexts"] |= dev_entry["contexts"]
        owner["adjacent_modalities"] |= dev_entry["adjacent_modalities"]
        if dev_entry["first_seen"] and (owner["first_seen"] is None or dev_entry["first_seen"] < owner["first_seen"]):
            owner["first_seen"] = dev_entry["first_seen"]
    return suffix_candidates, remaining_dev_code


def _clean_date_string(value) -> str | None:
    """round-1 fix: a parquet column's missing value can be a float NaN,
    not None or an empty string -- `if value:` treats NaN as TRUTHY
    (`bool(float("nan"))` is `True` in Python), so the old `if date: ...
    str(date)` pattern silently wrote the literal string "nan" as
    first_seen for an undated record instead of leaving it blank.
    Verified live: 3 real candidate_queue.tsv rows had first_seen="nan"
    before this fix (all from AACR 2026's undated records)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def candidate_id_for_name(name: str) -> str:
    """Source-independent, persistent candidate identity -- depends ONLY
    on the canonical normalized name, NEVER on which source(s) discovered
    it. round-1 fix: the previous scheme picked candidate_id's PREFIX
    (CTGOV_SUFFIX_ vs CONFERENCE_SUFFIX_) based on whether clinicaltrials
    evidence was present, so the SAME real candidate got a different id
    depending on run-to-run source availability -- e.g. a name seen only
    in a conference abstract first, then later also confirmed on CT.gov,
    would appear to Phase 6's delta system as "old candidate disappeared,
    new candidate appeared" instead of "same candidate, new evidence
    source, status upgraded". This is the identity contract Phase 6's
    twice-monthly delta depends on, fixed now (before Phase 6 exists) per
    the reviewer's explicit call: an intentional, one-time migration of
    the 16 existing CTGOV_SUFFIX_* ids to this scheme, not a compatibility
    shim -- the hash portion is unchanged (still
    sha256(normalize_name(name))[:12]), only the prefix text changes."""
    key = normalize_name(name)
    return f"ADC_SUFFIX_{sha256_bytes(key.encode('utf-8'))[:12]}"


def build_ctgov_suffix_candidates(ct_manifest: pd.DataFrame, known_ids: set[str]) -> dict[str, dict]:
    """One aggregated candidate per distinct EXTRACTED generic name (across
    all trials that mention it), keyed by normalized extracted name --
    never split into fuzzy near-duplicates, never merged across genuinely
    different names. Matching against `known_ids` and the suffix lookup
    both operate on the extracted name, not the raw intervention string,
    so a combination-regimen/arm-label/radiolabel wrapper around an
    already-known asset is correctly suppressed, and a radiolabeled
    variant of a NEW candidate correctly merges into that same candidate
    rather than becoming a separate, spurious entity."""
    candidates: dict[str, dict] = {}
    for _, row in ct_manifest.iterrows():
        names = row.get("intervention_names")
        if names is None:
            continue
        for raw_name in names:
            if not raw_name or raw_name.lower().strip() in NON_DRUG_INTERVENTION_TERMS:
                continue
            extracted = extract_adc_generic_name(raw_name)
            if not extracted:
                continue
            if mentions_known_asset(extracted, known_ids):
                continue
            suffix = find_suffix_matches(extracted)
            if not suffix:
                continue
            key = normalize_name(extracted)
            entry = candidates.setdefault(key, dict(
                label=extracted, suffix=suffix, nct_ids=set(), conference_ids=set(), phases=set(),
                first_seen=None, contexts=set(), sources={"clinicaltrials"}, adjacent_modalities=set(),
            ))
            entry["nct_ids"].add(row["nct_id"])
            phases = row.get("phases")
            if phases is not None:
                for p in phases:
                    entry["phases"].add(p)
            brief_title = str(row.get("brief_title") or "")
            entry["contexts"].add(brief_title[:150])
            # round-1 fix: modality evidence must be attributed to THIS
            # intervention mention only, not the row's shared brief_title
            # -- a CT.gov brief_title can describe multiple interventions/
            # arms/comparators, so scanning it and applying the result to
            # every intervention extracted from that row risked tagging
            # an unrelated intervention with another one's modality.
            # raw_name (this specific intervention string) is inherently
            # local to this one mention, unlike the row's shared title.
            entry["adjacent_modalities"] |= detect_adjacent_modalities(raw_name)
            posted = _clean_date_string(row.get("study_first_post_date"))
            if posted and (entry["first_seen"] is None or posted < entry["first_seen"]):
                entry["first_seen"] = posted
    return candidates


def build_conference_suffix_candidates(conf_manifest: pd.DataFrame, known_ids: set[str]) -> dict[str, dict]:
    """Same idea as build_ctgov_suffix_candidates(), but scanning
    conference_abstract_corpus's title+abstract free text instead of
    CT.gov's structured intervention_names field. Uses
    _iter_adc_generic_name_matches() directly (every OCCURRENCE, not the
    deduplicated list extract_all_adc_generic_names_from_text() returns)
    since one abstract can genuinely discuss more than one ADC, and the
    same candidate can be mentioned more than once with modality evidence
    near only one occurrence. Returns the SAME dict shape (merged with
    CT.gov's candidates by tools/breadth/candidate_queue.py's main(),
    keyed by normalized extracted name) so a name found by BOTH sources
    becomes one entity with combined evidence, not two.

    round-1 fix: modality evidence is attributed via
    local_context_for_span() -- the sentence/window AROUND this specific
    mention, never the whole title+abstract -- so a modality-identifying
    phrase near one candidate (e.g. "Zelenectide pevedotin is a Bicycle
    Toxin Conjugate...") cannot wrongly tag an unrelated candidate
    mentioned elsewhere in the same abstract (e.g. "...Trastuzumab
    deruxtecan was used as comparator")."""
    candidates: dict[str, dict] = {}
    for _, row in conf_manifest.iterrows():
        title = row.get("title") or ""
        abstract = row.get("abstract") or ""
        text = f"{title} {abstract}"
        for extracted, start, end in _iter_adc_generic_name_matches(text):
            if mentions_known_asset(extracted, known_ids):
                continue
            suffix = find_suffix_matches(extracted)
            if not suffix:
                continue
            key = normalize_name(extracted)
            entry = candidates.setdefault(key, dict(
                label=extracted, suffix=suffix, nct_ids=set(), conference_ids=set(), phases=set(),
                first_seen=None, contexts=set(), sources={"conference_abstract_corpus"}, adjacent_modalities=set(),
            ))
            entry["conference_ids"].add(row["source_record_id"])
            entry["contexts"].add(str(title)[:150])
            local_context = local_context_for_span(text, start, end)
            entry["adjacent_modalities"] |= detect_adjacent_modalities(local_context)
            date = _clean_date_string(row.get("publication_or_release_date"))
            if date and (entry["first_seen"] is None or date < entry["first_seen"]):
                entry["first_seen"] = date
    return candidates


def status_and_confidence_for_sources(sources: set[str]) -> tuple[str, str]:
    """Decide validation_status/confidence purely from WHICH sources
    contributed evidence for a suffix-matched candidate -- never from
    which source happened to be discovered/processed first, so the SAME
    candidate's status upgrades in place (NEEDS_REVIEW ->
    AUTO_HIGH_CONFIDENCE) the instant clinicaltrials evidence appears,
    rather than looking like two different candidates. Paired with
    candidate_id_for_name()'s source-independent identity -- see that
    docstring for why this stability matters for Phase 6's delta
    system."""
    if "clinicaltrials" in sources:
        return "AUTO_HIGH_CONFIDENCE", "high"
    return "NEEDS_REVIEW", "medium"


def merge_suffix_candidates(*candidate_dicts: dict[str, dict]) -> dict[str, dict]:
    """Union candidates found by different sources under the same
    normalized-name key, combining evidence rather than creating a
    duplicate entity per source -- e.g. a name found in BOTH
    clinicaltrials.parquet and conference_abstract_corpus.parquet
    becomes one merged entry with sources={"clinicaltrials",
    "conference_abstract_corpus"}, not two separate candidates."""
    merged: dict[str, dict] = {}
    for candidates in candidate_dicts:
        for key, c in candidates.items():
            entry = merged.setdefault(key, dict(
                label=c["label"], suffix=c["suffix"], nct_ids=set(), conference_ids=set(),
                phases=set(), contexts=set(), first_seen=None, sources=set(), adjacent_modalities=set(),
            ))
            entry["sources"] |= c["sources"]
            entry["nct_ids"] |= c["nct_ids"]
            entry["conference_ids"] |= c["conference_ids"]
            entry["phases"] |= c["phases"]
            entry["contexts"] |= c["contexts"]
            entry["adjacent_modalities"] |= c["adjacent_modalities"]
            if c["first_seen"] and (entry["first_seen"] is None or c["first_seen"] < entry["first_seen"]):
                entry["first_seen"] = c["first_seen"]
    return merged


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


CANDIDATE_QUEUE_FIELDS = [
    "candidate_id", "candidate_type", "candidate_label", "source", "evidence_id", "context",
    "first_seen", "confidence", "validation_status", "reason",
    "modality_classification", "modality_detail",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--known-assets-file", type=str, default="configs/known_adc_assets.yaml")
    parser.add_argument("--data-dir", type=str, default="DATA")
    parser.add_argument("--output", type=str, default="DATA/feasibility")
    args = parser.parse_args()

    output_dir = Path(args.output)
    known_assets = load_known_registry(Path(args.known_assets_file))
    active_known = [a for a in known_assets if a.get("active", True)]
    known_ids = known_identifier_set(active_known)

    rows = []
    for a in active_known:
        rows.append(dict(
            candidate_id=f"KNOWN_{a['asset_id'].upper()}",
            candidate_type="ADC_CANDIDATE",
            candidate_label=a["canonical_name"],
            source="configs/known_adc_assets.yaml",
            evidence_id=a["asset_id"],
            context="curated known-asset registry entry, independently verified in prior audits (PR #17)",
            first_seen="",
            confidence="high",
            validation_status="PROMOTED",
            reason="pre-curated, independently verified known ADC asset",
            modality_classification="STRICT_ADC",
            modality_detail="",
        ))

    ct_path = Path(args.data_dir) / "manifests" / "clinicaltrials.parquet"
    conf_path = Path(args.data_dir) / "manifests" / "conference_abstract_corpus.parquet"
    pubmed_path = Path(args.data_dir) / "manifests" / "pubmed.parquet"
    epmc_path = Path(args.data_dir) / "manifests" / "europe_pmc.parquet"
    ct_df = pd.read_parquet(ct_path) if ct_path.exists() else pd.DataFrame()
    conf_df = pd.read_parquet(conf_path) if conf_path.exists() else pd.DataFrame()
    pubmed_df = pd.read_parquet(pubmed_path) if pubmed_path.exists() else pd.DataFrame()
    epmc_df = pd.read_parquet(epmc_path) if epmc_path.exists() else pd.DataFrame()

    ct_candidates = build_ctgov_suffix_candidates(ct_df, known_ids) if not ct_df.empty else {}
    conf_candidates = build_conference_suffix_candidates(conf_df, known_ids) if not conf_df.empty else {}
    suffix_candidates = merge_suffix_candidates(ct_candidates, conf_candidates)
    overlap = len(set(ct_candidates) & set(conf_candidates))
    print(
        f"Found {len(suffix_candidates)} distinct new candidate names via ADC USAN/INN suffix match "
        f"({len(ct_candidates)} from clinicaltrials, {len(conf_candidates)} from conference_abstract_corpus, "
        f"{overlap} found by both)",
        file=sys.stderr,
    )

    # PR #31/#32: second, independent discovery signal -- development-code
    # named assets, which the USAN/INN suffix signal above structurally
    # cannot find (see build_dev_code_candidates()'s docstring). Scanned
    # across every source with inline title+abstract text in its
    # committed manifest, PLUS CT.gov's structured intervention_names
    # field (PR #32 addition, build_ctgov_dev_code_candidates()).
    pubmed_dev = build_dev_code_candidates(pubmed_df, "pubmed", known_ids) if not pubmed_df.empty else {}
    epmc_dev = build_dev_code_candidates(epmc_df, "europe_pmc", known_ids) if not epmc_df.empty else {}
    conf_dev = build_dev_code_candidates(conf_df, "conference_abstract_corpus", known_ids) if not conf_df.empty else {}
    ctgov_dev = build_ctgov_dev_code_candidates(ct_df, known_ids) if not ct_df.empty else {}
    dev_code_candidates = merge_dev_code_candidates(pubmed_dev, epmc_dev, conf_dev, ctgov_dev)
    # Safety net: never double-list a name the suffix signal already
    # found under the same normalized key (not expected to collide in
    # practice -- the two signals operate on structurally different label
    # shapes -- but cheap to guard explicitly rather than assume).
    dev_code_candidates = {k: v for k, v in dev_code_candidates.items() if k not in suffix_candidates}
    n_dev_before_crosswalk = len(dev_code_candidates)

    # PR #32: deterministic alias/dev-code crosswalk (parenthetical
    # co-reference, e.g. "glembatumumab vedotin (CDX-011)") -- merges a
    # dev-code candidate that is really just an ALIAS of an already-
    # discovered suffix candidate into that candidate's own evidence,
    # instead of emitting it as a separate, duplicate row.
    alias_crosswalk = parenthetical_alias_crosswalk(
        [(pubmed_df, ["title", "abstract"]), (epmc_df, ["title", "abstract"]), (conf_df, ["title", "abstract"])],
        [c["label"] for c in suffix_candidates.values()],
    )
    suffix_candidates, dev_code_candidates = apply_alias_crosswalk(suffix_candidates, dev_code_candidates, alias_crosswalk)
    n_aliases_merged = n_dev_before_crosswalk - len(dev_code_candidates)
    print(
        f"Found {len(dev_code_candidates)} distinct new candidate development codes via explicit "
        f"'<code> is/was a(n) ADC' / 'ADC <code>' / appositive grammatical co-occurrence or CT.gov "
        f"structured provenance ({len(pubmed_dev)} pubmed, {len(epmc_dev)} europe_pmc, "
        f"{len(conf_dev)} conference_abstract_corpus, {len(ctgov_dev)} clinicaltrials, before merge; "
        f"{n_aliases_merged} merged into an existing suffix candidate as a deterministic alias, not "
        "double-listed)",
        file=sys.stderr,
    )

    for c in suffix_candidates.values():
        payload_class = ADC_SUFFIX_PAYLOAD_CLASS[c["suffix"]]
        evidence_ids = sorted(c["nct_ids"])[:10] + sorted(c["conference_ids"])[:10]
        example_context = sorted(c["contexts"])[0] if c["contexts"] else ""
        validation_status, confidence = status_and_confidence_for_sources(c["sources"])
        if validation_status == "AUTO_HIGH_CONFIDENCE":
            # A structured, controlled intervention-name field confirms
            # this name -- same confidence basis as Phase 3, regardless
            # of whether conference text also mentions it.
            reason = f"generic drug name ends in the documented ADC USAN/INN payload-class stem '-{c['suffix']}'"
        else:
            # ONLY found via free-text conference-abstract co-occurrence --
            # a categorically noisier signal than a structured field
            # (common-word/target-symbol prefixes, typo variants of an
            # already-known name all pass the same regex), so this is
            # NEVER auto-promoted -- Part 9's two-stage design exists
            # exactly for this case.
            reason = (
                f"generic-looking name ends in the documented ADC USAN/INN payload-class stem '-{c['suffix']}', "
                "but ONLY found via free-text conference-abstract title/abstract co-occurrence -- no structured "
                "intervention-name field confirms it. Higher false-positive risk than the clinicaltrials path "
                "(a common English word or a target/gene symbol can precede the suffix word in prose, and "
                "OCR/authoring typos of an already-known name's spelling are not caught by exact matching); "
                "needs a human check before promotion, not auto-promoted."
            )
        if c["adjacent_modalities"]:
            # Positive keyword evidence in the candidate's OWN text names
            # a specific non-strict-ADC conjugate class (e.g. "Bicycle
            # Toxin Conjugate") -- see ADC_MODALITY_TAXONOMY.md for why
            # this is evidence-gated, never inferred from the name's shape.
            modality_classification = "ADJACENT_CONJUGATE_MODALITY"
            modality_detail = "; ".join(sorted(c["adjacent_modalities"]))
        else:
            # No adjacent-modality keyword found -- PRESUMED, not
            # confirmed, to be a strict antibody ADC (censored-negative,
            # same discipline as broad_recall.py's NOT_CONFIRMED_BROAD).
            modality_classification = "PRESUMED_STRICT_ADC"
            modality_detail = ""
        rows.append(dict(
            candidate_id=candidate_id_for_name(c["label"]),
            candidate_type="ADC_CANDIDATE",
            candidate_label=c["label"],
            source="; ".join(sorted(c["sources"])),
            evidence_id="; ".join(evidence_ids),
            context=f"generic name ends in '-{c['suffix']}' ({payload_class}); example: {example_context}",
            first_seen=c["first_seen"] or "",
            confidence=confidence,
            validation_status=validation_status,
            reason=reason,
            modality_classification=modality_classification,
            modality_detail=modality_detail,
        ))

    for c in dev_code_candidates.values():
        evidence_ids = sorted(c["conference_ids"])[:10]
        example_context = sorted(c["contexts"])[0] if c["contexts"] else ""
        reason = (
            "development-code-shaped name found in explicit tight grammatical relationship with "
            "'antibody-drug conjugate'/'ADC' (e.g. '<code> is a novel antibody-drug conjugate' or "
            "'the ADC candidate <code>') in free-text title/abstract -- no structured field confirms "
            "this, and a development code alone (unlike a USAN/INN suffix) carries no independent "
            "payload/linker class evidence; needs a human check before promotion, not auto-promoted "
            "regardless of how many sources mention it."
        )
        if c["adjacent_modalities"]:
            modality_classification = "ADJACENT_CONJUGATE_MODALITY"
            modality_detail = "; ".join(sorted(c["adjacent_modalities"]))
        else:
            modality_classification = "PRESUMED_STRICT_ADC"
            modality_detail = ""
        rows.append(dict(
            candidate_id=candidate_id_for_name(c["label"]),
            candidate_type="ADC_CANDIDATE",
            candidate_label=c["label"],
            source="; ".join(sorted(c["sources"])),
            evidence_id="; ".join(evidence_ids),
            context=f"development-code + explicit ADC-context match; example: {example_context}",
            first_seen=c["first_seen"] or "",
            confidence="medium",
            validation_status="NEEDS_REVIEW",
            reason=reason,
            modality_classification=modality_classification,
            modality_detail=modality_detail,
        ))

    write_tsv(output_dir / "candidate_queue.tsv", rows, CANDIDATE_QUEUE_FIELDS)
    n_promoted = sum(1 for r in rows if r["validation_status"] == "PROMOTED")
    n_auto = sum(1 for r in rows if r["validation_status"] == "AUTO_HIGH_CONFIDENCE")
    n_review = sum(1 for r in rows if r["validation_status"] == "NEEDS_REVIEW")
    n_adjacent = sum(1 for r in rows if r["modality_classification"] == "ADJACENT_CONJUGATE_MODALITY")
    print(f"candidate_queue.tsv: {len(rows)} total ({n_promoted} PROMOTED from known registry, "
          f"{n_auto} AUTO_HIGH_CONFIDENCE via a structured field, {n_review} NEEDS_REVIEW "
          "via free-text co-occurrence only -- USAN/INN suffix or development-code+ADC-context)", file=sys.stderr)
    print(f"modality_classification: {n_adjacent} ADJACENT_CONJUGATE_MODALITY (positive keyword evidence, "
          "see ADC_MODALITY_TAXONOMY.md), rest STRICT_ADC (known registry) or PRESUMED_STRICT_ADC "
          "(suffix- or development-code-matched, no adjacent-modality evidence found)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
