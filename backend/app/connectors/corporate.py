"""Corporate disclosures (FR-SRC-005) and conference feeds (FR-SRC-006).

* ``SecEdgarAdapter`` - SEC EDGAR submissions API for monitored CIKs (8-K, 10-K, 10-Q, 6-K, 20-F).
  SEC fair-access policy: declared User-Agent, <=10 req/s.
* ``FeedAdapter`` - permitted RSS/Atom/JSON feeds (investor-relations press releases, public congress
  abstract feeds). Each feed carries a rights policy; feeds whose policy does not permit ingestion
  are skipped and logged (FR-SRC-006 acceptance: rights/access policy is enforced per source).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from html import unescape
from typing import Any

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
from app.core.logging import get_logger
from app.pipeline.normalize import clean_text, parse_datetime

log = get_logger(__name__)

MATERIAL_FORMS = {"8-K", "10-K", "10-Q", "6-K", "20-F", "S-1", "425", "8-K/A"}
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def html_to_text(html: str) -> str:
    return clean_text(unescape(_TAG.sub(" ", _SCRIPT.sub(" ", html))))


class SecEdgarAdapter(SourceAdapter):
    key = "sec_edgar"
    version = "1.0.2"
    display_name = "SEC EDGAR"
    default_rate_limit_per_sec = 5.0
    default_schedule = "10 * * * *"
    freshness_slo_hours = 6

    def __init__(self, client: SourceHttpClient | None = None, rate_per_sec: float | None = None):
        ua = get_settings().sec_user_agent
        self.http = client or SourceHttpClient(self.key, rate_per_sec or self.default_rate_limit_per_sec,
                                               headers={"User-Agent": ua})

    def rights(self) -> dict[str, Any]:
        return {"license": "public (U.S. SEC filings)", "redistribution": "allowed", "attribution": "SEC EDGAR",
                "terms_url": "https://www.sec.gov/os/accessing-edgar-data"}

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        max_filings = int(ctx.settings.get("max_filings_per_company", 20))
        fetch_documents = bool(ctx.settings.get("fetch_primary_documents", True))
        for cik in sorted(ctx.plan.sec_ciks):
            cik10 = cik.zfill(10)
            res = self.http.get(f"https://data.sec.gov/submissions/CIK{cik10}.json", allow_404=True)
            if res.status == 404:
                continue
            body = res.json()
            recent = body.get("filings", {}).get("recent", {})
            n = len(recent.get("accessionNumber", []))
            count = 0
            for i in range(n):
                form = recent["form"][i]
                if form not in MATERIAL_FORMS:
                    continue
                acc = recent["accessionNumber"][i]
                doc = recent.get("primaryDocument", [""] * n)[i]
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
                filing = {
                    "cik": cik10, "company": body.get("name"), "form": form, "accession": acc,
                    "filing_date": recent["filingDate"][i], "report_date": recent.get("reportDate", [""] * n)[i],
                    "description": recent.get("primaryDocDescription", [""] * n)[i],
                    "items": recent.get("items", [""] * n)[i], "url": url, "tickers": body.get("tickers", []),
                }
                if fetch_documents and form in {"8-K", "6-K", "8-K/A"}:
                    doc_res = self.http.get(url, allow_404=True)
                    if doc_res.status != 404:
                        filing["text"] = html_to_text(doc_res.content.decode("utf-8", "replace"))[:200_000]
                raw = json.dumps(filing, sort_keys=True).encode()
                yield FetchedRecord(acc, url, raw, "application/json", res.retrieved_at,
                                    title=f"{body.get('name')} {form} ({filing['filing_date']})",
                                    published_at=parse_datetime(filing["filing_date"]),
                                    query_provenance={"cik": cik10})
                count += 1
                if count >= max_filings:
                    break

    def parse(self, record: FetchedRecord) -> list[NormalizedRecord]:
        f = json.loads(record.raw)
        text = f.get("text") or ""
        normalized = {k: f.get(k) for k in ("cik", "company", "form", "accession", "filing_date", "report_date",
                                            "description", "items", "url")}
        normalized["title"] = record.title
        sections = [TextSection("filing", "edgar.primaryDocument", text or f"{record.title}: {f.get('description')}",
                                record.title)]
        return [NormalizedRecord("disclosure", record.source_object_id, normalized,
                                 [Mention(f.get("company") or "", "company", "filer", {"cik": f.get("cik")})],
                                 sections, record.title, record.published_at)]


class FeedAdapter(SourceAdapter):
    """Generic permitted feed adapter; ``kind`` is 'corporate' or 'conference'."""

    version = "1.0.0"
    default_rate_limit_per_sec = 1.0
    default_schedule = "45 */3 * * *"

    ALLOWED_POLICIES = {"public", "licensed", "permitted"}

    def __init__(self, kind: str, client: SourceHttpClient | None = None, rate_per_sec: float | None = None):
        self.kind = kind
        self.key = f"{kind}_feed"
        self.display_name = "Corporate IR feeds" if kind == "corporate" else "Conference abstract feeds"
        self.http = client or SourceHttpClient(self.key, rate_per_sec or self.default_rate_limit_per_sec)

    def rights(self) -> dict[str, Any]:
        return {"license": "per-feed policy", "redistribution": "excerpt-only", "attribution": self.display_name}

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        for feed in ctx.plan.feeds:
            if feed.get("kind", "corporate") != self.kind:
                continue
            policy = (feed.get("rights") or {}).get("policy", "unknown")
            if policy not in self.ALLOWED_POLICIES or feed.get("allowed") is False:
                log.warning("feed_skipped_rights_policy", feed=feed.get("url"), policy=policy)
                continue
            res = self.http.get(feed["url"])
            for item in _parse_feed(res.content, res.content_type):
                raw = json.dumps({**item, "feed": feed["url"], "company": feed.get("company"),
                                  "conference": feed.get("conference"), "rights": feed.get("rights")},
                                 sort_keys=True).encode()
                yield FetchedRecord(item["id"], item.get("link") or feed["url"], raw, "application/json",
                                    res.retrieved_at, title=item.get("title"),
                                    published_at=parse_datetime(item.get("published")),
                                    query_provenance={"feed": feed["url"], "rights": feed.get("rights")})

    def parse(self, record: FetchedRecord) -> list[NormalizedRecord]:
        it = json.loads(record.raw)
        object_type = "disclosure" if self.kind == "corporate" else "conference_abstract"
        normalized = {"title": clean_text(it.get("title")), "summary": clean_text(it.get("summary")),
                      "link": it.get("link"), "published": it.get("published"), "feed": it.get("feed"),
                      "company": it.get("company"), "conference": it.get("conference"),
                      "form": "PRESS_RELEASE" if self.kind == "corporate" else "ABSTRACT"}
        mentions = []
        if it.get("company"):
            mentions.append(Mention(it["company"], "company", "issuer"))
        if it.get("conference"):
            mentions.append(Mention(it["conference"], "conference", "venue"))
        return [NormalizedRecord(object_type, record.source_object_id, normalized, mentions,
                                 [TextSection("body", "feed.item", normalized["summary"] or normalized["title"],
                                              normalized["title"])],
                                 normalized["title"], record.published_at)]


def _parse_feed(content: bytes, content_type: str) -> list[dict[str, Any]]:
    if "json" in content_type:
        data = json.loads(content)
        items = data.get("items", data if isinstance(data, list) else [])
        return [{"id": str(i.get("id") or i.get("url")), "title": i.get("title"), "link": i.get("url") or i.get("link"),
                 "summary": html_to_text(i.get("content_html") or i.get("summary") or i.get("content_text") or ""),
                 "published": i.get("date_published") or i.get("published")} for i in items]
    root = SafeET.fromstring(content)
    out = []
    atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter("item"):
        out.append({"id": (it.findtext("guid") or it.findtext("link") or "").strip(), "title": it.findtext("title"),
                    "link": it.findtext("link"), "summary": html_to_text(it.findtext("description") or ""),
                    "published": it.findtext("pubDate")})
    for it in root.iter(f"{atom}entry"):
        link = it.find(f"{atom}link")
        out.append({"id": (it.findtext(f"{atom}id") or "").strip(), "title": it.findtext(f"{atom}title"),
                    "link": link.get("href") if link is not None else None,
                    "summary": html_to_text(it.findtext(f"{atom}summary") or it.findtext(f"{atom}content") or ""),
                    "published": it.findtext(f"{atom}published") or it.findtext(f"{atom}updated")})
    return [o for o in out if o["id"]]
