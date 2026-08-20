#!/usr/bin/env python3
"""External benchmark / gap analysis: adc-acquisition vs. the NAR ADCdb
database (Chen SQ, Dong XW, Fang L, Zhu F. "ADCdb: the database of
antibody-drug conjugates." Nucleic Acids Research 52(D1):D1097-D1109
(2024). PMID 37831118).

READ-ONLY against the external ADCdb vault -- never writes, renames, or
deletes anything under --external-root. Writes only under --output
(default: reports/validation/nar_adcdb_comparison/) in THIS repo.

IMPORTANT, established by direct inspection before writing this script
(see reports/validation/nar_adcdb_comparison.md section 3 for the full
writeup): the external vault at --external-root is NOT the original 2023
paper dataset. It is a local Obsidian vault built by crawling the LIVE
ADCdb website (adcdb.idrblab.net) in 2026-04 and 2026-08 -- a evolving,
continuously-updated resource, not a frozen snapshot. Its own
`update.timeline.md` explicitly documents this divergence (paper: 6572
ADCs / local crawl: 6235 ADCs), and 5533 of those 6235 are undifferentiated
cross-link "stub" entries with NO development-phase tag at all (the
vault's own note warns not to treat a blank status as a biological fact).
This script's NAR benchmark universe is therefore, by design, the 702
entries that DO carry an explicit phase/status tag (Approved/Phase 1-3/
Investigative) -- see `load_nar_benchmark_universe()` for exactly how
that's determined (non-"raw:"-prefixed result_url in _data/adc_inventory.json).

Also established directly: the per-ADC pages expose NO PMID field, NO DOI
field (except a handful of inline DOIs in free-text reference lists), and
NO patent identifiers at all (0/6235 pages mention "patent"). This is a
genuine SCHEMA LIMITATION of the external database, not a defect in this
comparison tool or in adc-acquisition -- PMID/DOI/patent overlap against
NAR literally cannot be computed the way a naive benchmark spec might
assume, because NAR doesn't expose those identifiers per-ADC. This script
still extracts what NCT IDs and DOIs it can find embedded in free text
(via regex) for a partial, disclosed-as-partial identifier comparison.

Usage:
    python3 tools/validation/compare_nar_adcdb.py \
        --external-root "/Volumes/Stelligen_SSD/Stelligen/DATA/1.Databases/ADCdb/ADCdb_Obsidian" \
        --data-dir DATA \
        --output reports/validation/nar_adcdb_comparison

Re-running regenerates identical output from the external vault's current
state + this repo's current DATA/manifests -- no manual editing of any
output TSV is ever performed; every number is reproducible from this
script.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# External ADCdb parsing
# ---------------------------------------------------------------------------

NCT_RE = re.compile(r"\bNCT\d{8}\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\]\)\"',;]+")


def _normalize_doi(doi: str) -> str:
    """DOIs are case-insensitive by specification, and a DOI extracted
    from free-flowing reference-list text is very often immediately
    followed by sentence-ending punctuation that is NOT part of the DOI
    itself (e.g. "...CCR-04-0037." with a trailing period) -- strip
    trailing punctuation and lowercase before ANY comparison, or every
    such DOI silently fails to match its real counterpart."""
    return doi.strip().rstrip(".,;)]\"'").lower()
TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|?\s*$")

STATUS_KEYWORDS = [
    "Approved", "Phase 3 Clinical Trial", "Phase 2 Clinical Trial",
    "Phase 1 Clinical Trial", "Preclinical", "Investigative",
]
INDICATION_SPLIT_RE = re.compile(
    r"(?=(?:" + "|".join(re.escape(k) for k in STATUS_KEYWORDS) + r"))"
)


@dataclass
class NARAsset:
    adc_id: str
    name: str  # as given in adc_inventory.json (often the real drug name/dev code once phase-tagged)
    status: str
    antibody_name_inv: str  # from adc_inventory.json (present even when .md is missing)
    payload_name_inv: str
    linker_name_inv: str
    representative_indication_inv: str
    md_found: bool = False
    brand_name: str | None = None
    synonyms: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    drug_status_md: str | None = None
    indications: list[str] = field(default_factory=list)  # (indication, status) pairs flattened to "indication (status)"
    antibody_name_md: str | None = None
    antigen_name_md: str | None = None
    payload_name_md: str | None = None
    therapeutic_target_md: str | None = None
    linker_name_md: str | None = None
    reference_count: int = 0
    reference_dois: list[str] = field(default_factory=list)
    nct_ids: list[str] = field(default_factory=list)

    def all_identifiers(self) -> list[str]:
        """Every distinct name-like string this NAR asset is known by --
        used as the candidate pool for matching against our corpus."""
        out = [self.name, self.adc_id]
        if self.brand_name:
            out.append(self.brand_name)
        out.extend(self.synonyms)
        return [x for x in out if x and x.strip()]


def load_nar_inventory(external_root: Path) -> list[dict]:
    path = external_root / "_data" / "adc_inventory.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def is_benchmark_entry(entry: dict) -> bool:
    """True iff this inventory entry has an explicit development-phase tag
    (i.e. was discovered via the site's phase search, not merely a
    cross-linked stub with no asserted clinical status)."""
    return bool(entry.get("status"))


def _parse_general_info_table(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    in_table = False
    for line in lines:
        if line.startswith("## General Information"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                if fields:
                    break
                continue
            m = TABLE_ROW_RE.match(line.rstrip("\n"))
            if not m:
                continue
            field_name, value = m.group(1).strip(), m.group(2).strip()
            if field_name in ("Field", "------") or set(field_name) == {"-"}:
                continue
            fields[field_name] = value
    return fields


def _parse_adc_id_cell(value: str, name: str, adc_id: str) -> str | None:
    """'DRG0ERKBH Trastuzumab deruxtecan Brand Name Enhertu' -> 'Enhertu'."""
    m = re.search(r"Brand Name\s+(.+)", value)
    if not m:
        return None
    return m.group(1).strip().split("  ")[0].strip() or None


def _parse_synonyms_cell(value: str) -> tuple[list[str], list[str]]:
    """'DS-8201; DS-8201a;...;T-DXd Organization Daiichi Sankyo Inc.; AstraZeneca PLC'
    -> (['DS-8201', 'DS-8201a', ..., 'T-DXd'], ['Daiichi Sankyo Inc.', 'AstraZeneca PLC'])."""
    parts = value.split(" Organization ", 1)
    synonyms_part = parts[0]
    companies_part = parts[1] if len(parts) > 1 else ""
    synonyms = [s.strip() for s in re.split(r"[;\n]", synonyms_part) if s.strip()]
    companies = [c.strip().rstrip(".") for c in re.split(r";", companies_part) if c.strip()]
    # Company list can run into unrelated overflow text on rare malformed
    # rows; cap at a generous but bounded count to avoid capturing garbage.
    return synonyms, companies[:10]


def _parse_indication_cell(value: str) -> list[str]:
    parts = [p.strip() for p in INDICATION_SPLIT_RE.split(value) if p.strip()]
    # parts alternate roughly as "<indication> <StatusPhrase> Approval Document ..."
    # -- keep it simple: report each status-keyword-delimited chunk verbatim,
    # truncated, rather than over-parsing an inherently free-text field.
    return [p[:120] for p in parts][:30]


def _parse_linker_cell(value: str) -> str | None:
    m = re.match(r"^(.*?)\s+Info\s+Conjugate Type", value)
    if m:
        return m.group(1).strip() or None
    # Some rows have no "Info Conjugate Type" marker at all (short/simple value).
    return value.strip().split("\n")[0][:80] or None


def parse_adc_markdown(path: Path, asset: NARAsset) -> None:
    with path.open(encoding="utf-8") as f:
        lines = f.readlines()
    fields = _parse_general_info_table(lines)
    asset.md_found = True

    adc_id_value = fields.get("ADC ID", "")
    asset.brand_name = _parse_adc_id_cell(adc_id_value, asset.name, asset.adc_id)

    synonyms_value = fields.get("Synonyms", "")
    asset.synonyms, asset.companies = _parse_synonyms_cell(synonyms_value)

    asset.drug_status_md = fields.get("Drug Status", "").strip() or None
    asset.indications = _parse_indication_cell(fields.get("Indication", ""))
    asset.antibody_name_md = fields.get("Antibody Name", "").strip() or None
    asset.antigen_name_md = fields.get("Antigen Name", "").strip() or None
    asset.payload_name_md = fields.get("Payload Name", "").strip() or None
    asset.therapeutic_target_md = fields.get("Therapeutic Target", "").strip() or None
    asset.linker_name_md = _parse_linker_cell(fields.get("Linker Name", ""))

    full_text = "".join(lines)
    asset.nct_ids = sorted(set(NCT_RE.findall(full_text)))

    # References section: count entries, extract any inline DOIs.
    ref_idx = full_text.find("## References")
    if ref_idx != -1:
        ref_text = full_text[ref_idx:]
        asset.reference_count = len(re.findall(r"^\d+\.\s", ref_text, re.MULTILINE))
        asset.reference_dois = sorted(set(DOI_RE.findall(ref_text)))


def build_nar_benchmark_assets(external_root: Path) -> list[NARAsset]:
    inventory = load_nar_inventory(external_root)
    assets = []
    for entry in inventory:
        if not is_benchmark_entry(entry):
            continue
        asset = NARAsset(
            adc_id=entry["adc_id"],
            name=entry["name"],
            status=entry["status"],
            antibody_name_inv=entry.get("antibody_name", "") or "",
            payload_name_inv=entry.get("payload_name", "") or "",
            linker_name_inv=entry.get("linker_name", "") or "",
            representative_indication_inv=entry.get("representative_indication", "") or "",
        )
        md_path = external_root / "ADCs" / f"{asset.name}.md"
        if md_path.exists():
            parse_adc_markdown(md_path, asset)
        assets.append(asset)
    return assets


# ---------------------------------------------------------------------------
# Our corpus loading
# ---------------------------------------------------------------------------

MANIFEST_NAMES = [
    "pubmed", "europe_pmc", "clinicaltrials", "crossref", "sec", "fda_applications",
    "fda_submissions", "fda_documents", "ema", "ema_documents", "wipo", "epo", "uspto",
    "uspto_documents", "company_pipeline", "patent_bioactivity_corpus",
    "publication_bioactivity_corpus",
]

# For each manifest, which columns hold free text worth grepping for an
# asset name/alias/dev-code/brand mention (title/applicants/sponsors/etc.),
# and which columns hold identifiers worth surfacing when a match is found.
TEXT_COLUMNS = {
    "pubmed": ["title", "abstract"],
    "europe_pmc": ["title", "abstract"],
    "clinicaltrials": ["brief_title", "official_title", "intervention_names", "conditions"],
    "crossref": ["title", "container_title"],
    "sec": ["title", "company"],
    "fda_applications": ["title", "sponsor_name", "brand_names", "active_ingredients"],
    "fda_submissions": ["title"],
    "fda_documents": ["title"],
    "ema": ["title", "active_substance", "marketing_authorisation_holder"],
    "ema_documents": ["title"],
    "wipo": ["title", "applicants", "inventors"],
    "epo": ["title", "applicants", "inventors"],
    "uspto": ["title", "applicants", "inventors", "assignees"],
    "uspto_documents": ["title"],
    "company_pipeline": ["title"],
    "patent_bioactivity_corpus": ["title"],
    "publication_bioactivity_corpus": ["title"],
}

IDENTIFIER_COLUMNS = {
    "pubmed": [("pmid", "pmid"), ("doi", "doi")],
    "europe_pmc": [("pmid", "pmid"), ("doi", "doi"), ("pmcid", "pmcid")],
    "clinicaltrials": [("nct_id", "nct_id")],
    "crossref": [("doi", "doi")],
    "sec": [("accession_number", "accession_number")],
    "fda_applications": [("application_number", "application_number")],
    "ema": [("product_number", "product_number")],
    "wipo": [("publication_number", "publication_number")],
    "epo": [("publication_number", "publication_number")],
    "uspto": [("application_number", "application_number"), ("publication_number", "publication_number")],
    "patent_bioactivity_corpus": [("publication_number", "publication_number")],
    "publication_bioactivity_corpus": [("doi", "doi")],
}


def load_our_manifests(data_dir: Path) -> dict[str, pd.DataFrame]:
    manifests = {}
    for name in MANIFEST_NAMES:
        path = data_dir / "manifests" / f"{name}.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            if not df.empty:
                # Latest version per record only -- an upstream job's manifest
                # is immutable version history, not a flat table of "current
                # facts" (Prompt.md section 23); comparing/matching must only
                # look at each record's most recent state.
                df = df.sort_values("version").groupby("source_record_id", as_index=False).tail(1)
            manifests[name] = df
    return manifests


def load_known_adc_assets(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("assets", [])


DISCOVERY_SOURCES = ["pubmed", "europe_pmc", "wipo", "epo", "uspto", "clinicaltrials"]


def load_discovery_ledgers(data_dir: Path) -> dict[str, pd.DataFrame]:
    ledgers = {}
    for name in DISCOVERY_SOURCES:
        path = data_dir / "manifests" / f"{name}_discovery.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            if not df.empty:
                ledgers[name] = df
    return ledgers


def _ctgov_lookup_query_id(identifier: str) -> str:
    """Reproduces jobs/clinicaltrials/job.py's exact deterministic hash
    scheme for a known-asset --intervention lookup, so a CTGOV_LOOKUP_INTR_*
    query_id in the discovery ledger can be mapped back to the asset
    identifier that produced it -- without needing to re-run the job or
    guess from the hash itself."""
    from adc_acquisition.hashing import sha256_bytes
    lookup_query_text = f"query.intr={identifier}"
    return f"CTGOV_LOOKUP_INTR_{sha256_bytes(lookup_query_text.encode('utf-8'))[:12]}"


def build_discovery_coverage(known_assets: list[KnownAssetIndex], discovery: dict[str, pd.DataFrame]) -> dict[tuple[str, str], int]:
    """(asset_id, source) -> count of DISTINCT discovered records tagged
    with an asset-expansion query_id for that asset in that source's own
    discovery ledger. This is deliberately independent of --limit-capped
    materialization: Job 15's generated query_ids are constructed as
    f"{PREFIX}_{asset_id.upper()}_..." (see query_templates.py), so a
    reverse asset_id lookup from query_id is exact string matching, not a
    fuzzy guess. Discovery reflects what the mechanism actually FOUND,
    independent of how much of it this benchmark run chose to download."""
    counts: dict[tuple[str, str], int] = {}
    ctgov_query_to_asset: dict[str, str] = {}
    for ka in known_assets:
        for identifier in ka.identifiers():
            ctgov_query_to_asset[_ctgov_lookup_query_id(identifier)] = ka.asset_id

    for source, df in discovery.items():
        if source == "clinicaltrials":
            df = df.copy()
            df["_asset_id"] = df["query_id"].map(ctgov_query_to_asset)
        else:
            asset_ids_upper = {ka.asset_id.upper(): ka.asset_id for ka in known_assets}

            def _match_asset(query_id: str) -> str | None:
                if "ASSETEXP_" not in str(query_id):
                    return None
                for upper_id, asset_id in asset_ids_upper.items():
                    if f"ASSETEXP_{upper_id}_" in query_id:
                        return asset_id
                return None

            df = df.copy()
            df["_asset_id"] = df["query_id"].map(_match_asset)

        for asset_id, group in df.dropna(subset=["_asset_id"]).groupby("_asset_id"):
            counts[(asset_id, source)] = group["source_record_id"].nunique()
    return counts


def _row_text_blob(row: pd.Series, columns: list[str]) -> str:
    parts = []
    for col in columns:
        if col not in row.index:
            continue
        val = row[col]
        if val is None:
            continue
        if isinstance(val, (list, tuple)):
            parts.append(" ".join(str(v) for v in val))
        else:
            try:
                if pd.isna(val):
                    continue
            except (TypeError, ValueError):
                pass
            parts.append(str(val))
    return " ".join(parts)


def find_manifest_matches(manifests: dict[str, pd.DataFrame], identifiers: list[str]) -> list[dict]:
    """Case-insensitive whole-word-ish substring search for any of
    `identifiers` across every manifest's designated text columns. Returns
    one dict per (manifest, matched_row, matched_identifier) hit."""
    hits = []
    patterns = [(ident, re.compile(re.escape(ident), re.IGNORECASE)) for ident in identifiers if len(ident) >= 4]
    for name, df in manifests.items():
        cols = TEXT_COLUMNS.get(name, [])
        if not cols or df.empty:
            continue
        for _, row in df.iterrows():
            blob = _row_text_blob(row, cols)
            if not blob:
                continue
            for ident, pattern in patterns:
                if pattern.search(blob):
                    id_cols = IDENTIFIER_COLUMNS.get(name, [])
                    our_identifiers = {label: row.get(col) for col, label in id_cols if col in row.index}
                    hits.append(dict(
                        source=name,
                        source_record_id=row.get("source_record_id"),
                        matched_identifier=ident,
                        query_id=row.get("query_id"),
                        our_identifiers=our_identifiers,
                    ))
    return hits


# ---------------------------------------------------------------------------
# Matching / crosswalk
# ---------------------------------------------------------------------------

def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


@dataclass
class KnownAssetIndex:
    asset_id: str
    canonical_name: str
    aliases: list[str]
    dev_codes: list[str]
    target: str | None
    company: str | None
    active: bool

    def identifiers(self) -> list[str]:
        return [self.canonical_name, *self.aliases, *self.dev_codes]


def build_known_asset_index(known_assets_raw: list[dict]) -> list[KnownAssetIndex]:
    return [
        KnownAssetIndex(
            asset_id=a["asset_id"], canonical_name=a["canonical_name"],
            aliases=list(a.get("aliases") or []), dev_codes=list(a.get("dev_codes") or []),
            target=a.get("target"), company=a.get("company"), active=a.get("active", True),
        )
        for a in known_assets_raw
    ]


def match_nar_to_known_assets(nar: NARAsset, known: list[KnownAssetIndex]) -> tuple[str, str, KnownAssetIndex | None]:
    """Returns (match_type, matched_on, matched_known_asset). Strong
    identifiers only -- exact normalized string equality on canonical
    name/alias/dev-code/brand, never fuzzy/substring for this step."""
    nar_norm = {normalize_name(x) for x in nar.all_identifiers()}
    for ka in known:
        if normalize_name(ka.canonical_name) in nar_norm:
            return "EXACT_NAME", ka.canonical_name, ka
        for alias in ka.aliases:
            if normalize_name(alias) in nar_norm:
                return "ALIAS_MATCH", alias, ka
        for code in ka.dev_codes:
            if normalize_name(code) in nar_norm:
                return "DEV_CODE_MATCH", code, ka
    return "NO_MATCH", "", None


def find_fulltext_matches(data_dir: Path, asset_publication_numbers: set[str], search_terms: list[str]) -> list[dict]:
    """Grep the ACTUAL raw full-text files (patent_bioactivity_corpus's
    description/claims XML) for search_terms, restricted to publications
    already known to belong to this asset. This exists because a
    title/abstract/applicant-only check (find_manifest_matches) will
    systematically under-report: chemistry-level facts like a payload or
    linker name typically appear only in a patent's full specification
    body, not its title -- confirmed directly (WO2021097220A1's
    description mentions "deruxtecan" 204 times and "topoisomerase" 5
    times, neither of which a title/applicant search would ever find)."""
    hits = []
    pbc_path = data_dir / "manifests" / "patent_bioactivity_corpus.parquet"
    if not pbc_path.exists() or not asset_publication_numbers:
        return hits
    pbc = pd.read_parquet(pbc_path)
    if pbc.empty:
        return hits
    candidates = pbc[pbc["publication_number"].isin(asset_publication_numbers)]
    patterns = [(t, re.compile(re.escape(t), re.IGNORECASE)) for t in search_terms if t and len(t) >= 4]
    for _, row in candidates.iterrows():
        raw_path = Path(row["raw_file_path"])
        if not raw_path.exists():
            continue
        try:
            text = raw_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for term, pattern in patterns:
            if pattern.search(text):
                hits.append(dict(
                    source="patent_bioactivity_corpus", source_record_id=row["source_record_id"],
                    matched_identifier=term, query_id=row.get("query_id"),
                    our_identifiers={"publication_number": row["publication_number"], "artifact_type": row["artifact_type"]},
                ))
    return hits


def asset_publication_numbers_from_discovery(asset_id: str, discovery: dict[str, pd.DataFrame]) -> set[str]:
    """publication_numbers discovered (WIPO or EPO) under this asset's own
    asset-expansion query_id -- the link needed to know WHICH patents in
    patent_bioactivity_corpus.parquet (a source-agnostic second-pass
    manifest with no query_id of its own tying back to Job 15) actually
    belong to this asset."""
    pubs = set()
    for source in ("wipo", "epo"):
        df = discovery.get(source)
        if df is None or df.empty:
            continue
        mask = df["query_id"].astype(str).str.contains(f"ASSETEXP_{asset_id.upper()}_", regex=False, na=False)
        pubs |= set(df.loc[mask, "source_record_id"].unique())
    return pubs


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=str, required=True)
    parser.add_argument("--data-dir", type=str, default="DATA")
    parser.add_argument("--known-assets-file", type=str, default="configs/known_adc_assets.yaml")
    parser.add_argument("--output", type=str, default="reports/validation/nar_adcdb_comparison")
    args = parser.parse_args()

    external_root = Path(args.external_root)
    output_dir = Path(args.output)

    print("Loading NAR ADCdb benchmark universe...", file=sys.stderr)
    nar_assets = build_nar_benchmark_assets(external_root)
    print(f"  {len(nar_assets)} phase-tagged NAR assets loaded", file=sys.stderr)

    print("Loading our corpus...", file=sys.stderr)
    manifests = load_our_manifests(Path(args.data_dir))
    known_assets_raw = load_known_adc_assets(Path(args.known_assets_file))
    known_assets = build_known_asset_index(known_assets_raw)
    active_known = [k for k in known_assets if k.active]
    print(f"  {sum(len(df) for df in manifests.values())} materialized records across {len(manifests)} manifests", file=sys.stderr)
    print(f"  {len(active_known)} active known-ADC assets in our Job 15 seed registry", file=sys.stderr)

    # --- asset_crosswalk.tsv ---
    crosswalk_rows = []
    shared_strict = 0
    for nar in nar_assets:
        match_type, matched_on, ka = match_nar_to_known_assets(nar, active_known)
        our_asset = ka.asset_id if ka else ""
        if match_type != "NO_MATCH":
            shared_strict += 1
        crosswalk_rows.append(dict(
            nar_asset=nar.name, nar_adc_id=nar.adc_id, our_asset=our_asset,
            match_type=match_type, match_confidence="high" if match_type != "NO_MATCH" else "",
            nar_aliases="; ".join(nar.synonyms), our_matching_identifier=matched_on,
            target=nar.antigen_name_md or nar.therapeutic_target_md or "",
            company="; ".join(nar.companies) if nar.companies else "",
            nar_status=nar.status, evidence_source="configs/known_adc_assets.yaml",
            notes="",
        ))
    write_tsv(
        output_dir / "asset_crosswalk.tsv", crosswalk_rows,
        ["nar_asset", "nar_adc_id", "our_asset", "match_type", "match_confidence",
         "nar_aliases", "our_matching_identifier", "target", "company", "nar_status",
         "evidence_source", "notes"],
    )
    print(f"asset_crosswalk.tsv: {len(nar_assets)} NAR benchmark assets, {shared_strict} strict matches to our known-asset registry", file=sys.stderr)

    # --- asset_source_coverage.tsv: for each of OUR active known assets,
    # does each of our own manifests contain >=1 MATERIALIZED record whose
    # text matches one of that asset's identifiers, AND separately, how
    # many records did the DISCOVERY ledger find for that asset (which is
    # NOT capped by this benchmark run's --limit choice)? Reporting only
    # the materialized column would understate the mechanism's real reach
    # -- discovery is asset-attributed via query_id regardless of how much
    # got downloaded. ---
    discovery = load_discovery_ledgers(Path(args.data_dir))
    discovery_coverage = build_discovery_coverage(active_known, discovery)

    coverage_rows = []
    for ka in active_known:
        idents = ka.identifiers()
        hits = find_manifest_matches(manifests, idents)
        sources_hit = sorted({h["source"] for h in hits})
        row = dict(asset_id=ka.asset_id, canonical_name=ka.canonical_name)
        for name in MANIFEST_NAMES:
            row[f"{name}_materialized"] = 1 if name in sources_hit else 0
        for name in DISCOVERY_SOURCES:
            row[f"{name}_discovered_count"] = discovery_coverage.get((ka.asset_id, name), 0)
        row["total_matching_records"] = len(hits)
        coverage_rows.append(row)
    coverage_fieldnames = (
        ["asset_id", "canonical_name"]
        + [f"{n}_materialized" for n in MANIFEST_NAMES]
        + [f"{n}_discovered_count" for n in DISCOVERY_SOURCES]
        + ["total_matching_records"]
    )
    write_tsv(output_dir / "asset_source_coverage.tsv", coverage_rows, coverage_fieldnames)
    any_materialized = sum(1 for r in coverage_rows if any(r[f"{n}_materialized"] for n in MANIFEST_NAMES))
    any_discovered = sum(1 for r in coverage_rows if any(r[f"{n}_discovered_count"] for n in DISCOVERY_SOURCES))
    print(
        f"asset_source_coverage.tsv: {len(coverage_rows)} known assets -- "
        f"{any_materialized}/{len(coverage_rows)} have >=1 materialized record in ANY source, "
        f"{any_discovered}/{len(coverage_rows)} have >=1 DISCOVERED record in ANY source",
        file=sys.stderr,
    )

    # --- identifier_overlap.tsv: NCT IDs and DOIs found in NAR free text,
    # for our known assets, checked against our own materialized identifiers ---
    our_nct_ids = set()
    if "clinicaltrials" in manifests and not manifests["clinicaltrials"].empty:
        our_nct_ids = set(manifests["clinicaltrials"]["nct_id"].dropna().astype(str))
    our_dois = set()
    for name in ("pubmed", "europe_pmc", "crossref", "publication_bioactivity_corpus"):
        if name in manifests and not manifests[name].empty and "doi" in manifests[name].columns:
            our_dois |= set(manifests[name]["doi"].dropna().astype(str).str.lower())

    identifier_rows = []
    for nar in nar_assets:
        match_type, _, ka = match_nar_to_known_assets(nar, active_known)
        asset_label = ka.asset_id if ka else nar.name
        for nct in nar.nct_ids:
            identifier_rows.append(dict(
                asset=asset_label, identifier_type="NCT", identifier=nct,
                nar_present=1, ours_present=1 if nct in our_nct_ids else 0,
                our_source="clinicaltrials" if nct in our_nct_ids else "",
                classification="SHARED" if nct in our_nct_ids else "NAR_ONLY",
                notes="",
            ))
        for doi in nar.reference_dois:
            doi_norm = _normalize_doi(doi)
            identifier_rows.append(dict(
                asset=asset_label, identifier_type="DOI", identifier=doi,
                nar_present=1, ours_present=1 if doi_norm in our_dois else 0,
                our_source="pubmed/europe_pmc/crossref" if doi_norm in our_dois else "",
                classification="SHARED" if doi_norm in our_dois else "NAR_ONLY",
                notes="",
            ))
    write_tsv(
        output_dir / "identifier_overlap.tsv", identifier_rows,
        ["asset", "identifier_type", "identifier", "nar_present", "ours_present",
         "our_source", "classification", "notes"],
    )
    n_nct = sum(1 for r in identifier_rows if r["identifier_type"] == "NCT")
    n_nct_shared = sum(1 for r in identifier_rows if r["identifier_type"] == "NCT" and r["classification"] == "SHARED")
    n_doi = sum(1 for r in identifier_rows if r["identifier_type"] == "DOI")
    n_doi_shared = sum(1 for r in identifier_rows if r["identifier_type"] == "DOI" and r["classification"] == "SHARED")
    print(f"identifier_overlap.tsv: NCT {n_nct_shared}/{n_nct} shared, DOI {n_doi_shared}/{n_doi} shared (both counts are PARTIAL -- see report for why PMID/patent overlap isn't computable against this external DB at all)", file=sys.stderr)

    # --- field_recoverability.tsv: for each of our 14 known assets, is
    # each NAR structured field (target/antibody/payload/linker/company/
    # status) STRUCTURED_PRESENT in one of our own manifests (it never is
    # -- we have no ADC-entity schema, by design), RAW_EVIDENCE_PRESENT_
    # NOT_EXTRACTED (the fact is recoverable from raw text we already
    # hold), or NO_EVIDENCE_FOUND. ---
    nar_by_asset_id: dict[str, NARAsset] = {}
    for nar in nar_assets:
        _, _, ka = match_nar_to_known_assets(nar, active_known)
        if ka:
            nar_by_asset_id[ka.asset_id] = nar

    FIELD_CHECKS = ["target", "antibody", "payload", "linker", "company", "status"]
    field_rows = []
    for ka in active_known:
        nar = nar_by_asset_id.get(ka.asset_id)
        if nar is None:
            continue
        nar_values = {
            "target": nar.antigen_name_md or nar.antibody_name_inv or "",
            "antibody": nar.antibody_name_md or nar.antibody_name_inv or "",
            "payload": nar.payload_name_md or nar.payload_name_inv or "",
            "linker": nar.linker_name_md or nar.linker_name_inv or "",
            "company": "; ".join(nar.companies) if nar.companies else "",
            "status": nar.drug_status_md or nar.status,
        }
        asset_pub_numbers = asset_publication_numbers_from_discovery(ka.asset_id, discovery)
        for fname in FIELD_CHECKS:
            nar_value = nar_values[fname]
            search_terms = [nar_value] if nar_value else []
            if fname == "target" and ka.target:
                search_terms.append(ka.target)
            if fname == "company" and ka.company:
                search_terms.append(ka.company)
            search_terms = [t for t in search_terms if t and len(t) >= 4]
            evidence_hits = find_manifest_matches(manifests, search_terms) if search_terms else []
            fulltext_hits = find_fulltext_matches(Path(args.data_dir), asset_pub_numbers, search_terms) if search_terms else []
            all_hits = evidence_hits + fulltext_hits
            raw_present = len(all_hits) > 0
            classification = (
                "RAW_EVIDENCE_PRESENT_NOT_EXTRACTED" if raw_present
                else ("NO_EVIDENCE_FOUND" if nar_value else "NOT_APPLICABLE")
            )
            field_rows.append(dict(
                asset=ka.asset_id, field=fname, nar_value=nar_value[:200],
                our_structured_value="",  # we have no ADC-entity schema by design -- always blank
                raw_evidence_present=1 if raw_present else 0,
                evidence_source=all_hits[0]["source"] if all_hits else "",
                evidence_identifier=all_hits[0]["source_record_id"] if all_hits else "",
                classification=classification, notes="",
            ))
    write_tsv(
        output_dir / "field_recoverability.tsv", field_rows,
        ["asset", "field", "nar_value", "our_structured_value", "raw_evidence_present",
         "evidence_source", "evidence_identifier", "classification", "notes"],
    )
    n_recoverable = sum(1 for r in field_rows if r["classification"] == "RAW_EVIDENCE_PRESENT_NOT_EXTRACTED")
    n_no_evidence = sum(1 for r in field_rows if r["classification"] == "NO_EVIDENCE_FOUND")
    print(f"field_recoverability.tsv: {len(field_rows)} (asset, field) pairs -- {n_recoverable} evidence-recoverable, {n_no_evidence} no evidence found, 0 structured (by design, acquisition-only)", file=sys.stderr)

    # --- ours_only_evidence.tsv: NCT IDs / DOIs we have for known assets
    # that do NOT appear in NAR's own (necessarily curated-highlight, not
    # exhaustive) reference list / free-text NCT mentions. ---
    NAR_PAPER_CUTOFF = "2023-08-31"  # NAR paper's own stated cutoff (see report section 3) -- NOT this local vault's later crawl dates.
    ours_only_rows = []
    if "clinicaltrials" in manifests:
        for ka in active_known:
            nar = nar_by_asset_id.get(ka.asset_id)
            nar_ncts = set(nar.nct_ids) if nar else set()
            idents = ka.identifiers()
            for h in find_manifest_matches({"clinicaltrials": manifests["clinicaltrials"]}, idents):
                nct = h["our_identifiers"].get("nct_id")
                if not nct or nct in nar_ncts:
                    continue
                row = manifests["clinicaltrials"][manifests["clinicaltrials"]["source_record_id"] == h["source_record_id"]].iloc[0]
                start_date = str(row.get("study_first_post_date") or row.get("start_date") or "")
                post_cutoff = bool(start_date) and start_date >= NAR_PAPER_CUTOFF
                ours_only_rows.append(dict(
                    asset_or_candidate=ka.asset_id, identifier_type="NCT", identifier=nct,
                    source="clinicaltrials", date=start_date, nar_cutoff=NAR_PAPER_CUTOFF,
                    classification="NEWER_THAN_NAR_CUTOFF" if post_cutoff else "ADDITIONAL_EVIDENCE_FOR_SHARED_FACT",
                    why_not_in_nar="NAR's per-asset reference/trial mentions are a curated highlight list, not exhaustive -- absence doesn't imply NAR is unaware of this trial.",
                    confidence="medium", notes="",
                ))
    write_tsv(
        output_dir / "ours_only_evidence.tsv", ours_only_rows,
        ["asset_or_candidate", "identifier_type", "identifier", "source", "date",
         "nar_cutoff", "classification", "why_not_in_nar", "confidence", "notes"],
    )
    n_post_cutoff = sum(1 for r in ours_only_rows if r["classification"] == "NEWER_THAN_NAR_CUTOFF")
    print(f"ours_only_evidence.tsv: {len(ours_only_rows)} NCT IDs we have for known assets not in NAR's reference list ({n_post_cutoff} post-cutoff by trial start/posting date)", file=sys.stderr)

    # --- gold_standard_audit.tsv: full trace for every one of our 14
    # known assets -- NAR match -> discovery -> materialization -> field
    # recoverability summary, one row per asset. ---
    gold_rows = []
    field_by_asset: dict[str, list[dict]] = {}
    for r in field_rows:
        field_by_asset.setdefault(r["asset"], []).append(r)
    for ka in active_known:
        nar = nar_by_asset_id.get(ka.asset_id)
        cov_row = next((r for r in coverage_rows if r["asset_id"] == ka.asset_id), {})
        fields_for_asset = field_by_asset.get(ka.asset_id, [])
        n_recoverable_asset = sum(1 for f in fields_for_asset if f["classification"] == "RAW_EVIDENCE_PRESENT_NOT_EXTRACTED")
        total_discovered_all_sources = sum(cov_row.get(f"{n}_discovered_count", 0) for n in DISCOVERY_SOURCES)
        gold_rows.append(dict(
            asset_id=ka.asset_id, canonical_name=ka.canonical_name,
            nar_adc_id=nar.adc_id if nar else "", nar_status=nar.status if nar else "NOT_FOUND_IN_NAR_BENCHMARK",
            known_aliases_used="; ".join(ka.identifiers()),
            nar_extra_synonyms_not_in_our_registry="; ".join(
                s for s in (nar.synonyms if nar else [])
                if normalize_name(s) not in {normalize_name(x) for x in ka.identifiers()}
            )[:300],
            total_discovered_all_sources=total_discovered_all_sources,
            sources_with_discovery=sum(1 for n in DISCOVERY_SOURCES if cov_row.get(f"{n}_discovered_count", 0) > 0),
            sources_with_materialization=sum(1 for n in MANIFEST_NAMES if cov_row.get(f"{n}_materialized", 0)),
            fields_evidence_recoverable=f"{n_recoverable_asset}/{len(fields_for_asset)}",
            notes="",
        ))
    write_tsv(
        output_dir / "gold_standard_audit.tsv", gold_rows,
        ["asset_id", "canonical_name", "nar_adc_id", "nar_status", "known_aliases_used",
         "nar_extra_synonyms_not_in_our_registry", "total_discovered_all_sources",
         "sources_with_discovery", "sources_with_materialization",
         "fields_evidence_recoverable", "notes"],
    )
    print(f"gold_standard_audit.tsv: {len(gold_rows)} known assets traced end-to-end", file=sys.stderr)

    # --- summary_metrics.tsv ---
    summary = [
        ("N_NAR_benchmark_assets_phase_tagged", len(nar_assets)),
        ("N_NAR_assets_approved_subset", sum(1 for n in nar_assets if n.status == "Approved")),
        ("N_our_active_known_assets", len(active_known)),
        ("N_shared_strict_asset_match", shared_strict),
        ("asset_strict_recall_vs_702", round(shared_strict / len(nar_assets), 4) if nar_assets else 0),
        ("N_known_assets_with_materialized_evidence_any_source", any_materialized),
        ("N_known_assets_with_discovered_evidence_any_source", any_discovered),
        ("NCT_overlap_shared", n_nct_shared),
        ("NCT_overlap_nar_total", n_nct),
        ("DOI_overlap_shared", n_doi_shared),
        ("DOI_overlap_nar_total", n_doi),
        ("PMID_overlap_computable", "NO -- NAR exposes no PMID field per-ADC (see report section 3)"),
        ("patent_identifier_overlap_computable", "NO -- 0/6235 NAR ADC pages mention patents at all (see report section 3)"),
        ("field_recoverability_evidence_recoverable_pairs", n_recoverable),
        ("field_recoverability_no_evidence_pairs", n_no_evidence),
        ("field_recoverability_total_pairs", len(field_rows)),
        ("ours_only_NCT_evidence_for_known_assets", len(ours_only_rows)),
        ("ours_only_NCT_post_NAR_cutoff", n_post_cutoff),
    ]
    write_tsv(
        output_dir / "summary_metrics.tsv",
        [dict(metric=k, value=v) for k, v in summary],
        ["metric", "value"],
    )
    print("summary_metrics.tsv written", file=sys.stderr)

    print(f"\nDone. Outputs written to {output_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
