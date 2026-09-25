"""Source-format fixtures (ClinicalTrials.gov v2 JSON, PubMed XML, openFDA JSON).

Used by the demo seed, contract tests and the golden evaluation set. Records are *illustrative*
(names, NCT numbers in the NCT99xxxxxx range, PMIDs 99xxxxxx are fictitious) but structurally identical
to the real APIs, so they exercise the real adapters' parse() code paths.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from app.connectors.base import FetchContext, FetchedRecord
from app.connectors.clinicaltrials import ClinicalTrialsGovAdapter
from app.connectors.openfda import DrugLabelAdapter, DrugsAtFDAAdapter
from app.connectors.pubmed import PubMedAdapter


def ctgov_study(
    nct: str, title: str, sponsor: str, phase: list[str], status: str, enrollment: int, start: str, pcd: str,
    cd: str, conditions: list[str], drug: str, other_names: list[str] | None = None,
    primary: list[tuple[str, str]] | None = None, secondary: list[tuple[str, str]] | None = None,
    eligibility: str = "", countries: list[str] | None = None, acronym: str | None = None,
    comparator: str | None = "Docetaxel", last_update: str = "2026-09-01", pcd_type: str = "ANTICIPATED",
    summary: str = "",
) -> dict[str, Any]:
    arms = [{"label": f"{drug} arm", "type": "EXPERIMENTAL", "description": f"{drug} monotherapy",
             "interventionNames": [f"Drug: {drug}"]}]
    interventions = [{"type": "DRUG", "name": drug, "otherNames": other_names or []}]
    if comparator:
        arms.append({"label": f"{comparator} arm", "type": "ACTIVE_COMPARATOR", "description": f"{comparator} per label",
                     "interventionNames": [f"Drug: {comparator}"]})
        interventions.append({"type": "DRUG", "name": comparator, "otherNames": []})
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": title, "officialTitle": f"A {title}", "acronym": acronym},
            "statusModule": {
                "overallStatus": status,
                "startDateStruct": {"date": start},
                "primaryCompletionDateStruct": {"date": pcd, "type": pcd_type},
                "completionDateStruct": {"date": cd, "type": "ANTICIPATED"},
                "lastUpdatePostDateStruct": {"date": last_update},
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor, "class": "INDUSTRY"}},
            "descriptionModule": {"briefSummary": summary or f"This study evaluates {drug} in participants with "
                                                             f"{', '.join(conditions)}."},
            "conditionsModule": {"conditions": conditions, "keywords": ["targeted therapy"]},
            "designModule": {"studyType": "INTERVENTIONAL", "phases": phase,
                             "enrollmentInfo": {"count": enrollment, "type": "ESTIMATED"}},
            "armsInterventionsModule": {"armGroups": arms, "interventions": interventions},
            "outcomesModule": {
                "primaryOutcomes": [{"measure": m, "timeFrame": t} for m, t in (primary or [])],
                "secondaryOutcomes": [{"measure": m, "timeFrame": t} for m, t in (secondary or [])],
            },
            "eligibilityModule": {"eligibilityCriteria": eligibility, "minimumAge": "18 Years", "sex": "ALL"},
            "contactsLocationsModule": {"locations": [{"facility": f"Site {i + 1}", "city": "City", "country": c,
                                                       "status": "RECRUITING"} for i, c in enumerate(countries or ["United States"])]},
        }
    }


def pubmed_article(pmid: str, title: str, abstract: list[tuple[str, str]], journal: str, year: int, month: int,
                   authors: list[tuple[str, str, str]], chemicals: list[str] | None = None,
                   mesh: list[str] | None = None, nct_ids: list[str] | None = None, doi: str | None = None,
                   pub_types: list[str] | None = None) -> bytes:
    from xml.sax.saxutils import escape

    ab = "".join(f'<AbstractText Label="{escape(label)}">{escape(text)}</AbstractText>' for label, text in abstract)
    au = "".join(f"<Author><LastName>{escape(ln)}</LastName><ForeName>{escape(fn)}</ForeName>"
                 f"<AffiliationInfo><Affiliation>{escape(aff)}</Affiliation></AffiliationInfo></Author>"
                 for fn, ln, aff in authors)
    chem = "".join(f"<Chemical><NameOfSubstance>{escape(c)}</NameOfSubstance></Chemical>" for c in chemicals or [])
    mh = "".join(f"<MeshHeading><DescriptorName>{escape(m)}</DescriptorName></MeshHeading>" for m in mesh or [])
    db = ("<DataBankList><DataBank><DataBankName>ClinicalTrials.gov</DataBankName><AccessionNumberList>"
          + "".join(f"<AccessionNumber>{n}</AccessionNumber>" for n in nct_ids or [])
          + "</AccessionNumberList></DataBank></DataBankList>") if nct_ids else ""
    doi_x = f'<ArticleId IdType="doi">{doi}</ArticleId>' if doi else ""
    pt = "<PublicationTypeList>" + "".join(f"<PublicationType>{escape(t)}</PublicationType>"
                                           for t in pub_types or ["Journal Article"]) + "</PublicationTypeList>"
    xml = (f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><Journal><Title>{escape(journal)}</Title>"
           f"<JournalIssue><PubDate><Year>{year}</Year><Month>{month:02d}</Month></PubDate></JournalIssue></Journal>"
           f"<ArticleTitle>{escape(title)}</ArticleTitle><Abstract>{ab}</Abstract><AuthorList>{au}</AuthorList>{db}{pt}"
           f"</Article><ChemicalList>{chem}</ChemicalList><MeshHeadingList>{mh}</MeshHeadingList></MedlineCitation>"
           f"<PubmedData><ArticleIdList><ArticleId IdType=\"pubmed\">{pmid}</ArticleId>{doi_x}</ArticleIdList>"
           f"</PubmedData></PubmedArticle>")
    return xml.encode()


class FixtureCTGovAdapter(ClinicalTrialsGovAdapter):
    """Serves fixture studies through the real adapter's parse path (contract tests / demo / eval)."""

    def __init__(self, studies: list[dict[str, Any]], retrieved_at: datetime | None = None):
        self.studies = studies
        self.retrieved_at = retrieved_at or datetime.now(UTC)
        self.http = None  # type: ignore[assignment]

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        for st in self.studies:
            nct = st["protocolSection"]["identificationModule"]["nctId"]
            yield self._record(nct, json.dumps(st, sort_keys=True).encode(), f"fixture://ctgov/{nct}",
                               self.retrieved_at, {"mode": "fixture"})

    def close(self) -> None:
        pass


class FixturePubMedAdapter(PubMedAdapter):
    def __init__(self, articles: list[tuple[str, bytes]], retrieved_at: datetime | None = None):
        self.articles = articles
        self.retrieved_at = retrieved_at or datetime.now(UTC)
        self.http = None  # type: ignore[assignment]

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        for pmid, xml in self.articles:
            yield FetchedRecord(pmid, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", xml, "application/xml",
                                self.retrieved_at, query_provenance={"query": "fixture"})

    def close(self) -> None:
        pass


class FixtureLabelAdapter(DrugLabelAdapter):
    def __init__(self, labels: list[dict[str, Any]], retrieved_at: datetime | None = None):
        self.labels = labels
        self.retrieved_at = retrieved_at or datetime.now(UTC)
        self.http = None  # type: ignore[assignment]

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        for lab in self.labels:
            yield FetchedRecord(lab["set_id"], f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={lab['set_id']}",
                                json.dumps(lab, sort_keys=True).encode(), "application/json", self.retrieved_at,
                                title=f"{lab['openfda']['brand_name'][0]} prescribing information",
                                source_last_updated=lab.get("effective_time"))

    def close(self) -> None:
        pass


class FixtureDrugsFDAAdapter(DrugsAtFDAAdapter):
    def __init__(self, apps: list[dict[str, Any]], retrieved_at: datetime | None = None):
        self.apps = apps
        self.retrieved_at = retrieved_at or datetime.now(UTC)
        self.http = None  # type: ignore[assignment]

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        for a in self.apps:
            yield FetchedRecord(a["application_number"], f"fixture://drugsfda/{a['application_number']}",
                                json.dumps(a, sort_keys=True).encode(), "application/json", self.retrieved_at,
                                title=f"{a['application_number']} - {a['sponsor_name']}")

    def close(self) -> None:
        pass
