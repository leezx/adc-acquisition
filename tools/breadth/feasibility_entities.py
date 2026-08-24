#!/usr/bin/env python3
"""Phase 3 (reports/validation/BREADTH_PLAN.md Part 4): turns the
VALIDATED (PROMOTED / AUTO_HIGH_CONFIDENCE) rows of `candidate_queue.tsv`
(built by tools/breadth/candidate_queue.py) into the first counted,
provenance-preserving feasibility entities. `NEEDS_REVIEW`/`REJECTED`/
`UNREVIEWED` candidates are deliberately NOT promoted here -- that is the
whole point of the two-stage design in Part 9.

Populates, from evidence already in this repo (no new acquisition):

  DATA/feasibility/adc_candidates.tsv    (entity_type = ADC_CANDIDATE)
  DATA/feasibility/adc_targets.tsv       (entity_type = ADC_TARGET -- delivery
                                           antigen, ontology-locked per
                                           BREADTH_PLAN.md Phase 1; ONLY from
                                           configs/known_adc_assets.yaml's
                                           own `target` field in this phase --
                                           new candidates have no known
                                           target yet, honestly left absent)
  DATA/feasibility/adc_payloads.tsv      (ADC_PAYLOAD, status = INFERRED --
                                           from the USAN/INN suffix map, a
                                           naming-convention inference, NOT
                                           a validated chemistry fact --
                                           known registry AND new candidates)
  DATA/feasibility/adc_linkers.tsv       (ADC_LINKER, status = INFERRED, same
                                           basis and same caveat as payloads)
  DATA/feasibility/adc_indications.tsv  (from clinicaltrials `conditions`,
                                           aggregated per candidate)

`adc_antibodies.tsv` is NOT written in this phase (round-1 fix): the full
intervention string (e.g. "Trastuzumab deruxtecan") is the complete ADC
asset, not its antibody moiety (e.g. "Trastuzumab") -- neither the known
registry nor clinicaltrials.parquet carries a reliable structured
antibody-moiety field, and guessing one by stripping the payload suffix
word is not safe in general (naming structure varies and isn't guaranteed
splittable that way). Antibody-entity extraction is deferred until a
source explicitly supports antibody identity.

  DATA/feasibility/target_indication_feasibility.tsv (Phase 5c, Part 10)
                                          -- (ADC_TARGET, indication) pairs
                                          derived from adc_candidates.tsv x
                                          adc_targets.tsv; `target` is
                                          ALWAYS ADC_TARGET (the delivery
                                          antigen), never PAYLOAD_MOA_TARGET.
                                          Known-registry-only in this phase,
                                          same reason as adc_targets.tsv:
                                          the 16 CT.gov/conference-derived
                                          candidates have no resolved
                                          target yet, so they cannot
                                          contribute a row here.

Phase 5e (BREADTH_PLAN.md Phase 5 Parts 5/11) additionally populates,
still from evidence already in this repo -- no new acquisition source,
no patent-derived mining (BREADTH_PLAN Part 8, explicitly deferred):

  DATA/feasibility/adc_platforms.tsv      (ADC_PLATFORM -- named
                                           bioconjugation/antibody-
                                           engineering technology
                                           mentions mined from already-
                                           acquired free text via a
                                           curated, individually-verified
                                           keyword dictionary,
                                           tools/breadth/
                                           component_evidence.py's
                                           ADC_PLATFORM_KEYWORDS; status
                                           OBSERVED (single source) or
                                           VALIDATED (corroborated across
                                           >=2 independent evidence
                                           corpora))
  DATA/feasibility/payload_moa_targets.tsv (PAYLOAD_MOA_TARGET -- the
                                           payload's mechanism-of-action
                                           target, Phase 1's ontology
                                           split, NEVER merged into
                                           adc_targets.tsv/ADC_TARGET;
                                           only populated for the 6 of 8
                                           USAN suffix classes with an
                                           uncontroversial public
                                           pharmacology MoA target --
                                           see component_evidence.py)

`adc_payloads.tsv`/`adc_linkers.tsv` also gain a real evidence-tier
upgrade this phase, via ONE ladder applied IDENTICALLY to every
candidate, known-registry or newly-discovered alike (round-1 fix -- see
`build_component_evidence_index()`'s docstring for the logic gap this
closes: PR #17 audited that a known asset IS a real antibody ADC, which
is not the same claim as knowing its SPECIFIC payload/linker chemistry,
so registry membership alone is never used as chemistry evidence):
`USAN_INN_NAMING_INFERENCE` (suffix alone) -> `TEXT_OBSERVED` (that
candidate's OWN evidence explicitly names the chemistry in the LOCAL
context around its own mention, in exactly one corpus -- never the whole
record, same cross-contamination discipline as Phase 5b's round-1 fix)
-> `TEXT_VALIDATED_CROSS_CORPUS` (corroborated across >=2 INDEPENDENT
evidence corpora). No tier guesses a NEW payload/linker identity beyond
the existing 8-suffix map; each only raises confidence in an already-
suffix-inferred identity when stronger evidence for THAT SAME identity
exists.

Usage:
    python3 tools/breadth/feasibility_entities.py \
        --candidate-queue DATA/feasibility/candidate_queue.tsv \
        --known-assets-file configs/known_adc_assets.yaml \
        --data-dir DATA \
        --output DATA/feasibility
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.breadth.candidate_queue import (  # noqa: E402
    ADC_SUFFIX_LINKER_CLASS,
    ADC_SUFFIX_PAYLOAD_CLASS,
    _iter_adc_generic_name_matches,
    find_suffix_matches,
    known_identifier_set,
    local_context_for_span,
    mentions_known_asset,
    normalize_name,
)
from tools.breadth.component_evidence import (  # noqa: E402
    ADC_PLATFORM_KEYWORDS,
    PAYLOAD_MOA_TARGET_BY_SUFFIX,
    find_platform_mentions_in_text,
    payload_linker_text_observed,
)

PROMOTABLE_STATUSES = {"PROMOTED", "AUTO_HIGH_CONFIDENCE"}
NAMING_INFERENCE = "USAN_INN_NAMING_INFERENCE"
TEXT_OBSERVED = "TEXT_OBSERVED"
TEXT_VALIDATED = "TEXT_VALIDATED_CROSS_CORPUS"
MOA_TARGET_PHARMACOLOGY_BASIS = "USAN_INN_PAYLOAD_CLASS_PHARMACOLOGY"

CANDIDATE_FIELDS = [
    "entity_id", "entity_type", "canonical_label", "aliases", "first_seen", "last_seen",
    "evidence_count", "evidence_sources", "confidence", "status",
    "asset_name", "development_codes", "target", "company", "stage", "indications",
    "payload_if_known", "payload_evidence_type", "linker_if_known", "linker_evidence_type",
    "modality_classification",
]
COMPONENT_FIELDS = [
    "entity_id", "entity_type", "canonical_label", "aliases", "first_seen", "last_seen",
    "evidence_count", "evidence_sources", "confidence", "status", "associated_adc_candidates",
]
TARGET_INDICATION_FIELDS = [
    "target", "target_entity_id", "indication", "supporting_asset_count", "supporting_adc_candidates",
    "confidence", "status",
]


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def load_known_registry(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {a["asset_id"]: a for a in data.get("assets", [])}


def filter_promotable(queue: pd.DataFrame) -> pd.DataFrame:
    """PROMOTED/AUTO_HIGH_CONFIDENCE rows, excluding any row whose own
    evidence positively confirms a non-strict-ADC conjugate modality
    (Phase 5b, reports/validation/breadth/ADC_MODALITY_TAXONOMY.md) -- a
    real ADC candidate table must never silently include a confirmed
    non-antibody conjugate, regardless of validation_status. Not
    load-bearing against the current data (every ADJACENT_CONJUGATE_
    MODALITY row today is already NEEDS_REVIEW, excluded by the status
    filter alone), but closes a real gap for any future case where an
    adjacent-modality candidate is ALSO confirmed via a structured field."""
    excluded_modality = queue["modality_classification"] == "ADJACENT_CONJUGATE_MODALITY"
    return queue[queue["validation_status"].isin(PROMOTABLE_STATUSES) & ~excluded_modality]


def indications_for_nct_ids(ct_manifest: pd.DataFrame, nct_ids: list[str]) -> tuple[list[str], str]:
    if not nct_ids or ct_manifest is None:
        return [], ""
    rows = ct_manifest[ct_manifest["nct_id"].isin(nct_ids)]
    conditions: set[str] = set()
    max_phase = ""
    phase_rank = {"PHASE1": 1, "PHASE2": 2, "PHASE3": 3, "PHASE4": 4}
    for _, row in rows.iterrows():
        conds = row.get("conditions")
        if conds is not None:
            conditions.update(str(c) for c in conds)
        phases = row.get("phases")
        if phases is not None:
            for p in phases:
                if phase_rank.get(p, 0) > phase_rank.get(max_phase, 0):
                    max_phase = p
    return sorted(conditions), max_phase


def build_target_indication_rows(candidate_rows: list[dict], target_rows: list[dict]) -> list[dict]:
    """target x indication feasibility table (Phase 5c, BREADTH_PLAN.md
    Part 10) -- `target` is ALWAYS ADC_TARGET (the antibody-binding
    delivery antigen), never PAYLOAD_MOA_TARGET (BREADTH_PLAN.md Phase 1's
    permanent ontology split).

    Built ONLY from candidates whose target is already known -- today,
    the 14 known-registry assets only. This is not a new restriction: it
    directly follows adc_targets.tsv's own existing scope ("known-registry
    only this phase" -- Phase 3's original comment, still true), since a
    candidate absent from adc_targets.tsv's `associated_adc_candidates`
    has no resolved target to pair with any indication here. The 16
    CT.gov/conference-derived candidates (Phase 3/5a) have `target=""`
    (honestly left blank, Part 4's explicit tolerance for partial
    entities), so they cannot contribute a row -- not silently guessed.

    ROUND-1 FIX (2 semantic issues from review): the count field counts
    DISTINCT SUPPORTING ADC ASSETS for a (target, indication) pair, not
    evidence documents/trials/sources -- two assets each backed by 100
    trials still count as 2, not 200 -- so it's named
    `supporting_asset_count`/`supporting_adc_candidates`, not
    `evidence_count`/`associated_adc_candidates`, leaving room for a
    genuinely different future `supporting_evidence_count` without a
    schema collision. And this table does NOT assert `status=VALIDATED`:
    "a known-target ADC and a CT.gov condition string were both
    associated with the same trial record" proves an OBSERVED CLINICAL
    ASSOCIATION, not that target-in-indication therapeutic feasibility has
    been biologically validated -- especially since `indication` is raw,
    undeduplicated CT.gov `conditions` text (mixing real disease
    indications with biomarker/mutation/comorbidity conditions like "HER2
    Gene Mutation"). `confidence=high` describes confidence in the
    ASSOCIATION's provenance (a real CT.gov record links this target's
    asset to this condition string), not confidence in therapeutic
    feasibility -- this table does not yet distinguish clinical vs.
    preclinical vs. patent/conference-only support levels (a future,
    separate increment), so every row here is intentionally the same,
    honestly-labeled tier."""
    candidates_by_entity_id = {c["entity_id"]: c for c in candidate_rows}
    pairs: dict[tuple[str, str], dict] = {}
    for target_row in target_rows:
        candidate_ids = [c.strip() for c in target_row["associated_adc_candidates"].split(";") if c.strip()]
        for candidate_id in candidate_ids:
            candidate = candidates_by_entity_id.get(candidate_id)
            if not candidate:
                continue
            indications = [i for i in candidate["indications"].split("; ") if i]
            for indication in indications:
                key = (target_row["entity_id"], indication)
                entry = pairs.setdefault(key, dict(
                    target=target_row["canonical_label"], target_entity_id=target_row["entity_id"],
                    indication=indication, supporting_adc_candidates=set(),
                ))
                entry["supporting_adc_candidates"].add(candidate_id)

    rows = [
        dict(
            target=entry["target"], target_entity_id=entry["target_entity_id"], indication=entry["indication"],
            supporting_asset_count=len(entry["supporting_adc_candidates"]),
            supporting_adc_candidates="; ".join(sorted(entry["supporting_adc_candidates"])),
            confidence="high", status="OBSERVED_CLINICAL_ASSOCIATION",
        )
        for entry in pairs.values()
    ]
    rows.sort(key=lambda r: (-r["supporting_asset_count"], r["target"], r["indication"]))
    return rows


def load_text_corpus(path: Path, text_cols: list[str]) -> dict[str, str]:
    """id -> concatenated free text, for one already-acquired manifest.
    Returns {} if the manifest doesn't exist (a source not yet run is not
    an error here -- Phase 5e mines whatever evidence already exists, it
    does not require every possible source to be present)."""
    if not path.exists():
        return {}
    cols = ["source_record_id"] + text_cols
    df = pd.read_parquet(path, columns=cols)
    texts = df[text_cols].fillna("").agg(" ".join, axis=1)
    return dict(zip(df["source_record_id"], texts))


def build_component_evidence_index(text_corpora: list[tuple[str, dict[str, str]]]) -> dict[str, dict[str, set[str]]]:
    """ROUND-1 FIX (Phase 5e review): a single pass over ALL already-
    acquired free-text corpora, mapping normalize_name(extracted generic
    name) -> {"payload": {distinct corpus names with a payload-chemistry
    hit in the LOCAL context around THAT mention}, "linker": {...}}.

    Applied IDENTICALLY to every candidate regardless of whether it came
    from configs/known_adc_assets.yaml or Phase 3/5a discovery -- a
    candidate's registry status is NEVER used as chemistry evidence on
    its own. The prior version of this mechanism gave every known-
    registry candidate's suffix-derived payload/linker a blanket
    VALIDATED tier on the theory that "PR #17 already audited this as a
    real antibody ADC" -- but that audit confirmed the asset's IDENTITY,
    not which specific payload/linker chemistry it uses; asserting the
    latter from the former was exactly the logic gap this fix closes.
    Every candidate, known or new, now needs the SAME textual evidence
    (candidate_queue.local_context_for_span() around its own mention,
    never the whole record -- Phase 5b's cross-contamination discipline)
    to earn TEXT_OBSERVED (>=1 corpus) or TEXT_VALIDATED (>=2 INDEPENDENT
    corpora); absent that, it stays USAN_INN_NAMING_INFERENCE, exactly as
    Phase 3 originally and correctly left it uncertain (e.g. -vedotin's
    linker was deliberately labeled "valine-citrulline cleavable linker
    (typical)" -- "typical", not "confirmed for every asset using this
    suffix")."""
    index: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"payload": set(), "linker": set()})
    for source_name, texts in text_corpora:
        for text in texts.values():
            if not text:
                continue
            for extracted, start, end in _iter_adc_generic_name_matches(text):
                suffix = find_suffix_matches(extracted)
                if not suffix:
                    continue
                local = local_context_for_span(text, start, end)
                payload_hit, linker_hit = payload_linker_text_observed(local, suffix)
                norm = normalize_name(extracted)
                if payload_hit:
                    index[norm]["payload"].add(source_name)
                if linker_hit:
                    index[norm]["linker"].add(source_name)
    return index


def evidence_tier_from_sources(sources: set[str]) -> str:
    """USAN suffix alone -> NAMING_INFERENCE; explicit asset-local text
    in exactly one corpus -> TEXT_OBSERVED; corroborated across >=2
    INDEPENDENT corpora -> TEXT_VALIDATED. Same ladder for every
    candidate (see build_component_evidence_index() docstring)."""
    if len(sources) >= 2:
        return TEXT_VALIDATED
    if len(sources) == 1:
        return TEXT_OBSERVED
    return NAMING_INFERENCE


def build_platform_rows(text_corpora: list[tuple[str, dict[str, str]]]) -> list[dict]:
    """ADC_PLATFORM entities mined from already-acquired free text
    (BREADTH_PLAN.md Phase 5 Parts 5/11) -- see component_evidence.py's
    ADC_PLATFORM_KEYWORDS module docstring for how this dictionary was
    built and verified. status=VALIDATED when the SAME canonical platform
    is corroborated across >=2 INDEPENDENT evidence corpora, else
    OBSERVED (a single source's own mention) -- there is no INFERRED
    tier for platforms, since (unlike payload/linker) there is no
    naming-convention mechanism to infer a platform identity from; every
    hit here is a direct, literal keyword match with real provenance,
    never a guess.

    `associated_adc_candidates` is deliberately ALWAYS left blank, not
    attempted via local-window co-occurrence -- tried during development
    and rejected: real abstract "aacr:2026:1689" mentions ConjuAll (a
    LegoChem platform for its OWN BCMA candidates LCB14-2524/LCB14-2516)
    and belantamab mafodotin (an unrelated, different company's BCMA ADC)
    in the same abstract purely as a comparator drug in the background
    section -- proximity alone produced a false "ConjuAll used by
    belantamab mafodotin" link. Attributing a specific candidate to a
    specific platform reliably needs an explicit usage-verb pattern
    ("prepared using X", "leveraging its proprietary X") tied to that
    SAME candidate's own name, not mere co-occurrence in the same
    record -- out of scope for this narrowly-scoped phase; guessing the
    link instead would violate this project's evidence-gated discipline."""
    occurrences: dict[str, list[dict]] = defaultdict(list)
    for source_name, texts in text_corpora:
        for record_id, text in texts.items():
            if not text:
                continue
            for label, variant, start, end in find_platform_mentions_in_text(text):
                occurrences[label].append(dict(source=source_name, record_id=record_id, variant=variant))

    rows = []
    for label, occs in occurrences.items():
        sources = sorted({o["source"] for o in occs})
        variants = sorted({o["variant"] for o in occs})
        validated = len(sources) >= 2
        rows.append(dict(
            entity_id=f"ADC_PLATFORM_{normalize_name(label).upper()}", entity_type="ADC_PLATFORM",
            canonical_label=label, aliases="; ".join(variants), first_seen="", last_seen="",
            evidence_count=len(occs), evidence_sources="; ".join(sources),
            confidence="high" if validated else "medium", status="VALIDATED" if validated else "OBSERVED",
            associated_adc_candidates="",
        ))
    rows.sort(key=lambda r: (-r["evidence_count"], r["canonical_label"]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-queue", type=str, default="DATA/feasibility/candidate_queue.tsv")
    parser.add_argument("--known-assets-file", type=str, default="configs/known_adc_assets.yaml")
    parser.add_argument("--data-dir", type=str, default="DATA")
    parser.add_argument("--output", type=str, default="DATA/feasibility")
    args = parser.parse_args()

    output_dir = Path(args.output)
    queue = pd.read_csv(args.candidate_queue, sep="\t", dtype=str).fillna("")
    promoted = filter_promotable(queue)
    excluded_modality_count = int((queue["modality_classification"] == "ADJACENT_CONJUGATE_MODALITY").sum())
    print(f"{len(promoted)}/{len(queue)} candidate_queue.tsv rows are validated "
          f"(PROMOTED/AUTO_HIGH_CONFIDENCE, excluding {excluded_modality_count} ADJACENT_CONJUGATE_MODALITY); "
          "building feasibility entities from those only", file=sys.stderr)

    known_registry = load_known_registry(Path(args.known_assets_file))
    ct_path = Path(args.data_dir) / "manifests" / "clinicaltrials.parquet"
    ct_manifest = pd.read_parquet(ct_path) if ct_path.exists() else None

    # Phase 5e (BREADTH_PLAN.md Phase 5 Parts 5/11): free-text evidence
    # ALREADY acquired by prior phases, used to upgrade payload/linker
    # evidence tiers and to mine ADC_PLATFORM mentions -- no new
    # acquisition source. Every corpus is optional (a source not yet run
    # is not an error); conference_abstract_corpus is used for the
    # payload/linker text-observed upgrade (its abstracts most reliably
    # state a specific asset's own chemistry), all five for platform
    # mining (a platform brand can appear in any of them).
    data_dir = Path(args.data_dir)
    conf_text_by_id = load_text_corpus(data_dir / "manifests" / "conference_abstract_corpus.parquet", ["title", "abstract"])
    text_corpora = [
        ("conference_abstract_corpus", conf_text_by_id),
        ("pubmed", load_text_corpus(data_dir / "manifests" / "pubmed.parquet", ["title", "abstract"])),
        ("europe_pmc", load_text_corpus(data_dir / "manifests" / "europe_pmc.parquet", ["title", "abstract"])),
        ("crossref", load_text_corpus(data_dir / "manifests" / "crossref.parquet", ["title", "abstract"])),
        ("company_scientific_presentations", load_text_corpus(data_dir / "manifests" / "company_scientific_presentations.parquet", ["title"])),
    ]

    # ROUND-1 FIX (Phase 5e review): one pass over ALL text corpora,
    # reused identically for every candidate below -- see
    # build_component_evidence_index()'s docstring for why a known-
    # registry candidate gets no shortcut here.
    component_evidence_index = build_component_evidence_index(text_corpora)

    candidate_rows = []
    payload_usage: dict[str, list[dict]] = defaultdict(list)
    linker_usage: dict[str, list[dict]] = defaultdict(list)
    moa_target_usage: dict[str, list[str]] = defaultdict(list)

    for _, c in promoted.iterrows():
        nct_ids = [n for n in c["evidence_id"].split("; ") if n.startswith("NCT")]
        suffix = find_suffix_matches(c["candidate_label"])
        payload_if_known = ADC_SUFFIX_PAYLOAD_CLASS.get(suffix, "") if suffix else ""
        linker_if_known = ADC_SUFFIX_LINKER_CLASS.get(suffix, "") if suffix else ""
        # Evidence-tier assignment (Phase 5e, round-1 fix): the SAME
        # ladder for known-registry and newly-discovered candidates
        # alike -- USAN suffix alone is NAMING_INFERENCE; the candidate's
        # OWN local evidence context explicitly naming that chemistry in
        # exactly one corpus is TEXT_OBSERVED; corroborated across >=2
        # independent corpora is TEXT_VALIDATED. A candidate's registry
        # status is never itself chemistry evidence.
        evidence_entry = component_evidence_index.get(normalize_name(c["candidate_label"]), {"payload": set(), "linker": set()})
        payload_evidence_type = evidence_tier_from_sources(evidence_entry["payload"]) if payload_if_known else ""
        linker_evidence_type = evidence_tier_from_sources(evidence_entry["linker"]) if linker_if_known else ""

        if c["source"] == "configs/known_adc_assets.yaml":
            asset = known_registry[c["evidence_id"]]
            # Known assets don't carry their own trial list directly in
            # the registry -- indications are looked up by matching the
            # asset's own identifiers against clinicaltrials intervention
            # names. Round-1 fix: reuses the SAME containment matcher
            # (mentions_known_asset) as candidate_queue.py's own dedup
            # step, restricted to just this one asset's identifiers --
            # an exact normalized-string match previously missed trials
            # whose intervention_names recorded a combination-regimen or
            # trial-arm label instead of a clean single-drug name,
            # undercounting evidence_count/indications for known assets.
            this_asset_ids = known_identifier_set([asset])
            matched_ncts = []
            if ct_manifest is not None:
                for _, row in ct_manifest.iterrows():
                    names = row.get("intervention_names")
                    if names is None:
                        continue
                    if any(mentions_known_asset(n, this_asset_ids) for n in names):
                        matched_ncts.append(row["nct_id"])
            indications, stage = indications_for_nct_ids(ct_manifest, matched_ncts)
            candidate_rows.append(dict(
                entity_id=f"ADC_CANDIDATE_{asset['asset_id'].upper()}",
                entity_type="ADC_CANDIDATE", canonical_label=asset["canonical_name"],
                aliases="; ".join(asset.get("aliases") or []),
                first_seen="", last_seen="",
                evidence_count=len(matched_ncts), evidence_sources="configs/known_adc_assets.yaml; clinicaltrials",
                confidence="high", status="VALIDATED",
                asset_name=asset["canonical_name"], development_codes="; ".join(asset.get("dev_codes") or []),
                target=asset.get("target", ""), company=asset.get("company", ""),
                stage="Approved",  # established in the prior NAR benchmark audit (PR #17): all 14 match NAR's Approved subset
                indications="; ".join(indications),
                payload_if_known=payload_if_known, payload_evidence_type=payload_evidence_type,
                linker_if_known=linker_if_known, linker_evidence_type=linker_evidence_type,
                modality_classification="STRICT_ADC",
            ))
        else:
            indications, stage = indications_for_nct_ids(ct_manifest, nct_ids)
            candidate_rows.append(dict(
                entity_id=f"ADC_CANDIDATE_{c['candidate_id']}",
                entity_type="ADC_CANDIDATE", canonical_label=c["candidate_label"], aliases="",
                first_seen=c["first_seen"], last_seen="",
                evidence_count=len(nct_ids), evidence_sources=c["source"],
                confidence=c["confidence"], status="VALIDATED",
                asset_name=c["candidate_label"], development_codes="",
                target="", company="",  # honestly unknown -- Part 4 explicitly tolerates partial entities
                stage=stage or "unknown", indications="; ".join(indications),
                payload_if_known=payload_if_known, payload_evidence_type=payload_evidence_type,
                linker_if_known=linker_if_known, linker_evidence_type=linker_evidence_type,
                modality_classification=c["modality_classification"],
            ))

        if suffix:
            candidate_entity_id = candidate_rows[-1]["entity_id"]
            payload_usage[payload_if_known].append(dict(candidate_id=candidate_entity_id, tier=payload_evidence_type))
            linker_usage[linker_if_known].append(dict(candidate_id=candidate_entity_id, tier=linker_evidence_type))
            moa_target = PAYLOAD_MOA_TARGET_BY_SUFFIX.get(suffix)
            if moa_target:
                moa_target_usage[moa_target].append(candidate_entity_id)

    write_tsv(output_dir / "adc_candidates.tsv", candidate_rows, CANDIDATE_FIELDS)
    print(f"adc_candidates.tsv: {len(candidate_rows)} entities "
          f"({sum(1 for r in candidate_rows if r['confidence'] == 'high')} high-confidence)", file=sys.stderr)

    # adc_targets.tsv: thin, known-registry-only in this phase -- new
    # candidates have no known target identity yet (honestly left absent,
    # per Part 4's explicit tolerance for partial entities), not guessed.
    # adc_antibodies.tsv is deliberately NOT produced this phase (round-1
    # fix) -- see module docstring for why.
    target_rows = []
    for asset in known_registry.values():
        if not asset.get("active", True):
            continue
        candidate_entity_id = f"ADC_CANDIDATE_{asset['asset_id'].upper()}"
        target_rows.append(dict(
            entity_id=f"ADC_TARGET_{normalize_name(asset['target']).upper()}", entity_type="ADC_TARGET",
            canonical_label=asset["target"], aliases="", first_seen="", last_seen="",
            evidence_count=1, evidence_sources="configs/known_adc_assets.yaml",
            confidence="high", status="VALIDATED", associated_adc_candidates=candidate_entity_id,
        ))
    # Merge duplicate targets (multiple known assets can share one target,
    # e.g. HER2) into one entity with all associated candidates listed.
    merged_targets: dict[str, dict] = {}
    for row in target_rows:
        existing = merged_targets.get(row["entity_id"])
        if existing:
            existing["evidence_count"] += 1
            existing["associated_adc_candidates"] += "; " + row["associated_adc_candidates"]
        else:
            merged_targets[row["entity_id"]] = row
    write_tsv(output_dir / "adc_targets.tsv", list(merged_targets.values()), COMPONENT_FIELDS)
    print(f"adc_targets.tsv: {len(merged_targets)} entities (known-registry only this phase)", file=sys.stderr)

    target_indication_rows = build_target_indication_rows(candidate_rows, list(merged_targets.values()))
    write_tsv(output_dir / "target_indication_feasibility.tsv", target_indication_rows, TARGET_INDICATION_FIELDS)
    print(f"target_indication_feasibility.tsv: {len(target_indication_rows)} (target, indication) pairs "
          "(known-registry-only this phase, same reason as adc_targets.tsv)", file=sys.stderr)

    # adc_payloads.tsv / adc_linkers.tsv (Phase 5e round-1 fix: tier-aware,
    # no longer flat INFERRED-only, and no known-registry shortcut): a
    # component entity's status is the BEST evidence tier found among its
    # associated candidates -- VALIDATED (>=1 candidate corroborated
    # across >=2 independent evidence corpora) > OBSERVED (>=1
    # candidate's own local text names this chemistry in exactly one
    # corpus) > INFERRED (naming-convention only, for every other
    # candidate using this suffix, known-registry or not). evidence_sources
    # lists every distinct tier actually contributing, so a payload used
    # by both a text-corroborated candidate AND a text-unconfirmed one
    # honestly shows both.
    def _component_rows(entity_type: str, usage: dict[str, list[dict]]) -> list[dict]:
        rows = []
        for label, entries in usage.items():
            if not label:
                continue
            tiers = {e["tier"] for e in entries if e["tier"]}
            if TEXT_VALIDATED in tiers:
                status, confidence = "VALIDATED", "high"
            elif TEXT_OBSERVED in tiers:
                status, confidence = "OBSERVED", "high"
            else:
                status, confidence = "INFERRED", "medium"
            rows.append(dict(
                entity_id=f"{entity_type}_{normalize_name(label).upper()}", entity_type=entity_type,
                canonical_label=label, aliases="", first_seen="", last_seen="",
                evidence_count=len(entries), evidence_sources="; ".join(sorted(tiers)),
                confidence=confidence, status=status,
                associated_adc_candidates="; ".join(sorted(e["candidate_id"] for e in entries)),
            ))
        return rows

    payload_rows = _component_rows("ADC_PAYLOAD", payload_usage)
    linker_rows = _component_rows("ADC_LINKER", linker_usage)
    write_tsv(output_dir / "adc_payloads.tsv", payload_rows, COMPONENT_FIELDS)
    write_tsv(output_dir / "adc_linkers.tsv", linker_rows, COMPONENT_FIELDS)
    for name, rows in (("adc_payloads.tsv", payload_rows), ("adc_linkers.tsv", linker_rows)):
        by_status = defaultdict(int)
        for r in rows:
            by_status[r["status"]] += 1
        print(f"{name}: {len(rows)} entities ({dict(by_status)})", file=sys.stderr)

    # payload_moa_targets.tsv (Phase 5e, BREADTH_PLAN.md Phase 1's ontology
    # split -- NEVER merged into adc_targets.tsv/ADC_TARGET). Only the 6 of
    # 8 suffix classes with an uncontroversial public-pharmacology MoA
    # target; see component_evidence.py for why ozogamicin/tesirine are
    # honestly left unmapped rather than guessed.
    moa_target_rows = [
        dict(
            entity_id=f"PAYLOAD_MOA_TARGET_{normalize_name(label).upper()}", entity_type="PAYLOAD_MOA_TARGET",
            canonical_label=label, aliases="", first_seen="", last_seen="",
            evidence_count=len(ids), evidence_sources=MOA_TARGET_PHARMACOLOGY_BASIS,
            confidence="high", status="VALIDATED", associated_adc_candidates="; ".join(sorted(ids)),
        )
        for label, ids in moa_target_usage.items()
    ]
    write_tsv(output_dir / "payload_moa_targets.tsv", moa_target_rows, COMPONENT_FIELDS)
    print(f"payload_moa_targets.tsv: {len(moa_target_rows)} entities "
          "(6 of 8 USAN suffix classes have an uncontroversial MoA target; ozogamicin/tesirine honestly unmapped)",
          file=sys.stderr)

    # adc_platforms.tsv (Phase 5e, BREADTH_PLAN.md Phase 5 Parts 5/11) --
    # mined from already-acquired free text only, see build_platform_rows().
    platform_rows = build_platform_rows(text_corpora)
    write_tsv(output_dir / "adc_platforms.tsv", platform_rows, COMPONENT_FIELDS)
    validated_platforms = sum(1 for r in platform_rows if r["status"] == "VALIDATED")
    print(f"adc_platforms.tsv: {len(platform_rows)} entities "
          f"({validated_platforms} VALIDATED via cross-corpus corroboration, "
          f"{len(platform_rows) - validated_platforms} OBSERVED single-source)", file=sys.stderr)

    # adc_indications.tsv: aggregate distinct condition strings across all
    # validated candidates, with a count of how many candidates cite each.
    indication_counts: dict[str, int] = defaultdict(int)
    for row in candidate_rows:
        for ind in [i for i in row["indications"].split("; ") if i]:
            indication_counts[ind] += 1
    indication_rows = [
        dict(indication=ind, n_adc_candidates=count)
        for ind, count in sorted(indication_counts.items(), key=lambda kv: -kv[1])
    ]
    write_tsv(output_dir / "adc_indications.tsv", indication_rows, ["indication", "n_adc_candidates"])
    print(f"adc_indications.tsv: {len(indication_rows)} distinct indications "
          f"(from clinicaltrials 'conditions', not yet cross-checked against NAR)", file=sys.stderr)

    print(f"\nDone. Outputs written to {output_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
