from jobs.wipo.parser import parse_biblio_response, parse_search_response

SEARCH_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ops:world-patent-data xmlns="http://www.epo.org/exchange" xmlns:ops="http://ops.epo.org">
    <ops:biblio-search total-result-count="2">
        <ops:range begin="1" end="2"/>
        <ops:search-result>
            <ops:publication-reference system="ops.epo.org" family-id="111">
                <document-id document-id-type="docdb">
                    <country>WO</country>
                    <doc-number>2026163182</doc-number>
                    <kind>A1</kind>
                </document-id>
            </ops:publication-reference>
            <ops:publication-reference system="ops.epo.org" family-id="222">
                <document-id document-id-type="docdb">
                    <country>WO</country>
                    <doc-number>2025000111</doc-number>
                    <kind>A2</kind>
                </document-id>
            </ops:publication-reference>
        </ops:search-result>
    </ops:biblio-search>
</ops:world-patent-data>
"""

BIBLIO_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ops:world-patent-data xmlns="http://www.epo.org/exchange" xmlns:ops="http://ops.epo.org">
    <exchange-documents>
        <exchange-document system="ops.epo.org" family-id="111" country="WO" doc-number="2026163182" kind="A1">
            <bibliographic-data>
                <publication-reference>
                    <document-id document-id-type="docdb">
                        <country>WO</country>
                        <doc-number>2026163182</doc-number>
                        <kind>A1</kind>
                        <date>20260806</date>
                    </document-id>
                </publication-reference>
                <classifications-ipcr>
                    <classification-ipcr sequence="1"><text>A61K  47/    68            A I</text></classification-ipcr>
                </classifications-ipcr>
                <patent-classifications>
                    <patent-classification sequence="1">
                        <classification-scheme office="EP" scheme="CPCI"/>
                        <section>A</section><class>61</class><subclass>K</subclass>
                        <main-group>47</main-group><subgroup>68033</subgroup>
                    </patent-classification>
                </patent-classifications>
                <application-reference doc-id="1">
                    <document-id document-id-type="epodoc">
                        <doc-number>WO2026IB51003</doc-number>
                        <date>20260203</date>
                    </document-id>
                </application-reference>
                <priority-claims>
                    <priority-claim sequence="1" kind="national">
                        <document-id document-id-type="epodoc">
                            <doc-number>US202563753186P</doc-number>
                            <date>20250203</date>
                        </document-id>
                    </priority-claim>
                    <priority-claim sequence="2" kind="national">
                        <document-id document-id-type="epodoc">
                            <doc-number>US202563774559P</doc-number>
                            <date>20250101</date>
                        </document-id>
                    </priority-claim>
                </priority-claims>
                <invention-title lang="fr">CONJUGUES</invention-title>
                <invention-title lang="en">CD26 ANTIBODY DRUG CONJUGATES</invention-title>
                <parties>
                    <applicants>
                        <applicant sequence="1" data-format="epodoc">
                            <applicant-name><name>ADIENNE PHARMA [CH]</name></applicant-name>
                        </applicant>
                        <applicant sequence="1" data-format="original">
                            <applicant-name><name>Adienne Pharma S.A.</name></applicant-name>
                        </applicant>
                    </applicants>
                    <inventors>
                        <inventor sequence="1" data-format="epodoc">
                            <inventor-name><name>DI NARO [CH]</name></inventor-name>
                        </inventor>
                        <inventor sequence="1" data-format="original">
                            <inventor-name><name>Di Naro, Antonio</name></inventor-name>
                        </inventor>
                    </inventors>
                </parties>
            </bibliographic-data>
            <abstract lang="en"><p>An antibody drug conjugate for cancer.</p></abstract>
            <abstract lang="fr"><p>Un conjugue anticorps.</p></abstract>
        </exchange-document>
    </exchange-documents>
</ops:world-patent-data>
"""


def test_parse_search_response_returns_hits_and_total():
    hits, total = parse_search_response(SEARCH_XML)
    assert total == 2
    assert len(hits) == 2
    assert hits[0].publication_number == "WO2026163182A1"
    assert hits[0].docdb_id == "WO.2026163182.A1"
    assert hits[0].family_id == "111"
    assert hits[1].publication_number == "WO2025000111A2"


def test_parse_biblio_response_extracts_all_fields():
    pub = parse_biblio_response(BIBLIO_XML)
    assert pub.publication_number == "WO2026163182A1"
    assert pub.family_id == "111"
    assert pub.application_number == "WO2026IB51003"
    assert pub.filing_date == "2026-02-03"
    assert pub.priority_date == "2025-01-01"  # earliest of the two priority claims
    assert pub.publication_date == "2026-08-06"
    assert pub.title == "CD26 ANTIBODY DRUG CONJUGATES"  # prefers English
    assert pub.abstract == "An antibody drug conjugate for cancer."
    assert pub.applicants == ["Adienne Pharma S.A."]  # only data-format="original"
    assert pub.inventors == ["Di Naro, Antonio"]
    assert pub.ipc_classes == ["A61K 47/ 68 A I"]
    assert pub.cpc_classes == ["A61K 47/68033"]


def test_parse_biblio_response_missing_document_returns_none():
    empty_xml = b'<?xml version="1.0"?><ops:world-patent-data xmlns:ops="http://ops.epo.org"><exchange-documents/></ops:world-patent-data>'
    assert parse_biblio_response(empty_xml) is None
