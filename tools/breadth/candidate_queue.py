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
    ct_candidates = build_ctgov_suffix_candidates(pd.read_parquet(ct_path), known_ids) if ct_path.exists() else {}
    conf_candidates = (
        build_conference_suffix_candidates(pd.read_parquet(conf_path), known_ids) if conf_path.exists() else {}
    )
    suffix_candidates = merge_suffix_candidates(ct_candidates, conf_candidates)
    overlap = len(set(ct_candidates) & set(conf_candidates))
    print(
        f"Found {len(suffix_candidates)} distinct new candidate names via ADC USAN/INN suffix match "
        f"({len(ct_candidates)} from clinicaltrials, {len(conf_candidates)} from conference_abstract_corpus, "
        f"{overlap} found by both)",
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

    write_tsv(output_dir / "candidate_queue.tsv", rows, CANDIDATE_QUEUE_FIELDS)
    n_promoted = sum(1 for r in rows if r["validation_status"] == "PROMOTED")
    n_auto = sum(1 for r in rows if r["validation_status"] == "AUTO_HIGH_CONFIDENCE")
    n_review = sum(1 for r in rows if r["validation_status"] == "NEEDS_REVIEW")
    n_adjacent = sum(1 for r in rows if r["modality_classification"] == "ADJACENT_CONJUGATE_MODALITY")
    print(f"candidate_queue.tsv: {len(rows)} total ({n_promoted} PROMOTED from known registry, "
          f"{n_auto} AUTO_HIGH_CONFIDENCE via a structured field, {n_review} NEEDS_REVIEW "
          "via free-text conference co-occurrence only)", file=sys.stderr)
    print(f"modality_classification: {n_adjacent} ADJACENT_CONJUGATE_MODALITY (positive keyword evidence, "
          "see ADC_MODALITY_TAXONOMY.md), rest STRICT_ADC (known registry) or PRESUMED_STRICT_ADC "
          "(suffix-matched, no adjacent-modality evidence found)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
