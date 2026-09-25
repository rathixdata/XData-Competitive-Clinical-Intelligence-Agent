"""ClinicalTrials.gov API v2 adapter (FR-SRC-002).

Uses the official structured API (https://clinicaltrials.gov/data-api/api), never page scraping.
Monitored NCT IDs are fetched individually; discovery queries (condition x intervention) find new
entrants. Incremental runs filter on LastUpdatePostDate.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from app.connectors.base import (
    FetchContext,
    FetchedRecord,
    Mention,
    NormalizedRecord,
    SourceAdapter,
    TextSection,
)
from app.connectors.http import SourceHttpClient
from app.pipeline.normalize import (
    clean_text,
    normalize_partial_date,
    normalize_phase,
    normalize_status,
    parse_datetime,
    to_int,
)

BASE = "https://clinicaltrials.gov/api/v2"


class ClinicalTrialsGovAdapter(SourceAdapter):
    key = "ctgov"
    version = "2.1.0"
    display_name = "ClinicalTrials.gov"
    default_rate_limit_per_sec = 0.8  # stay well under the documented ~50 req/min guidance
    default_schedule = "15 */2 * * *"
    freshness_slo_hours = 12

    def __init__(self, client: SourceHttpClient | None = None, rate_per_sec: float | None = None):
        self.http = client or SourceHttpClient(self.key, rate_per_sec or self.default_rate_limit_per_sec)

    def rights(self) -> dict[str, Any]:
        return {
            "license": "public-domain (U.S. NLM)",
            "redistribution": "allowed-with-attribution",
            "attribution": "ClinicalTrials.gov, U.S. National Library of Medicine",
            "terms_url": "https://clinicaltrials.gov/about-site/terms-conditions",
        }

    # ---------------------------------------------------------------- fetch
    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        seen: set[str] = set()
        for nct in sorted(ctx.plan.nct_ids):
            res = self.http.get(f"{BASE}/studies/{nct}", {"format": "json"}, allow_404=True)
            if res.status == 404:
                continue
            seen.add(nct)
            yield self._record(nct, res.content, res.url, res.retrieved_at, {"mode": "monitored", "nct_id": nct})

        page_size = int(ctx.settings.get("page_size", 100))
        max_pages = int(ctx.settings.get("max_pages_per_query", 5))
        since = ctx.since or (parse_datetime(ctx.checkpoint.get("last_success_at")) if ctx.checkpoint else None)
        for q in ctx.plan.trial_queries:
            params: dict[str, Any] = {"format": "json", "pageSize": page_size, "countTotal": "false"}
            if q.get("cond"):
                params["query.cond"] = q["cond"]
            if q.get("intr"):
                params["query.intr"] = q["intr"]
            if q.get("term"):
                params["query.term"] = q["term"]
            if since:
                lo = (since - timedelta(days=2)).date().isoformat()
                params["filter.advanced"] = f"AREA[LastUpdatePostDate]RANGE[{lo},MAX]"
            token = None
            for _ in range(max_pages):
                if token:
                    params["pageToken"] = token
                res = self.http.get(f"{BASE}/studies", params)
                body = res.json()
                for study in body.get("studies", []):
                    nct = study.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
                    if not nct or nct in seen:
                        continue
                    seen.add(nct)
                    raw = json.dumps(study, sort_keys=True).encode()
                    yield self._record(
                        nct, raw, f"{BASE}/studies/{nct}", res.retrieved_at, {"mode": "discovery", "query": q}
                    )
                token = body.get("nextPageToken")
                if not token:
                    break

    def _record(self, nct: str, raw: bytes, url: str, retrieved_at, prov: dict) -> FetchedRecord:  # type: ignore[no-untyped-def]
        data = json.loads(raw)
        ps = data.get("protocolSection", {})
        status = ps.get("statusModule", {})
        return FetchedRecord(
            source_object_id=nct,
            uri=f"https://clinicaltrials.gov/study/{nct}",
            raw=raw,
            content_type="application/json",
            retrieved_at=retrieved_at,
            title=ps.get("identificationModule", {}).get("briefTitle"),
            source_last_updated=(status.get("lastUpdatePostDateStruct") or {}).get("date"),
            query_provenance={**prov, "api_url": url},
        )

    # ---------------------------------------------------------------- parse
    def parse(self, record: FetchedRecord) -> list[NormalizedRecord]:
        data = json.loads(record.raw)
        ps = data.get("protocolSection", {})
        ident = ps.get("identificationModule", {})
        status = ps.get("statusModule", {})
        sponsor = ps.get("sponsorCollaboratorsModule", {})
        design = ps.get("designModule", {})
        arms_mod = ps.get("armsInterventionsModule", {})
        outcomes = ps.get("outcomesModule", {})
        elig = ps.get("eligibilityModule", {})
        conds = ps.get("conditionsModule", {})
        locs = ps.get("contactsLocationsModule", {})

        def outcome_list(items: list[dict] | None) -> list[dict[str, str]]:
            return [
                {
                    "measure": clean_text(o.get("measure")),
                    "time_frame": clean_text(o.get("timeFrame")),
                    "description": clean_text(o.get("description")),
                }
                for o in (items or [])
            ]

        interventions = [
            {
                "type": i.get("type"),
                "name": clean_text(i.get("name")),
                "other_names": sorted({clean_text(n) for n in i.get("otherNames", []) if n}),
            }
            for i in arms_mod.get("interventions", [])
        ]
        arms = [
            {
                "label": clean_text(a.get("label")),
                "type": a.get("type"),
                "description": clean_text(a.get("description")),
                "interventions": sorted(clean_text(x) for x in a.get("interventionNames", [])),
            }
            for a in arms_mod.get("armGroups", [])
        ]
        locations = [
            {
                "facility": clean_text(loc.get("facility")),
                "city": clean_text(loc.get("city")),
                "country": clean_text(loc.get("country")),
                "status": loc.get("status"),
            }
            for loc in locs.get("locations", [])
        ]
        enrollment = design.get("enrollmentInfo", {}) or {}
        lead = (sponsor.get("leadSponsor") or {}).get("name")

        normalized: dict[str, Any] = {
            "nct_id": ident.get("nctId"),
            "brief_title": clean_text(ident.get("briefTitle")),
            "official_title": clean_text(ident.get("officialTitle")),
            "acronym": ident.get("acronym"),
            "sponsor": clean_text(lead) if lead else None,
            "collaborators": sorted(clean_text(c.get("name")) for c in sponsor.get("collaborators", [])),
            "status": normalize_status(status.get("overallStatus")),
            "why_stopped": clean_text(status.get("whyStopped")) or None,
            "phase": normalize_phase(design.get("phases")),
            "study_type": design.get("studyType"),
            "enrollment": to_int(enrollment.get("count")),
            "enrollment_type": enrollment.get("type"),
            "start_date": normalize_partial_date((status.get("startDateStruct") or {}).get("date")),
            "primary_completion_date": normalize_partial_date(
                (status.get("primaryCompletionDateStruct") or {}).get("date")
            ),
            "primary_completion_date_type": (status.get("primaryCompletionDateStruct") or {}).get("type"),
            "completion_date": normalize_partial_date((status.get("completionDateStruct") or {}).get("date")),
            "conditions": sorted(clean_text(c) for c in conds.get("conditions", [])),
            "keywords": sorted(clean_text(k) for k in conds.get("keywords", [])),
            "interventions": sorted(interventions, key=lambda i: i["name"].lower()),
            "arms": sorted(arms, key=lambda a: a["label"].lower()),
            "primary_endpoints": outcome_list(outcomes.get("primaryOutcomes")),
            "secondary_endpoints": outcome_list(outcomes.get("secondaryOutcomes")),
            "eligibility_criteria": clean_text(elig.get("eligibilityCriteria")),
            "minimum_age": elig.get("minimumAge"),
            "sex": elig.get("sex"),
            "locations": sorted(locations, key=lambda x: (x["country"], x["city"], x["facility"])),
            "countries": sorted({loc["country"] for loc in locations if loc["country"]}),
            "last_update_posted": normalize_partial_date((status.get("lastUpdatePostDateStruct") or {}).get("date")),
        }

        mentions: list[Mention] = []
        if lead:
            mentions.append(Mention(lead, "company", "sponsor"))
        for c in sponsor.get("collaborators", []):
            if c.get("name"):
                mentions.append(Mention(c["name"], "company", "collaborator"))
        for i in interventions:
            if i["type"] in ("DRUG", "BIOLOGICAL", "GENETIC", "COMBINATION_PRODUCT", None):
                if i["name"].lower() in {"placebo", "standard of care", "best supportive care"}:
                    continue
                mentions.append(Mention(i["name"], "asset", "intervention", {"other_names": i["other_names"]}))
        for c in normalized["conditions"]:
            mentions.append(Mention(c, "indication", "condition"))
        for o in normalized["primary_endpoints"]:
            mentions.append(Mention(o["measure"], "endpoint", "primary_endpoint"))

        title = normalized["brief_title"]
        sections = [
            TextSection("summary", "protocolSection.descriptionModule.briefSummary",
                        clean_text(ps.get("descriptionModule", {}).get("briefSummary")), title),
            TextSection("design", "protocolSection.designModule", _design_text(normalized), title),
            TextSection("primary_outcomes", "protocolSection.outcomesModule.primaryOutcomes",
                        _outcomes_text("Primary endpoint", normalized["primary_endpoints"]), title),
            TextSection("secondary_outcomes", "protocolSection.outcomesModule.secondaryOutcomes",
                        _outcomes_text("Secondary endpoint", normalized["secondary_endpoints"]), title),
            TextSection("arms", "protocolSection.armsInterventionsModule",
                        "; ".join(f"Arm {a['label']} ({a['type']}): {a['description']}" for a in arms), title),
            TextSection("eligibility", "protocolSection.eligibilityModule.eligibilityCriteria",
                        normalized["eligibility_criteria"], title),
        ]
        return [
            NormalizedRecord(
                object_type="trial",
                source_object_id=normalized["nct_id"] or record.source_object_id,
                normalized=normalized,
                mentions=mentions,
                sections=[s for s in sections if s.text],
                title=title,
                published_at=parse_datetime(normalized["last_update_posted"]),
            )
        ]


def _design_text(n: dict[str, Any]) -> str:
    return (
        f"{n['nct_id']} ({n.get('acronym') or n['brief_title']}) sponsored by {n.get('sponsor')}. "
        f"Status: {n.get('status')}. Phase: {n.get('phase')}. Enrollment: {n.get('enrollment')} "
        f"({n.get('enrollment_type')}). Start: {n.get('start_date')}. Primary completion: "
        f"{n.get('primary_completion_date')} ({n.get('primary_completion_date_type')}). Study completion: "
        f"{n.get('completion_date')}. Conditions: {', '.join(n.get('conditions') or [])}. Interventions: "
        f"{', '.join(i['name'] for i in n.get('interventions') or [])}. Countries: {', '.join(n.get('countries') or [])}."
    )


def _outcomes_text(label: str, outcomes: list[dict[str, str]]) -> str:
    return " ".join(f"{label}: {o['measure']} (time frame: {o['time_frame']}). {o['description']}" for o in outcomes)
