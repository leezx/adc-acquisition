"""Normalize EMA's bulk medicines/documents JSON feeds.

Both feeds are {"meta": {...}, "data": [...]} with one dict per record —
verified live on 2026-08-12 (2,730 medicines; 20,099 documents across all
EMA medicines). Each medicine dict IS its own raw record already (no
column-index reconstruction needed, unlike the XLSX export); each
document dict carries its own stable `id`, `ema_product_number`,
`type`, and first_published/last_updated dates independent of any
medicine's own record. Defensive throughout: a missing field must never
crash the batch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class ParsedMedicine:
    product_number: str
    name: str | None
    status: str | None
    active_substance: str | None
    therapeutic_area: str | None
    marketing_authorisation_holder: str | None
    decision_date: str | None  # normalized YYYY-MM-DD
    authorisation_date: str | None
    withdrawal_date: str | None
    last_updated_date: str | None
    epar_url: str | None
    raw_row: dict  # the exact record dict from the bulk feed


@dataclass
class ParsedDocument:
    doc_id: str
    product_number: str
    doc_type: str | None
    url: str | None
    first_published: str | None  # normalized YYYY-MM-DD
    last_updated: str | None
    raw_row: dict


_UK_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def normalize_ema_date(raw) -> str | None:
    """The medicines feed uses DD/MM/YYYY strings; the documents feed
    uses full ISO-8601 datetimes. The universal manifest contract wants
    YYYY-MM-DD either way."""
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    m = _ISO_DATE_RE.match(raw)
    if m:
        return m.group(1)
    m = _UK_DATE_RE.match(raw)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month}-{day}"
    return None


def parse_medicines_json(json_bytes: bytes) -> list[ParsedMedicine]:
    data = json.loads(json_bytes).get("data") or []
    medicines = []
    for row in data:
        product_number = row.get("ema_product_number")
        if not product_number:
            continue
        medicines.append(
            ParsedMedicine(
                product_number=product_number,
                name=row.get("name_of_medicine"),
                status=row.get("medicine_status"),
                active_substance=row.get("active_substance"),
                therapeutic_area=row.get("therapeutic_area_mesh"),
                marketing_authorisation_holder=row.get("marketing_authorisation_developer_applicant_holder"),
                decision_date=normalize_ema_date(row.get("european_commission_decision_date")),
                authorisation_date=normalize_ema_date(row.get("marketing_authorisation_date")),
                withdrawal_date=normalize_ema_date(
                    row.get("withdrawal_expiry_revocation_lapse_of_marketing_authorisation_date")
                ),
                last_updated_date=normalize_ema_date(row.get("last_updated_date")),
                epar_url=row.get("medicine_url"),
                raw_row=row,
            )
        )
    return medicines


def parse_epar_documents_json(json_bytes: bytes) -> list[ParsedDocument]:
    data = json.loads(json_bytes).get("data") or []
    documents = []
    for row in data:
        doc_id = row.get("id")
        product_number = row.get("ema_product_number")
        url = row.get("document_url")
        if not doc_id or not product_number or not url:
            continue
        documents.append(
            ParsedDocument(
                doc_id=str(doc_id),
                product_number=product_number,
                doc_type=row.get("type"),
                url=url,
                first_published=normalize_ema_date(row.get("first_published_date")),
                last_updated=normalize_ema_date(row.get("last_updated_date")),
                raw_row=row,
            )
        )
    return documents


def is_adc_candidate(medicine: ParsedMedicine, substance_patterns: list[str]) -> bool:
    """Systematic INN-suffix matching (vedotin, emtansine, deruxtecan, ...
    — standardized WHO INN stems for ADC linker/payload chemistry), not a
    manually maintained list of specific approved drug names — this
    catches future ADCs using the same naming convention without needing
    per-drug updates, same spirit as Job 06 (FDA)'s full-text
    "antibody-drug conjugate" label search."""
    haystack = f"{medicine.name or ''} {medicine.active_substance or ''}".lower()
    return any(pattern.lower() in haystack for pattern in substance_patterns)


def within_date_range(date_str: str | None, since: str | None, until: str | None) -> bool:
    """Lexicographic YYYY-MM-DD comparison — same convention as
    jobs/sec/parser.py and jobs/fda/parser.py."""
    if not since and not until:
        return True
    if not date_str:
        return False
    if since and date_str < since:
        return False
    if until and date_str > until:
        return False
    return True
