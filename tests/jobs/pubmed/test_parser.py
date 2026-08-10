from xml.etree import ElementTree as ET

import pytest

from jobs.pubmed.parser import parse_pubmed_articleset

FULL_ARTICLE_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">12345</PMID>
    <Article>
      <Journal>
        <Title>Journal of Testing</Title>
        <JournalIssue><PubDate><Year>2021</Year><Month>Mar</Month><Day>5</Day></PubDate></JournalIssue>
      </Journal>
      <ArticleTitle>An ADC Study</ArticleTitle>
      <Abstract>
        <AbstractText Label="BACKGROUND">Background text.</AbstractText>
        <AbstractText Label="METHODS">Methods text.</AbstractText>
      </Abstract>
      <AuthorList>
        <Author><LastName>Smith</LastName><Initials>J</Initials></Author>
        <Author><CollectiveName>Some Consortium</CollectiveName></Author>
      </AuthorList>
      <PublicationTypeList>
        <PublicationType>Journal Article</PublicationType>
      </PublicationTypeList>
      <ELocationID EIdType="doi">10.1000/fallback-doi</ELocationID>
    </Article>
    <MeshHeadingList>
      <MeshHeading><DescriptorName>Antibodies</DescriptorName></MeshHeading>
    </MeshHeadingList>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">12345</ArticleId>
      <ArticleId IdType="doi">10.1000/xyz123</ArticleId>
      <ArticleId IdType="pmc">PMC999</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""

MINIMAL_ARTICLE_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">999</PMID>
    <Article>
      <ArticleTitle>No abstract here</ArticleTitle>
    </Article>
  </MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>
"""

ARTICLE_MISSING_PMID_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <Article><ArticleTitle>Orphan</ArticleTitle></Article>
  </MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>
"""

EMPTY_ARTICLESET_XML = b"""<?xml version="1.0"?><PubmedArticleSet></PubmedArticleSet>"""

MALFORMED_XML = b"<PubmedArticleSet><PubmedArticle><Unclosed>"


def test_parses_full_article_fields():
    [article] = parse_pubmed_articleset(FULL_ARTICLE_XML)
    assert article.pmid == "12345"
    assert article.title == "An ADC Study"
    assert "Background text." in article.abstract
    assert "BACKGROUND: Background text." in article.abstract
    assert article.journal == "Journal of Testing"
    assert article.publication_date == "2021-03-05"
    assert article.doi == "10.1000/xyz123"  # PubmedData ArticleId wins over ELocationID fallback
    assert article.pmcid == "PMC999"
    assert article.authors == ["Smith J", "Some Consortium"]
    assert article.publication_types == ["Journal Article"]
    assert article.mesh_terms == ["Antibodies"]
    assert article.raw_xml.startswith(b"<PubmedArticle>")


def test_falls_back_to_elocation_doi_when_no_pubmeddata_doi():
    xml = FULL_ARTICLE_XML.replace(b'<ArticleId IdType="doi">10.1000/xyz123</ArticleId>', b"")
    [article] = parse_pubmed_articleset(xml)
    assert article.doi == "10.1000/fallback-doi"


def test_minimal_article_has_none_for_missing_optional_fields():
    [article] = parse_pubmed_articleset(MINIMAL_ARTICLE_XML)
    assert article.pmid == "999"
    assert article.title == "No abstract here"
    assert article.abstract is None
    assert article.doi is None
    assert article.pmcid is None
    assert article.authors == []
    assert article.mesh_terms == []


def test_article_without_pmid_is_skipped_not_crashed():
    articles = parse_pubmed_articleset(ARTICLE_MISSING_PMID_XML)
    assert articles == []


def test_empty_articleset_returns_empty_list():
    assert parse_pubmed_articleset(EMPTY_ARTICLESET_XML) == []


def test_malformed_xml_raises_parse_error_for_caller_to_handle():
    with pytest.raises(ET.ParseError):
        parse_pubmed_articleset(MALFORMED_XML)


def test_month_only_numeric_is_not_double_normalized():
    xml = FULL_ARTICLE_XML.replace(b"<Month>Mar</Month>", b"<Month>3</Month>")
    [article] = parse_pubmed_articleset(xml)
    assert article.publication_date == "2021-03-05"


def test_unrecognized_season_month_left_as_is():
    xml = FULL_ARTICLE_XML.replace(b"<Month>Mar</Month><Day>5</Day>", b"<Month>Spring</Month>")
    [article] = parse_pubmed_articleset(xml)
    assert article.publication_date == "2021-Spring"
