#!/usr/bin/env python3
"""Company-registry gap analysis (source-coverage expansion, round 1 of 4).

Per the reviewer's explicit finding: `configs/company_registry.yaml`
(shared by Job 05/SEC, Job 11/company pipeline pages, Job 12/company press
releases, and the company scientific-presentations source) has only 8
curated companies, while the reviewer's own reading of the code confirmed
at least one real Phase1+-ADC-holding company (Day One, which acquired
Mersana's ADC asset) is not registered at all. The 8-company registry
therefore represents "company ACQUISITION CAPABILITY is built," never
"the company UNIVERSE is covered" -- this tool makes that gap concrete and
reproducible instead of guessing which companies to add next.

Deliberately NOT a new acquisition source: this is a pure data-engineering
audit over two tables this repo already owns --
`DATA/catalog/adc_asset_universe.tsv` (PR #30-33's reference-seeded master
catalog) and `configs/company_registry.yaml` itself. No network access, no
new external dependency.

Method: every Phase1+ (Approved/Phase3/Phase2/Phase1) catalog row's own
`company` field (semicolon-separated, since a row can name more than one
sponsor/partner) is split into distinct company-name mentions, counted
across all Phase1+ rows, and checked for an EXACT normalized-name match
(reusing `tools.validation.compare_nar_adcdb.normalize_name` -- the same
lowercase/punctuation-stripped discipline used everywhere else in this
repo for cross-entity identity, never fuzzy) against every registered
company's own `canonical_name` + `aliases`. A company name is "covered"
only on an exact match; this deliberately does NOT try to resolve
corporate-family relationships (e.g. "Genentech, Inc" is Roche's US
subsidiary, "F. Hoffmann-La Roche Ltd" and "Roche Holding AG" are
distinct real SEC/EDGAR-relevant legal entities) -- collapsing those
would be a genuine identity-resolution judgment call belonging to a
human curating the registry, not something this audit tool should guess.

Ranks distinct companies by Phase1+ mention count (a company named on more
Phase1+ catalog rows is a higher-value registry gap to close first) and
reports, NOT auto-generates, registry entries -- adding a company to
`configs/company_registry.yaml` still requires the same live research
(CIK, official domain, pipeline/press-release/investor-relations URLs)
every existing entry required; this tool's job is to tell a human/reviewer
WHICH companies are worth that research effort, in priority order, not to
skip the research.

SEMANTIC CAVEAT (reviewer finding, round-1 fix 2026-08-31): the catalog's
own `company` field is a broad ASSOCIATED-company field -- it is populated
without checking `development_status` and without distinguishing
originator / licensee / manufacturer / CMO / historical (terminated
portfolio) company from an actual current developer or sponsor. Live
output surfaced real cases of this: CDMO/manufacturing entities (BSP
Pharmaceuticals, Baxter Oncology) and companies with long-terminated
programs (Agensys, Stemcentrx, MedImmune) all appeared indistinguishable
from a genuine active ADC developer. This tool therefore does NOT assert
"this is an active ADC company" -- it reports "this company name is
associated with a Phase1+ catalog row," a high-recall CANDIDATE list for
human registry review, not proof of current developer/sponsor status.
Resolving originator/licensee/manufacturer/historical roles is a genuine
identity-resolution judgment call for a human curating the registry (same
principle already applied above to Genentech/Roche), deliberately out of
scope for this tool.

Usage:
    python3 tools/validation/company_registry_gap_analysis.py \
        --catalog DATA/catalog/adc_asset_universe.tsv \
        --company-registry configs/company_registry.yaml \
        --output reports/validation/breadth/company_registry_gap.tsv \
        --report-output reports/validation/breadth/COMPANY_REGISTRY_GAP.md
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adc_acquisition.company_registry import load_companies  # noqa: E402
from tools.validation.compare_nar_adcdb import normalize_name  # noqa: E402

PHASE1_PLUS_STAGES = {"Approved", "Phase3", "Phase2", "Phase1"}

GAP_FIELDS = [
    "company_name", "phase1_plus_asset_count", "in_registry",
    "matched_company_id", "example_assets",
]


def registered_identifier_index(companies: list) -> dict[str, str]:
    """normalize_name(identifier) -> company_id, for every canonical_name/
    alias across the registry -- exact match only, same discipline as
    match_nar_to_known_assets()/match_candidate_to_nar() elsewhere in this
    repo (never fuzzy/substring, to avoid a Roche/Genentech-style false
    merge)."""
    index: dict[str, str] = {}
    for c in companies:
        for identifier in [c.canonical_name, *c.aliases]:
            if identifier:
                index[normalize_name(identifier)] = c.company_id
    return index


def split_multi(value: str) -> list[str]:
    return [v.strip() for v in str(value or "").split(";") if v.strip()]


def load_phase1_plus_company_mentions(catalog_path: Path) -> dict[str, dict]:
    """Returns {company_name: {"count": int, "examples": [canonical_name, ...]}}
    across every DISTINCT company name mentioned in a Phase1+ catalog row's
    own `company` field -- a row naming 2 companies (e.g. an originator +
    licensing partner, or a developer + a manufacturing/CDMO entity)
    contributes to BOTH company names' counts. This field is genuinely
    associated with the asset in the catalog, but is NOT checked against
    `development_status` and does not distinguish originator / licensee /
    manufacturer / historical company -- see this module's own docstring
    caveat before treating a high mention count as proof of an active
    developer/sponsor role."""
    df = pd.read_csv(catalog_path, sep="\t", dtype=str).fillna("")
    phase1_plus = df[df["highest_stage"].isin(PHASE1_PLUS_STAGES)]
    mentions: dict[str, dict] = {}
    for _, row in phase1_plus.iterrows():
        for company_name in split_multi(row["company"]):
            entry = mentions.setdefault(company_name, {"count": 0, "examples": [], "stages": []})
            entry["count"] += 1
            entry["stages"].append(row["highest_stage"])
            if len(entry["examples"]) < 5:
                entry["examples"].append(row["canonical_name"])
    return mentions


def build_gap_rows(mentions: dict[str, dict], registry_index: dict[str, str]) -> list[dict]:
    rows = []
    for company_name, entry in mentions.items():
        matched_company_id = registry_index.get(normalize_name(company_name))
        rows.append(dict(
            company_name=company_name,
            phase1_plus_asset_count=entry["count"],
            in_registry=matched_company_id is not None,
            matched_company_id=matched_company_id or "",
            example_assets="; ".join(entry["examples"]),
        ))
    rows.sort(key=lambda r: (-r["phase1_plus_asset_count"], r["company_name"]))
    return rows


def write_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GAP_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_report(rows: list[dict], registered_count: int) -> str:
    covered = [r for r in rows if r["in_registry"]]
    gaps = [r for r in rows if not r["in_registry"]]
    top_gaps = gaps[:30]
    lines = [
        "# Company Registry Gap Analysis",
        "",
        "Reproducible audit (`tools/validation/company_registry_gap_analysis.py`) "
        "comparing every distinct company name ASSOCIATED WITH a Phase1+ "
        "(`highest_stage` in Approved/Phase3/Phase2/Phase1) row in "
        "`DATA/catalog/adc_asset_universe.tsv` against "
        "`configs/company_registry.yaml`'s own canonical_name/aliases "
        "(exact normalized match only, never fuzzy).",
        "",
        "**Caveat**: the catalog's `company` field is a broad "
        "associated-company field -- it does not check `development_status` "
        "and does not distinguish originator / licensee / manufacturer / "
        "CMO / historical (terminated-portfolio) company from an active "
        "current developer or sponsor. This is a high-recall CANDIDATE list "
        "for human registry review, not proof that every listed entity is a "
        "current developer/sponsor -- some rows below are manufacturing/CDMO "
        "entities or long-terminated programs, not registry-worthy ADC "
        "companies.",
        "",
        f"- Companies currently registered: {registered_count}",
        f"- Distinct company names associated with Phase1+ catalog rows: {len(rows)}",
        f"- Of those, already registered: {len(covered)}",
        f"- Of those, NOT registered (the gap): {len(gaps)}",
        "",
        "## Top 30 unregistered company names associated with Phase1+ catalog rows, by mention count",
        "",
        "Not auto-added -- each still needs the same live research (CIK, "
        "official domain, pipeline/press-release/investor-relations URLs) "
        "every existing registry entry required, INCLUDING confirming the "
        "entity is actually an active developer/sponsor worth registering "
        "at all (see caveat above).",
        "",
        "| Phase1+ mentions | Company name | Example assets |",
        "|---|---|---|",
    ]
    for r in top_gaps:
        lines.append(f"| {r['phase1_plus_asset_count']} | {r['company_name']} | {r['example_assets']} |")
    return "\n".join(lines) + "\n"


UNIVERSE_FIELDS = [
    "company_id", "canonical_name", "aliases", "representative_adc",
    "highest_phase1_plus_stage_observed", "phase1_plus_asset_mention_count",
    "official_domain", "pipeline_url", "press_release_url", "presentations_url",
    "parent_company", "registry_status", "evidence_source", "last_verified",
]

# NAR_ADCdb-style stage ordering, most-advanced first -- reused only to
# pick ONE "highest_phase1_plus_stage_observed" per company from the
# several Phase1+ rows it's named on, never to invent a stage not already
# on some real catalog row.
_STAGE_RANK = {"Approved": 0, "Phase3": 1, "Phase2": 2, "Phase1": 3}


def build_company_universe_rows(
    mentions: dict[str, dict], companies: list, run_date: str,
) -> list[dict]:
    """One row per company known to this project EITHER because it's
    registered in configs/company_registry.yaml OR because it's named on a
    Phase1+ catalog row (or both) -- a standing, reproducible table joining
    Phase1+ catalog mentions against the registry, replacing a one-off
    manual list.

    `registry_status`:
    - REGISTERED: has a company_registry.yaml entry with at least
      official_domain and one of pipeline_urls/press_release_url set.
    - REGISTERED_INCOMPLETE: has an entry, but no official_domain or no
      pipeline/press-release URL at all yet (e.g. a just-added company
      still pending live URL research) -- distinct from REGISTERED so a
      reviewer can see incomplete entries without re-deriving it by hand.
    - UNREGISTERED_PHASE1_PLUS_COMPANY_MENTION: this company name is
      associated with a Phase1+ catalog row but has no registry entry at
      all. Deliberately NOT named "...ACTIVE_ADC_COMPANY" (an earlier,
      reviewer-flagged version of this status) -- the catalog's `company`
      field does not check `development_status` and does not distinguish
      originator / licensee / manufacturer / CMO / historical company from
      an active developer, and live output surfaced real cases of this
      (CDMO entities BSP Pharmaceuticals/Baxter Oncology; long-terminated
      programs at Agensys/Stemcentrx/MedImmune all appeared indistinguishable
      from a genuine active ADC developer). This status is a high-recall
      CANDIDATE flag for human registry review, never proof of current
      developer/sponsor status -- see this module's own docstring caveat.

    `last_verified` is the date THIS TOOL RUN computed the join, not a
    claim that live URLs were re-checked on that date -- see this
    function's own caller (main()) for why: this is an audit snapshot,
    not a live crawl.

    Matches a company to catalog mentions via EVERY identifier it owns
    (canonical_name + aliases), not canonical_name alone -- mirrors
    registered_identifier_index()'s own matching semantics (module
    docstring: "exact normalized-name match ... against every registered
    company's own canonical_name + aliases"). A prior version of this
    function only checked canonical_name, silently missing any company
    whose catalog mentions use an alias form (e.g. "Bristol Myers Squibb
    Co" vs. the registry's "Bristol-Myers Squibb Company") -- found and
    fixed 2026-08-28 while adding aliases for the source-coverage
    expansion round; a company can have multiple mention-name variants in
    the catalog, so counts/examples/stages are aggregated across all of
    them rather than only the first identifier that happens to match."""
    mentions_by_normalized: dict[str, tuple[str, dict]] = {
        normalize_name(name): (name, entry) for name, entry in mentions.items()
    }
    rows: list[dict] = []
    seen_normalized: set[str] = set()

    for c in companies:
        identifiers = [c.canonical_name, *c.aliases]
        matches = []
        for identifier in identifiers:
            if not identifier:
                continue
            norm = normalize_name(identifier)
            seen_normalized.add(norm)
            matched = mentions_by_normalized.get(norm)
            if matched:
                matches.append(matched[1])
        representative_adc, highest_stage_observed, mention_count = "", "", 0
        if matches:
            mention_count = sum(m["count"] for m in matches)
            examples = [e for m in matches for e in m.get("examples", [])]
            representative_adc = examples[0] if examples else ""
            stages = [s for m in matches for s in m.get("stages", []) if s in _STAGE_RANK]
            if stages:
                highest_stage_observed = min(stages, key=lambda s: _STAGE_RANK[s])
        has_url = bool(c.pipeline_urls) or bool(c.press_release_url)
        registry_status = "REGISTERED" if (c.official_domain and has_url) else "REGISTERED_INCOMPLETE"
        rows.append(dict(
            company_id=c.company_id, canonical_name=c.canonical_name,
            aliases="; ".join(c.aliases), representative_adc=representative_adc,
            highest_phase1_plus_stage_observed=highest_stage_observed,
            phase1_plus_asset_mention_count=mention_count,
            official_domain=c.official_domain or "",
            pipeline_url="; ".join(c.pipeline_urls), press_release_url=c.press_release_url or "",
            presentations_url=c.presentations_url or "", parent_company=c.parent_company_id or "",
            registry_status=registry_status, evidence_source="company_registry.yaml",
            last_verified=run_date,
        ))

    for name, entry in mentions.items():
        if normalize_name(name) in seen_normalized:
            continue
        stages = [s for s in entry.get("stages", []) if s in _STAGE_RANK]
        highest_stage_observed = min(stages, key=lambda s: _STAGE_RANK[s]) if stages else ""
        rows.append(dict(
            company_id="", canonical_name=name, aliases="",
            representative_adc=entry["examples"][0] if entry["examples"] else "",
            highest_phase1_plus_stage_observed=highest_stage_observed,
            phase1_plus_asset_mention_count=entry["count"],
            official_domain="", pipeline_url="", press_release_url="", presentations_url="",
            parent_company="", registry_status="UNREGISTERED_PHASE1_PLUS_COMPANY_MENTION",
            evidence_source="master_catalog", last_verified="",
        ))

    rows.sort(key=lambda r: (
        r["registry_status"] != "UNREGISTERED_PHASE1_PLUS_COMPANY_MENTION",
        -r["phase1_plus_asset_mention_count"], r["canonical_name"],
    ))
    return rows


def write_company_universe_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNIVERSE_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=str, default="DATA/catalog/adc_asset_universe.tsv")
    parser.add_argument("--company-registry", type=str, default="configs/company_registry.yaml")
    parser.add_argument("--output", type=str, default="reports/validation/breadth/company_registry_gap.tsv")
    parser.add_argument("--report-output", type=str, default="reports/validation/breadth/COMPANY_REGISTRY_GAP.md")
    parser.add_argument("--company-universe-output", type=str, default="reports/validation/breadth/PHASE1_PLUS_COMPANY_UNIVERSE.tsv")
    parser.add_argument("--run-date", type=str, required=True, help="Stamped into last_verified -- caller-supplied so this script never calls datetime.now() itself.")
    args = parser.parse_args()

    companies = load_companies(Path(args.company_registry))
    registry_index = registered_identifier_index(companies)
    mentions = load_phase1_plus_company_mentions(Path(args.catalog))
    rows = build_gap_rows(mentions, registry_index)

    write_tsv(Path(args.output), rows)
    Path(args.report_output).write_text(build_report(rows, len(companies)), encoding="utf-8")

    universe_rows = build_company_universe_rows(mentions, companies, args.run_date)
    write_company_universe_tsv(Path(args.company_universe_output), universe_rows)

    n_gap = sum(1 for r in rows if not r["in_registry"])
    n_unregistered_mentions = sum(
        1 for r in universe_rows if r["registry_status"] == "UNREGISTERED_PHASE1_PLUS_COMPANY_MENTION"
    )
    print(
        f"company_registry_gap_analysis: {len(companies)} companies registered, "
        f"{len(rows)} distinct company names associated with Phase1+ catalog rows, {n_gap} not registered. "
        f"Written to {args.output} (+ report at {args.report_output}); "
        f"company universe ({len(universe_rows)} rows, {n_unregistered_mentions} "
        f"UNREGISTERED_PHASE1_PLUS_COMPANY_MENTION) written to {args.company_universe_output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
