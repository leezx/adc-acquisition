import numpy as np
import pandas as pd

from tools.breadth.candidate_queue import (
    apply_alias_crosswalk,
    build_conference_suffix_candidates,
    build_ctgov_dev_code_candidates,
    build_ctgov_suffix_candidates,
    build_dev_code_candidates,
    candidate_id_for_name,
    detect_adjacent_modalities,
    extract_adc_generic_name,
    extract_all_adc_generic_names_from_text,
    find_suffix_matches,
    known_identifier_set,
    local_context_for_span,
    mentions_known_asset,
    merge_dev_code_candidates,
    merge_suffix_candidates,
    normalize_name,
    parenthetical_alias_crosswalk,
    status_and_confidence_for_sources,
)


def test_find_suffix_matches_recognizes_documented_stem():
    assert find_suffix_matches("Ladiratuzumab vedotin") == "vedotin"
    assert find_suffix_matches("Depatuxizumab mafodotin") == "mafodotin"


def test_find_suffix_matches_returns_none_for_unrelated_name():
    assert find_suffix_matches("Pembrolizumab") is None
    assert find_suffix_matches("vedotin") is None  # bare suffix, not a real drug name with a stem prefix


def test_mentions_known_asset_catches_combination_regimen_strings():
    known = known_identifier_set([{"asset_id": "x", "canonical_name": "Enfortumab vedotin", "aliases": [], "dev_codes": []}])
    assert mentions_known_asset("Pembrolizumab + Enfortumab Vedotin", known)
    assert mentions_known_asset("Arm A: Belantamab Mafodotin", known_identifier_set(
        [{"asset_id": "y", "canonical_name": "Belantamab mafodotin", "aliases": [], "dev_codes": []}]
    ))


def test_mentions_known_asset_false_for_genuinely_new_name():
    known = known_identifier_set([{"asset_id": "x", "canonical_name": "Enfortumab vedotin", "aliases": [], "dev_codes": []}])
    assert not mentions_known_asset("Ladiratuzumab vedotin", known)


def test_normalize_name_strips_punctuation_and_case():
    assert normalize_name("Trastuzumab-Emtansine") == normalize_name("trastuzumab emtansine")


def test_extract_adc_generic_name_strips_combination_regimen_partner():
    assert extract_adc_generic_name("Pembrolizumab + Ladiratuzumab vedotin") == "Ladiratuzumab vedotin"


def test_extract_adc_generic_name_strips_trial_arm_label():
    assert extract_adc_generic_name("Arm A: Ladiratuzumab vedotin") == "Ladiratuzumab vedotin"


def test_extract_adc_generic_name_strips_radiolabel_prefix():
    assert extract_adc_generic_name("89Zr-Patritumab deruxtecan") == "Patritumab deruxtecan"


def test_extract_adc_generic_name_strips_trailing_parenthetical_abbreviation():
    """A real case found in clinicaltrials.parquet: the naive whole-string
    endswith() check missed these entirely because the suffix word isn't
    at the very end of the raw string."""
    assert extract_adc_generic_name("Labetuzumab Govitecan (LG)") == "Labetuzumab Govitecan"
    assert extract_adc_generic_name("Enapotamab vedotin (HuMax-AXL-ADC)") == "Enapotamab vedotin"


def test_extract_adc_generic_name_returns_none_for_bare_suffix_or_no_suffix():
    assert extract_adc_generic_name("Vedotin") is None
    assert extract_adc_generic_name("Pembrolizumab") is None


def test_extract_all_adc_generic_names_from_text_finds_multiple_distinct_names():
    text = "A comparison of Trastuzumab deruxtecan and Sacituzumab govitecan in breast cancer."
    names = extract_all_adc_generic_names_from_text(text)
    assert set(n.lower() for n in names) == {"trastuzumab deruxtecan", "sacituzumab govitecan"}


def test_extract_all_adc_generic_names_from_text_excludes_stopword_prefixes():
    # Real false-positive patterns observed scanning the actual conference
    # abstract corpus: a common English word directly before the suffix
    # word, not a real antibody-name stem.
    text = "This novel vedotin conjugate and the deruxtecan arm showed activity."
    assert extract_all_adc_generic_names_from_text(text) == []


def test_extract_all_adc_generic_names_from_text_deduplicates_repeated_mentions():
    text = "Trastuzumab deruxtecan was studied. Later, trastuzumab deruxtecan showed responses."
    names = extract_all_adc_generic_names_from_text(text)
    assert len(names) == 1


def test_build_conference_suffix_candidates_suppresses_known_asset():
    known = known_identifier_set([{"asset_id": "x", "canonical_name": "Trastuzumab deruxtecan", "aliases": [], "dev_codes": []}])
    manifest = pd.DataFrame([
        dict(source_record_id="10.1/1", title="A study of Trastuzumab deruxtecan", abstract=None, publication_or_release_date="2020-01-01"),
    ])
    assert build_conference_suffix_candidates(manifest, known) == {}


def test_build_conference_suffix_candidates_surfaces_genuinely_new_name():
    known = known_identifier_set([{"asset_id": "x", "canonical_name": "Trastuzumab deruxtecan", "aliases": [], "dev_codes": []}])
    manifest = pd.DataFrame([
        dict(source_record_id="10.1/1", title="A study of Mecbotamab vedotin in AXL-positive tumors", abstract=None, publication_or_release_date="2020-01-01"),
    ])
    candidates = build_conference_suffix_candidates(manifest, known)
    assert len(candidates) == 1
    entry = next(iter(candidates.values()))
    assert entry["label"] == "Mecbotamab vedotin"
    assert entry["sources"] == {"conference_abstract_corpus"}
    assert entry["conference_ids"] == {"10.1/1"}


def test_merge_suffix_candidates_combines_sources_for_same_name():
    ct = {"mecbotamabvedotin": dict(label="Mecbotamab vedotin", suffix="vedotin", nct_ids={"NCT1"},
                                     conference_ids=set(), phases=set(), first_seen="2021-01-01",
                                     contexts={"a trial"}, sources={"clinicaltrials"}, adjacent_modalities=set())}
    conf = {"mecbotamabvedotin": dict(label="Mecbotamab vedotin", suffix="vedotin", nct_ids=set(),
                                       conference_ids={"10.1/1"}, phases=set(), first_seen="2020-01-01",
                                       contexts={"an abstract"}, sources={"conference_abstract_corpus"},
                                       adjacent_modalities={"BICYCLE_TOXIN_CONJUGATE"})}
    merged = merge_suffix_candidates(ct, conf)
    assert len(merged) == 1
    entry = merged["mecbotamabvedotin"]
    assert entry["sources"] == {"clinicaltrials", "conference_abstract_corpus"}
    assert entry["nct_ids"] == {"NCT1"}
    assert entry["conference_ids"] == {"10.1/1"}
    assert entry["first_seen"] == "2020-01-01"  # earliest of the two
    assert entry["adjacent_modalities"] == {"BICYCLE_TOXIN_CONJUGATE"}


def test_merge_suffix_candidates_keeps_distinct_names_separate():
    ct = {"a": dict(label="A vedotin", suffix="vedotin", nct_ids={"NCT1"}, conference_ids=set(),
                     phases=set(), first_seen=None, contexts=set(), sources={"clinicaltrials"}, adjacent_modalities=set())}
    conf = {"b": dict(label="B vedotin", suffix="vedotin", nct_ids=set(), conference_ids={"10.1/2"},
                       phases=set(), first_seen=None, contexts=set(), sources={"conference_abstract_corpus"},
                       adjacent_modalities=set())}
    merged = merge_suffix_candidates(ct, conf)
    assert set(merged.keys()) == {"a", "b"}


def test_status_and_confidence_for_sources():
    assert status_and_confidence_for_sources({"clinicaltrials"}) == ("AUTO_HIGH_CONFIDENCE", "high")
    assert status_and_confidence_for_sources({"clinicaltrials", "conference_abstract_corpus"}) == ("AUTO_HIGH_CONFIDENCE", "high")
    assert status_and_confidence_for_sources({"conference_abstract_corpus"}) == ("NEEDS_REVIEW", "medium")


def test_candidate_id_for_name_is_source_independent_and_stable_across_upgrade():
    """Regression test for the round-1 fix: a candidate first seen ONLY in
    a conference abstract, then later ALSO confirmed on CT.gov, must keep
    the SAME candidate_id and upgrade status in place -- not disappear
    under one id and reappear under a different one. This is the identity
    contract Phase 6's twice-monthly delta system depends on."""
    known = known_identifier_set([])

    conf_manifest = pd.DataFrame([
        dict(source_record_id="10.1/1", title="A study of Mecbotamab vedotin in AXL-positive tumors",
             abstract=None, publication_or_release_date="2026-08-01"),
    ])
    conf_candidates = build_conference_suffix_candidates(conf_manifest, known)

    # Run 1: only conference evidence exists yet.
    run1 = merge_suffix_candidates(conf_candidates)
    assert len(run1) == 1
    entry1 = next(iter(run1.values()))
    id1 = candidate_id_for_name(entry1["label"])
    status1, _ = status_and_confidence_for_sources(entry1["sources"])
    assert entry1["sources"] == {"conference_abstract_corpus"}
    assert status1 == "NEEDS_REVIEW"

    # Run 2: the SAME real candidate now also appears on CT.gov.
    ct_manifest = pd.DataFrame([
        dict(nct_id="NCT99999999", intervention_names=["Mecbotamab vedotin"], phases=["PHASE1"],
             brief_title="A trial of mecbotamab vedotin", study_first_post_date="2026-08-15"),
    ])
    ct_candidates = build_ctgov_suffix_candidates(ct_manifest, known)
    run2 = merge_suffix_candidates(ct_candidates, conf_candidates)
    assert len(run2) == 1
    entry2 = next(iter(run2.values()))
    id2 = candidate_id_for_name(entry2["label"])
    status2, _ = status_and_confidence_for_sources(entry2["sources"])

    assert id2 == id1  # same identity, not a new one
    assert entry2["sources"] == {"clinicaltrials", "conference_abstract_corpus"}
    assert status2 == "AUTO_HIGH_CONFIDENCE"  # upgraded in place


def test_detect_adjacent_modalities_finds_bicycle_toxin_conjugate():
    text = ("Zelenectide pevedotin (zele; BT8009) is a Bicycle Toxin Conjugate (BTC), "
            "comprising a highly selective bicyclic peptide targeting Nectin-4.")
    assert detect_adjacent_modalities(text) == {"BICYCLE_TOXIN_CONJUGATE"}


def test_detect_adjacent_modalities_empty_for_ordinary_adc_text():
    text = "A phase 1 study of Trastuzumab deruxtecan in HER2-positive breast cancer."
    assert detect_adjacent_modalities(text) == set()


def test_local_context_for_span_excludes_a_different_adjacent_sentence():
    """Regression test for the round-1 fix: modality evidence about one
    candidate must not leak into the local context of a different
    candidate mentioned in an adjacent sentence of the same record."""
    text = "Zelenectide pevedotin is a Bicycle Toxin Conjugate. Trastuzumab deruxtecan was used as comparator."
    zele_start = text.index("Zelenectide")
    zele_end = zele_start + len("Zelenectide pevedotin")
    trast_start = text.index("Trastuzumab")
    trast_end = trast_start + len("Trastuzumab deruxtecan")

    zele_context = local_context_for_span(text, zele_start, zele_end)
    trast_context = local_context_for_span(text, trast_start, trast_end)

    assert "bicycle toxin conjugate" in zele_context.lower()
    assert "bicycle toxin conjugate" not in trast_context.lower()


def test_build_conference_suffix_candidates_does_not_cross_contaminate_unrelated_candidate():
    """The exact scenario the reviewer flagged: one abstract mentions two
    ADC-like candidates, and only one is actually described as a Bicycle
    Toxin Conjugate. The unrelated candidate must NOT inherit that
    modality just because it appears in the same record."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(
            source_record_id="10.1/1",
            title="A comparison of two conjugates",
            abstract="Zelenectide pevedotin is a Bicycle Toxin Conjugate. "
                     "Trastuzumab deruxtecan was used as comparator.",
            publication_or_release_date="2025-01-01",
        ),
    ])
    candidates = build_conference_suffix_candidates(manifest, known)
    by_label = {c["label"].lower(): c for c in candidates.values()}

    assert by_label["zelenectide pevedotin"]["adjacent_modalities"] == {"BICYCLE_TOXIN_CONJUGATE"}
    assert by_label["trastuzumab deruxtecan"]["adjacent_modalities"] == set()


def test_build_conference_suffix_candidates_only_flags_the_candidate_in_the_matching_sentence():
    """A second variant of the same scenario, using a different keyword
    (peptide-drug conjugate) and different candidate names, to confirm
    this isn't specific to the zelenectide/Bicycle wording."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(
            source_record_id="10.1/2",
            title="A comparison of two candidates",
            abstract="Mecbotamab vedotin is a peptide-drug conjugate targeting AXL. "
                     "Sonesitatug vedotin was evaluated separately in a different cohort.",
            publication_or_release_date="2025-01-01",
        ),
    ])
    candidates = build_conference_suffix_candidates(manifest, known)
    by_label = {c["label"].lower(): c for c in candidates.values()}

    assert by_label["mecbotamab vedotin"]["adjacent_modalities"] == {"PEPTIDE_DRUG_CONJUGATE"}
    assert by_label["sonesitatug vedotin"]["adjacent_modalities"] == set()


def test_build_conference_suffix_candidates_flags_adjacent_modality_from_full_abstract_text():
    """The real zelenectide pevedotin case: the modality phrase appears in
    the abstract BODY, not (necessarily) within the 150-char title
    snippet stored in `contexts` -- the scan must cover the full text."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(
            source_record_id="10.1200/jco.2025.43.16_suppl.tps4619",
            title="A phase 2/3 study of zelenectide pevedotin targeting nectin-4",
            abstract="Zelenectide pevedotin (BT8009) is a Bicycle Toxin Conjugate (BTC), "
                     "comprising a bicyclic peptide linked to MMAE.",
            publication_or_release_date="2025-06-01",
        ),
    ])
    candidates = build_conference_suffix_candidates(manifest, known)
    entry = next(iter(candidates.values()))
    assert entry["adjacent_modalities"] == {"BICYCLE_TOXIN_CONJUGATE"}


def test_build_ctgov_suffix_candidates_attributes_modality_to_the_specific_intervention_only():
    """Same class of bug as the conference-text case, for CT.gov: a row's
    brief_title can describe multiple interventions/arms, so modality
    evidence must come from the specific intervention string itself, not
    the shared brief_title -- otherwise an unrelated intervention in the
    same trial could inherit another arm's modality."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(nct_id="NCT1",
             intervention_names=["Mecbotamab vedotin (a peptide-drug conjugate)", "Sonesitatug vedotin"],
             phases=["PHASE1"], brief_title="A trial comparing two ADC-class candidates",
             study_first_post_date="2021-01-01"),
    ])
    candidates = build_ctgov_suffix_candidates(manifest, known)
    by_label = {c["label"].lower(): c for c in candidates.values()}

    assert by_label["mecbotamab vedotin"]["adjacent_modalities"] == {"PEPTIDE_DRUG_CONJUGATE"}
    assert by_label["sonesitatug vedotin"]["adjacent_modalities"] == set()


def test_build_ctgov_suffix_candidates_has_empty_adjacent_modalities_for_ordinary_candidate():
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(nct_id="NCT1", intervention_names=["Mecbotamab vedotin"], phases=["PHASE1"],
             brief_title="A trial of mecbotamab vedotin", study_first_post_date="2021-01-01"),
    ])
    candidates = build_ctgov_suffix_candidates(manifest, known)
    entry = next(iter(candidates.values()))
    assert entry["adjacent_modalities"] == set()


def test_clean_date_string_never_produces_literal_nan():
    """Regression test: a conference record with no publication date has
    pandas' float NaN for that column (not None), and `if value:` treats
    NaN as truthy -- the round-1 bug wrote the literal string "nan" as
    first_seen instead of leaving it blank."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="aacr:2026:1", title="A study of Mecbotamab vedotin",
             abstract=None, publication_or_release_date=np.nan),
    ])
    candidates = build_conference_suffix_candidates(manifest, known)
    entry = next(iter(candidates.values()))
    assert entry["first_seen"] is None
    assert entry["first_seen"] != "nan"


# --- PR #31: development-code + explicit ADC-context signal ---------------


def test_build_dev_code_candidates_finds_code_first_pattern():
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="pmid:1", title="Population-Based Modeling to Predict Human PK/PD of TAK-500",
             abstract="TAK-500 is a novel antibody-drug conjugate composed of an anti-CCR2 antibody "
                      "conjugated to a STING agonist.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "pubmed", known)
    assert len(candidates) == 1
    entry = next(iter(candidates.values()))
    assert entry["label"] == "TAK-500"
    assert entry["sources"] == {"pubmed"}


def test_build_dev_code_candidates_finds_term_first_pattern():
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="pmid:2", title="A phase 1 study",
             abstract="Here we report the first-in-human results for the ADC candidate BAT-8008 in "
                      "patients with advanced solid tumors.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "pubmed", known)
    assert len(candidates) == 1
    assert next(iter(candidates.values()))["label"] == "BAT-8008"


def test_build_dev_code_candidates_rejects_loose_cooccurrence_without_tight_grammar():
    """A dev-code-shaped token merely co-occurring with 'ADC' elsewhere in
    the abstract (not in the tight 'is/was a(n) ADC' or 'ADC <code>'
    relationship) must NOT be surfaced -- this is exactly the class of
    false positive (clinical trial acronyms, cell lines, target symbols)
    the tight-grammar requirement exists to exclude."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="pmid:3", title="KEYNOTE-057 study of pembrolizumab",
             abstract="This ADC trial enrolled patients from KEYNOTE-057 across multiple centers.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "pubmed", known)
    assert candidates == {}


def test_build_dev_code_candidates_excludes_scientific_notation():
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="pmid:4", title="A study",
             abstract="The observed hazard ratio was significant (p = 5E-33), consistent with the "
                      "antibody-drug conjugate's efficacy.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "pubmed", known)
    assert candidates == {}


def test_build_dev_code_candidates_suppresses_known_registry_dev_code_by_exact_match():
    """Round-1-class regression: a short dev code (e.g. 'SGN-35',
    normalize_name -> 'sgn35', only 5 chars) must still be suppressed even
    though mentions_known_asset()'s substring-containment check requires
    >=6 chars -- this signal's candidate label IS the entire dev code, so
    exact match (not containment) is used instead."""
    known = known_identifier_set([
        {"asset_id": "x", "canonical_name": "Brentuximab vedotin", "aliases": [], "dev_codes": ["SGN-35"]},
    ])
    manifest = pd.DataFrame([
        dict(source_record_id="pmid:5", title="A study",
             abstract="SGN-35 is an antibody-drug conjugate targeting CD30.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "pubmed", known)
    assert candidates == {}


def test_build_dev_code_candidates_attributes_modality_to_local_context():
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="pmid:6", title="A study",
             abstract="ZK-1000 is an antibody-drug conjugate that is also a bicycle toxin conjugate "
                      "in its structural class.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "pubmed", known)
    entry = next(iter(candidates.values()))
    assert entry["adjacent_modalities"] == {"BICYCLE_TOXIN_CONJUGATE"}


def test_merge_dev_code_candidates_combines_sources_for_same_code():
    a = {"tak500": dict(label="TAK-500", nct_ids=set(), conference_ids={"pmid:1"}, phases=set(),
                         first_seen="2024-01-01", contexts={"x"}, sources={"pubmed"}, adjacent_modalities=set())}
    b = {"tak500": dict(label="TAK-500", nct_ids=set(), conference_ids={"pmid:2"}, phases=set(),
                         first_seen="2023-06-01", contexts={"y"}, sources={"europe_pmc"}, adjacent_modalities=set())}
    merged = merge_dev_code_candidates(a, b)
    assert len(merged) == 1
    entry = merged["tak500"]
    assert entry["sources"] == {"pubmed", "europe_pmc"}
    assert entry["conference_ids"] == {"pmid:1", "pmid:2"}
    assert entry["first_seen"] == "2023-06-01"  # earliest of the two


# --- PR #32: appositive pattern, hyphen-optional fragment, CT.gov signal, alias crosswalk, new suffixes ---


def test_build_dev_code_candidates_finds_appositive_pattern():
    """Round-1-of-PR#31-fix regression: 'ZL-6201, a novel LRRC15-
    targeting antibody drug conjugate (ADC)' -- an appositive construction
    with no is/was verb, which PR #31's two patterns did not cover."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="conf:1", title="Discovery of ZL-6201",
             abstract="Discovery of ZL-6201, a novel LRRC15-targeting antibody drug conjugate (ADC) for "
                      "the treatment of sarcomas and epithelial solid tumors.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "conference_abstract_corpus", known)
    assert "zl6201" in candidates
    assert candidates["zl6201"]["label"] == "ZL-6201"


def test_build_dev_code_candidates_finds_hyphenless_code():
    """Round-1-of-PR#31-fix regression: the real acquired text spells
    BAT-8008 without its hyphen ("BAT8008")."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="conf:1", title="A study",
             abstract="This study reports the safety and efficacy of BAT8008, an antibody-drug conjugate, "
                      "in a cohort of patients.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "conference_abstract_corpus", known)
    assert "bat8008" in candidates


def test_build_dev_code_candidates_finds_letter_after_hyphen_code():
    """SHR-A2102 -- a letter directly after the hyphen, before the digit
    run, a shape the original fragment (hyphen then digits only) missed."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="conf:1", title="A study",
             abstract="SHR-A2102, a nectin-4 directed antibody-drug conjugate, in patients with "
                      "pretreated advanced solid tumours.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "conference_abstract_corpus", known)
    assert "shra2102" in candidates


def test_build_dev_code_candidates_finds_single_letter_hyphenless_prefix():
    """M7437 -- a single-uppercase-letter-only prefix, shorter than the
    original hyphenless fragment's 2-character minimum."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="conf:1", title="A study",
             abstract="M7437, a novel anti-Ly6E antibody-drug conjugate (ADC) with topoisomerase 1 "
                      "inhibitor payload: preclinical antitumor activity and safety.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "conference_abstract_corpus", known)
    assert "m7437" in candidates


def test_build_dev_code_candidates_still_rejects_short_target_symbols():
    """The broadened fragment must still exclude common 1-2-digit target/
    biomarker symbols (HER2, CD30) -- the >=3-digit floor for the
    hyphenless branch is the guard."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(source_record_id="conf:1", title="A study",
             abstract="HER2 is a well-established target. CD30 is an antibody-drug conjugate target "
                      "in Hodgkin lymphoma.",
             publication_or_release_date="2024-01-01"),
    ])
    candidates = build_dev_code_candidates(manifest, "conference_abstract_corpus", known)
    assert candidates == {}


def test_build_ctgov_dev_code_candidates_requires_trial_level_adc_context():
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(nct_id="NCT1", intervention_names=["STRO-002"],
             brief_title="Study of STRO-002, an Anti-Folate Receptor Alpha Antibody Drug Conjugate",
             official_title="", conditions=["Ovarian Cancer"], study_first_post_date="2020-01-01"),
        dict(nct_id="NCT2", intervention_names=["PF-06804103"],
             brief_title="PF-06804103 Dose Escalation in HER2 Positive Solid Tumors",
             official_title="", conditions=["Breast Neoplasms"], study_first_post_date="2020-01-01"),
    ])
    candidates = build_ctgov_dev_code_candidates(manifest, known)
    assert "stro002" in candidates  # trial title itself says "Antibody Drug Conjugate"
    assert "pf06804103" not in candidates  # this trial's own title/conditions never say ADC


def test_build_ctgov_dev_code_candidates_full_match_only_not_embedded():
    """A dev-code-shaped SUBSTRING of a longer intervention_names entry
    (e.g. a combination-regimen label) must not match -- only an entry
    that IS, in its entirety, development-code-shaped."""
    known = known_identifier_set([])
    manifest = pd.DataFrame([
        dict(nct_id="NCT1", intervention_names=["Pembrolizumab + STRO-002"],
             brief_title="A study of an antibody-drug conjugate", official_title="",
             conditions=[], study_first_post_date="2020-01-01"),
    ])
    candidates = build_ctgov_dev_code_candidates(manifest, known)
    assert candidates == {}


def test_parenthetical_alias_crosswalk_finds_code_in_parens_after_name():
    df = pd.DataFrame([
        dict(title="GPNMB-targeted ADC",
             abstract="cells to killing by CDX-011 (glembatumumab vedotin), a GPNMB-targeted "
                      "antibody-drug conjugate."),
    ])
    aliases = parenthetical_alias_crosswalk([(df, ["title", "abstract"])], ["glembatumumab vedotin"])
    assert aliases == {"glembatumumabvedotin": {"CDX-011"}}


def test_parenthetical_alias_crosswalk_finds_name_in_parens_after_code():
    df = pd.DataFrame([
        dict(title="Management of metastatic breast cancer",
             abstract="second-generation antibody-drug conjugates: focus on glembatumumab vedotin "
                      "(CDX-011, CR011-vcMMAE)."),
    ])
    aliases = parenthetical_alias_crosswalk([(df, ["title", "abstract"])], ["glembatumumab vedotin"])
    assert aliases == {"glembatumumabvedotin": {"CDX-011"}}


def test_parenthetical_alias_crosswalk_finds_multi_alias_group():
    """'Bulumtatug Fuvedotin (BFv, 9MW2821)' -- a comma-separated group
    inside the parens, only the dev-code-shaped piece is kept."""
    df = pd.DataFrame([
        dict(title="Bulumtatug Fuvedotin (BFv, 9MW2821), a next-generation Nectin-4 targeting ADC",
             abstract="in patients with advanced solid tumors."),
    ])
    aliases = parenthetical_alias_crosswalk([(df, ["title", "abstract"])], ["Bulumtatug Fuvedotin"])
    assert aliases == {"bulumtatugfuvedotin": {"9MW2821"}}


def test_parenthetical_alias_crosswalk_empty_when_no_candidate_labels():
    df = pd.DataFrame([dict(title="x (CDX-011)", abstract="")])
    assert parenthetical_alias_crosswalk([(df, ["title", "abstract"])], []) == {}


def test_apply_alias_crosswalk_merges_dev_code_into_suffix_candidate_not_double_listed():
    suffix_candidates = {
        "glembatumumabvedotin": dict(
            label="glembatumumab vedotin", suffix="vedotin", nct_ids=set(), conference_ids={"epmc:1"},
            phases=set(), contexts={"x"}, first_seen="2020-01-01", sources={"conference_abstract_corpus"},
            adjacent_modalities=set(),
        ),
    }
    dev_code_candidates = {
        "cdx011": dict(
            label="CDX-011", nct_ids=set(), conference_ids={"pmid:9"}, phases=set(),
            contexts={"y"}, first_seen="2015-01-01", sources={"pubmed"}, adjacent_modalities=set(),
        ),
    }
    alias_crosswalk = {"glembatumumabvedotin": {"CDX-011"}}
    updated_suffix, remaining_dev = apply_alias_crosswalk(suffix_candidates, dev_code_candidates, alias_crosswalk)
    assert remaining_dev == {}  # not double-listed
    merged = updated_suffix["glembatumumabvedotin"]
    assert merged["sources"] == {"conference_abstract_corpus", "pubmed"}  # evidence merged, not dropped
    assert merged["first_seen"] == "2015-01-01"  # earliest of the two


def test_apply_alias_crosswalk_leaves_unrelated_dev_code_untouched():
    suffix_candidates = {"a": dict(label="A vedotin", suffix="vedotin", nct_ids=set(), conference_ids=set(),
                                    phases=set(), contexts=set(), first_seen=None, sources={"pubmed"},
                                    adjacent_modalities=set())}
    dev_code_candidates = {"tak500": dict(label="TAK-500", nct_ids=set(), conference_ids=set(), phases=set(),
                                           contexts=set(), first_seen=None, sources={"europe_pmc"},
                                           adjacent_modalities=set())}
    updated_suffix, remaining_dev = apply_alias_crosswalk(suffix_candidates, dev_code_candidates, alias_crosswalk={})
    assert "tak500" in remaining_dev
    assert updated_suffix["a"]["sources"] == {"pubmed"}  # untouched


def test_find_suffix_matches_new_suffixes_do_not_collide_with_soravtansine():
    """'Mirvetuximab soravtansine' must still match the more specific
    'soravtansine' suffix, not the newly-added 'ravtansine' (which
    'soravtansine' ends with as a substring)."""
    assert find_suffix_matches("Mirvetuximab soravtansine") == "soravtansine"
    assert find_suffix_matches("Indatuximab ravtansine") == "ravtansine"


def test_find_suffix_matches_recognizes_new_pr32_suffixes():
    assert find_suffix_matches("Bivatuzumab mertansine") == "mertansine"
    assert find_suffix_matches("Serclutamab talirine") == "talirine"
    assert find_suffix_matches("Vobramitamab duocarmazine") == "duocarmazine"
