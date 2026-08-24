from tools.breadth.component_evidence import (
    PAYLOAD_MOA_TARGET_BY_SUFFIX,
    find_platform_mentions_in_text,
    payload_linker_text_observed,
)


def test_find_platform_mentions_finds_registered_variant():
    text = "This ADC was prepared using MediLink's TMALIN platform, a proprietary linker-payload platform."
    hits = find_platform_mentions_in_text(text)
    labels = {label for label, variant, start, end in hits}
    assert "TMALIN" in labels


def test_find_platform_mentions_requires_trademark_marker_for_collision_prone_terms():
    """Bare 'SMAC' (Second Mitochondria-derived Activator of Caspases, a
    real and common apoptosis-pathway term unrelated to any ADC platform)
    must NOT match -- only the disambiguating 'SMACTM' surface form
    registered in ADC_PLATFORM_KEYWORDS should."""
    unrelated_text = "SMAC mimetics induce apoptosis by antagonizing IAP proteins in cancer cells."
    hits = find_platform_mentions_in_text(unrelated_text)
    assert hits == []

    real_text = "The ADC was generated using SMACTM technology for site-specific conjugation."
    hits = find_platform_mentions_in_text(real_text)
    labels = {label for label, variant, start, end in hits}
    assert "SMAC" in labels


def test_find_platform_mentions_returns_empty_for_generic_platform_prose():
    """Generic prose mentioning 'platform'/'technology' without any
    registered brand name must not produce a spurious hit -- this
    dictionary is positive-evidence-only, never a naming-shape guess."""
    text = "This ADC platform represents a novel technology for cancer therapy."
    assert find_platform_mentions_in_text(text) == []


def test_payload_linker_text_observed_finds_registered_signal():
    local_context = "The ADC was conjugated to MMAE via a cleavable linker."
    payload, linker = payload_linker_text_observed(local_context, "vedotin")
    assert payload == "MMAE"


def test_payload_linker_text_observed_finds_linker_signal():
    local_context = "A valine-citrulline linker connects the antibody to its payload."
    payload, linker = payload_linker_text_observed(local_context, "vedotin")
    assert linker == "valine-citrulline"


def test_payload_linker_text_observed_returns_none_when_absent():
    local_context = "This is an unrelated sentence about clinical trial enrollment."
    payload, linker = payload_linker_text_observed(local_context, "vedotin")
    assert payload is None
    assert linker is None


def test_payload_moa_target_honestly_unmapped_for_dna_damaging_agents():
    """ozogamicin (calicheamicin) and tesirine (PBD dimer) are DNA-damaging
    agents without a single discrete protein MoA target -- must be
    absent, not guessed, from PAYLOAD_MOA_TARGET_BY_SUFFIX."""
    assert "ozogamicin" not in PAYLOAD_MOA_TARGET_BY_SUFFIX
    assert "tesirine" not in PAYLOAD_MOA_TARGET_BY_SUFFIX


def test_payload_moa_target_mapped_for_tubulin_and_top1_classes():
    assert PAYLOAD_MOA_TARGET_BY_SUFFIX["vedotin"] == "Tubulin"
    assert PAYLOAD_MOA_TARGET_BY_SUFFIX["deruxtecan"] == "DNA topoisomerase 1 (TOP1)"
