"""Parsing for EPO OPS search results and per-publication bibliographic
data (see jobs/wipo/client.py for the live-verified endpoint/CQL shapes).

OPS responses are namespaced XML (default namespace
http://www.epo.org/exchange, ops: http://ops.epo.org). We strip namespace
prefixes on parse rather than registering them, since we only need to read
data out, not validate or re-serialize the document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _strip_ns(elem: ET.Element) -> ET.Element:
    for e in elem.iter():
        e.tag = _local(e.tag)
    return elem


@dataclass
class SearchHit:
    family_id: str
    country: str
    doc_number: str
    kind: str

    @property
    def publication_number(self) -> str:
        return f"{self.country}{self.doc_number}{self.kind}"

    @property
    def docdb_id(self) -> str:
        return f"{self.country}.{self.doc_number}.{self.kind}"


def parse_search_response(xml_bytes: bytes) -> tuple[list[SearchHit], int]:
    """Returns (hits on this page, total_result_count for the whole query)."""
    root = _strip_ns(ET.fromstring(xml_bytes))
    biblio_search = root.find(".//biblio-search")
    total_count = int(biblio_search.get("total-result-count")) if biblio_search is not None else 0

    hits: list[SearchHit] = []
    for pub_ref in root.findall(".//search-result/publication-reference"):
        family_id = pub_ref.get("family-id") or ""
        doc_id = pub_ref.find("./document-id[@document-id-type='docdb']")
        if doc_id is None:
            continue
        country = (doc_id.findtext("country") or "").strip()
        doc_number = (doc_id.findtext("doc-number") or "").strip()
        kind = (doc_id.findtext("kind") or "").strip()
        if not (country and doc_number and kind):
            continue
        hits.append(SearchHit(family_id=family_id, country=country, doc_number=doc_number, kind=kind))
    return hits, total_count


@dataclass
class ParsedPublication:
    publication_number: str
    family_id: str | None
    application_number: str | None
    filing_date: str | None
    priority_date: str | None
    publication_date: str | None
    title: str | None
    abstract: str | None
    applicants: list[str] = field(default_factory=list)
    inventors: list[str] = field(default_factory=list)
    ipc_classes: list[str] = field(default_factory=list)
    cpc_classes: list[str] = field(default_factory=list)


def _normalize_date(raw: str | None) -> str | None:
    if not raw or len(raw) != 8 or not raw.isdigit():
        return raw
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def _preferred_lang_text(elems: list[ET.Element]) -> str | None:
    by_lang = {e.get("lang"): (e.text or "").strip() for e in elems}
    return by_lang.get("en") or next(iter(by_lang.values()), None)


def _names(container: ET.Element | None, tag: str) -> list[str]:
    if container is None:
        return []
    names = []
    seen = set()
    for entry in container.findall(f"./{tag}[@data-format='original']"):
        name_el = entry.find(f"./{tag}-name/name")
        if name_el is not None and name_el.text:
            name = name_el.text.strip()
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def parse_biblio_response(xml_bytes: bytes) -> ParsedPublication | None:
    root = _strip_ns(ET.fromstring(xml_bytes))
    doc = root.find(".//exchange-document")
    if doc is None:
        return None

    country = doc.get("country") or ""
    doc_number = doc.get("doc-number") or ""
    kind = doc.get("kind") or ""
    publication_number = f"{country}{doc_number}{kind}"
    family_id = doc.get("family-id")

    biblio = doc.find("./bibliographic-data")

    application_number = None
    filing_date = None
    app_ref = biblio.find("./application-reference") if biblio is not None else None
    if app_ref is not None:
        epodoc = app_ref.find("./document-id[@document-id-type='epodoc']")
        if epodoc is not None:
            application_number = (epodoc.findtext("doc-number") or "").strip() or None
            filing_date = _normalize_date((epodoc.findtext("date") or "").strip() or None)

    priority_date = None
    if biblio is not None:
        priority_dates = [
            d for d in (
                (pc.find("./document-id[@document-id-type='epodoc']").findtext("date") or "").strip()
                for pc in biblio.findall("./priority-claims/priority-claim")
                if pc.find("./document-id[@document-id-type='epodoc']") is not None
            )
            if d
        ]
        if priority_dates:
            priority_date = _normalize_date(min(priority_dates))

    publication_date = None
    if biblio is not None:
        pub_docdb = biblio.find("./publication-reference/document-id[@document-id-type='docdb']")
        if pub_docdb is not None:
            publication_date = _normalize_date((pub_docdb.findtext("date") or "").strip() or None)

    title = None
    if biblio is not None:
        title = _preferred_lang_text(biblio.findall("./invention-title"))

    abstract = None
    abstracts_by_lang = {a.get("lang"): a for a in doc.findall("./abstract")}
    chosen_abstract = abstracts_by_lang["en"] if "en" in abstracts_by_lang else next(iter(abstracts_by_lang.values()), None)
    if chosen_abstract is not None:
        p = chosen_abstract.find("./p")
        if p is not None and p.text:
            abstract = p.text.strip()

    parties = biblio.find("./parties") if biblio is not None else None
    applicants = _names(parties.find("./applicants") if parties is not None else None, "applicant")
    inventors = _names(parties.find("./inventors") if parties is not None else None, "inventor")

    ipc_classes = []
    cpc_classes = []
    if biblio is not None:
        for c in biblio.findall("./classifications-ipcr/classification-ipcr/text"):
            if c.text:
                ipc_classes.append(" ".join(c.text.split()))
        for c in biblio.findall("./patent-classifications/patent-classification"):
            parts = [c.findtext(tag) or "" for tag in ("section", "class", "subclass", "main-group", "subgroup")]
            code = "".join(parts[:3]) + " " + "/".join(parts[3:])
            cpc_classes.append(code.strip())

    return ParsedPublication(
        publication_number=publication_number,
        family_id=family_id,
        application_number=application_number,
        filing_date=filing_date,
        priority_date=priority_date,
        publication_date=publication_date,
        title=title,
        abstract=abstract,
        applicants=applicants,
        inventors=inventors,
        ipc_classes=ipc_classes,
        cpc_classes=cpc_classes,
    )
