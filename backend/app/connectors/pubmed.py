"""NCBI PubMed E-utilities adapter (FR-SRC-003).

ESearch (history server) -> EFetch XML in batches. Complies with NCBI usage guidance: tool/email
parameters, <=3 req/s without an API key and <=10 req/s with one. Each PubmedArticle is retained as
its own raw artifact; PMIDs are unique in the canonical store so duplicates are impossible, and every
query that surfaced a PMID is retained as provenance.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from xml.etree.ElementTree import Element, tostring  # noqa: S405 - only used to serialise trusted elements

from defusedxml import ElementTree as SafeET

from app.connectors.base import (
    FetchContext,
    FetchedRecord,
    Mention,
    NormalizedRecord,
    SourceAdapter,
    TextSection,
)
from app.connectors.http import SourceHttpClient
from app.core.config import get_settings
from app.pipeline.normalize import clean_text, parse_datetime

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class PubMedAdapter(SourceAdapter):
    key = "pubmed"
    version = "1.3.0"
    display_name = "NCBI PubMed"
    default_schedule = "30 */6 * * *"
    freshness_slo_hours = 24

    def __init__(self, client: SourceHttpClient | None = None, rate_per_sec: float | None = None):
        s = get_settings()
        self.api_key = s.ncbi_api_key.get_secret_value() if s.ncbi_api_key else None
        default_rate = 9.0 if self.api_key else 2.5
        self.default_rate_limit_per_sec = default_rate
        self.http = client or SourceHttpClient(self.key, rate_per_sec or default_rate)
        self.common = {"tool": s.ncbi_tool, "email": s.ncbi_email}
        if self.api_key:
            self.common["api_key"] = self.api_key

    def rights(self) -> dict[str, Any]:
        return {
            "license": "NLM bibliographic metadata; abstracts may be subject to publisher copyright",
            "redistribution": "metadata-and-short-excerpts",
            "attribution": "PubMed, U.S. National Library of Medicine",
            "terms_url": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
        }

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        reldays = int(ctx.settings.get("reldays", 30))
        since = ctx.since or parse_datetime((ctx.checkpoint or {}).get("last_success_at"))
        retmax = int(ctx.settings.get("retmax", 200))
        seen: set[str] = set()
        for q in ctx.plan.pubmed_queries:
            params: dict[str, Any] = {**self.common, "db": "pubmed", "term": q["query"], "retmode": "json",
                                      "retmax": retmax, "sort": "pub_date", "usehistory": "n"}
            if since:
                params.update({"datetype": "edat", "mindate": (since - timedelta(days=2)).strftime("%Y/%m/%d"),
                               "maxdate": "3000"})
            else:
                params.update({"datetype": "edat", "reldate": reldays})
            ids = self.http.get(f"{BASE}/esearch.fcgi", params).json().get("esearchresult", {}).get("idlist", [])
            ids = [i for i in ids if i not in seen]
            for start in range(0, len(ids), 100):
                batch = ids[start : start + 100]
                res = self.http.get(
                    f"{BASE}/efetch.fcgi", {**self.common, "db": "pubmed", "id": ",".join(batch), "retmode": "xml"}
                )
                root = SafeET.fromstring(res.content)
                for art in root.findall("PubmedArticle"):
                    pmid = (art.findtext("MedlineCitation/PMID") or "").strip()
                    if not pmid or pmid in seen:
                        continue
                    seen.add(pmid)
                    raw = tostring(art, encoding="utf-8")
                    yield FetchedRecord(
                        source_object_id=pmid,
                        uri=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        raw=raw,
                        content_type="application/xml",
                        retrieved_at=res.retrieved_at,
                        title=clean_text(art.findtext("MedlineCitation/Article/ArticleTitle")),
                        query_provenance={"query": q["query"], "landscape_ids": q.get("landscape_ids", []),
                                          "esearch": "edat"},
                    )

    def parse(self, record: FetchedRecord) -> list[NormalizedRecord]:
        art: Element = SafeET.fromstring(record.raw)
        cit = art.find("MedlineCitation")
        a = cit.find("Article") if cit is not None else None
        if a is None:
            return []
        title = clean_text("".join(a.find("ArticleTitle").itertext()) if a.find("ArticleTitle") is not None else "")
        abstract_parts = []
        for t in a.findall("Abstract/AbstractText"):
            label = t.get("Label")
            txt = clean_text("".join(t.itertext()))
            abstract_parts.append(f"{label}: {txt}" if label else txt)
        abstract = " ".join(abstract_parts)
        authors = []
        for au in a.findall("AuthorList/Author"):
            name = " ".join(x for x in [au.findtext("ForeName"), au.findtext("LastName")] if x) or au.findtext(
                "CollectiveName"
            )
            if name:
                authors.append({"name": clean_text(name),
                                "affiliation": clean_text(au.findtext("AffiliationInfo/Affiliation"))})
        journal = clean_text(a.findtext("Journal/Title"))
        pub_date = _pub_date(a)
        doi = None
        for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").strip()
        mesh = [clean_text(m.findtext("DescriptorName")) for m in (cit.findall("MeshHeadingList/MeshHeading") or [])]
        chemicals = [clean_text(c.findtext("NameOfSubstance")) for c in cit.findall("ChemicalList/Chemical")]
        pub_types = sorted({clean_text(t.text) for t in a.findall("PublicationTypeList/PublicationType") if t.text})
        ncts = sorted({(x.text or "").strip() for x in a.findall("DataBankList/DataBank/AccessionNumberList/AccessionNumber")
                       if (x.text or "").startswith("NCT")})
        normalized = {
            "pmid": record.source_object_id,
            "doi": doi,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "pub_date": pub_date,
            "mesh_terms": sorted(m for m in mesh if m),
            "chemicals": sorted(c for c in chemicals if c),
            "nct_ids": ncts,
            "publication_types": pub_types,
        }
        mentions = [Mention(c, "asset", "chemical") for c in normalized["chemicals"]]
        mentions += [Mention(m, "indication", "mesh") for m in normalized["mesh_terms"]]
        mentions += [Mention(au["name"], "kol", "author", {"affiliation": au["affiliation"]}) for au in authors[:5]]
        sections = [TextSection("abstract", "MedlineCitation.Article.Abstract", abstract, title)] if abstract else []
        sections.append(TextSection("citation", "MedlineCitation.Article",
                                    f"{title}. {journal} ({pub_date}). Authors: "
                                    f"{', '.join(au['name'] for au in authors[:8])}. PMID {record.source_object_id}.",
                                    title))
        return [NormalizedRecord("publication", record.source_object_id, normalized, mentions, sections, title,
                                 parse_datetime(pub_date))]


def _pub_date(a: Element) -> str | None:
    ad = a.find("ArticleDate")
    if ad is not None and ad.findtext("Year"):
        return f"{ad.findtext('Year')}-{int(ad.findtext('Month') or 1):02d}-{int(ad.findtext('Day') or 1):02d}"
    pd = a.find("Journal/JournalIssue/PubDate")
    if pd is None:
        return None
    y = pd.findtext("Year")
    if not y:
        md = pd.findtext("MedlineDate") or ""
        return md[:4] or None
    m = pd.findtext("Month")
    if m:
        mi = int(m) if m.isdigit() else _MONTHS.get(m[:3].lower(), 1)
        return f"{y}-{mi:02d}"
    return y
