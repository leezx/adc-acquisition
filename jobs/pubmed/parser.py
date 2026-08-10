"""Parse NCBI efetch PubmedArticleSet XML into per-article raw fragments and
normalized metadata dicts.

Every field lookup is defensive (missing/malformed XML must not crash the
whole batch — Prompt.md section 25 requires malformed-response handling to
be tested, and a batch of 200 articles should not be lost because one is
missing a DOI).
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

_MONTH_NUMBERS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _normalize_month(month: str) -> str:
    """PubMed gives Month as either "10" or "Oct". Normalize to zero-padded
    numeric form; leave season names (e.g. "Winter") as-is since they aren't
    a real month."""
    if month.isdigit():
        return month.zfill(2)
    return _MONTH_NUMBERS.get(month[:3].lower(), month)


@dataclass
class ParsedArticle:
    pmid: str
    raw_xml: bytes
    title: str | None
    abstract: str | None
    authors: list[str]
    journal: str | None
    publication_date: str | None
    doi: str | None
    pmcid: str | None
    publication_types: list[str]
    mesh_terms: list[str]


def _text(elem, path: str) -> str | None:
    node = elem.find(path)
    if node is None or node.text is None:
        return None
    return node.text.strip() or None


def _join_text(elem, path: str, sep: str = " ") -> str | None:
    node = elem.find(path)
    if node is None:
        return None
    text = "".join(node.itertext()).strip()
    return text or None


def parse_pmid(article_elem: ET.Element) -> str | None:
    return _text(article_elem, "./MedlineCitation/PMID")


def parse_title(article_elem: ET.Element) -> str | None:
    return _join_text(article_elem, "./MedlineCitation/Article/ArticleTitle")


def parse_abstract(article_elem: ET.Element) -> str | None:
    abstract_node = article_elem.find("./MedlineCitation/Article/Abstract")
    if abstract_node is None:
        return None
    parts = []
    for abstract_text in abstract_node.findall("AbstractText"):
        label = abstract_text.get("Label")
        text = "".join(abstract_text.itertext()).strip()
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    return "\n\n".join(parts) or None


def parse_authors(article_elem: ET.Element) -> list[str]:
    authors: list[str] = []
    author_list = article_elem.find("./MedlineCitation/Article/AuthorList")
    if author_list is None:
        return authors
    for author in author_list.findall("Author"):
        collective = _text(author, "CollectiveName")
        if collective:
            authors.append(collective)
            continue
        last_name = _text(author, "LastName")
        initials = _text(author, "Initials")
        if last_name and initials:
            authors.append(f"{last_name} {initials}")
        elif last_name:
            authors.append(last_name)
    return authors


def parse_journal(article_elem: ET.Element) -> str | None:
    return _text(article_elem, "./MedlineCitation/Article/Journal/Title") or _text(
        article_elem, "./MedlineCitation/Article/Journal/ISOAbbreviation"
    )


def parse_publication_date(article_elem: ET.Element) -> str | None:
    pub_date = article_elem.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None
    medline_date = _text(pub_date, "MedlineDate")
    if medline_date:
        return medline_date
    year = _text(pub_date, "Year")
    month = _text(pub_date, "Month")
    day = _text(pub_date, "Day")
    if not year:
        return None
    parts = [year]
    if month:
        parts.append(_normalize_month(month))
        if day:
            parts.append(day.zfill(2))
    return "-".join(parts)


def parse_doi(article_elem: ET.Element) -> str | None:
    for article_id in article_elem.findall("./PubmedData/ArticleIdList/ArticleId"):
        if article_id.get("IdType") == "doi" and article_id.text:
            return article_id.text.strip()
    for elocation_id in article_elem.findall("./MedlineCitation/Article/ELocationID"):
        if elocation_id.get("EIdType") == "doi" and elocation_id.text:
            return elocation_id.text.strip()
    return None


def parse_pmcid(article_elem: ET.Element) -> str | None:
    for article_id in article_elem.findall("./PubmedData/ArticleIdList/ArticleId"):
        if article_id.get("IdType") == "pmc" and article_id.text:
            return article_id.text.strip()
    return None


def parse_publication_types(article_elem: ET.Element) -> list[str]:
    types = []
    for pub_type in article_elem.findall("./MedlineCitation/Article/PublicationTypeList/PublicationType"):
        if pub_type.text:
            types.append(pub_type.text.strip())
    return types


def parse_mesh_terms(article_elem: ET.Element) -> list[str]:
    terms = []
    for heading in article_elem.findall("./MedlineCitation/MeshHeadingList/MeshHeading"):
        descriptor = heading.find("DescriptorName")
        if descriptor is not None and descriptor.text:
            terms.append(descriptor.text.strip())
    return terms


def parse_pubmed_articleset(raw_xml: bytes) -> list[ParsedArticle]:
    """Split a PubmedArticleSet response into one ParsedArticle per
    <PubmedArticle>, each carrying its own re-serialized raw XML fragment
    for independent storage/hashing.

    Raises ET.ParseError on genuinely malformed XML — callers must catch
    this and record a failure rather than let it crash the whole run.
    """
    root = ET.fromstring(raw_xml)
    articles: list[ParsedArticle] = []
    for article_elem in root.findall("./PubmedArticle"):
        pmid = parse_pmid(article_elem)
        if not pmid:
            # Cannot store/checkpoint a record without an identifier; skip it
            # rather than raise, so the rest of the batch still succeeds.
            continue
        articles.append(
            ParsedArticle(
                pmid=pmid,
                raw_xml=ET.tostring(article_elem, encoding="utf-8"),
                title=parse_title(article_elem),
                abstract=parse_abstract(article_elem),
                authors=parse_authors(article_elem),
                journal=parse_journal(article_elem),
                publication_date=parse_publication_date(article_elem),
                doi=parse_doi(article_elem),
                pmcid=parse_pmcid(article_elem),
                publication_types=parse_publication_types(article_elem),
                mesh_terms=parse_mesh_terms(article_elem),
            )
        )
    return articles
