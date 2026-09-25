"""openFDA adapters: Drugs@FDA (approvals) and Structured Product Labeling (FR-SRC-004).

openFDA explicitly states its data should not be relied on for medical decisions and may lag
official sources; that disclaimer is retained in the rights metadata of every artifact and surfaced
with FDA-derived facts.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
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
from app.core.config import get_settings
from app.pipeline.normalize import clean_text, normalize_partial_date, parse_datetime

BASE = "https://api.fda.gov/drug"
OPENFDA_DISCLAIMER = (
    "openFDA data is provided for informational purposes; do not rely on it to make decisions regarding "
    "medical care. Data may be incomplete or lag official FDA publications. See https://open.fda.gov/terms/."
)
LABEL_SECTIONS = [
    "boxed_warning",
    "indications_and_usage",
    "dosage_and_administration",
    "dosage_forms_and_strengths",
    "contraindications",
    "warnings_and_cautions",
    "adverse_reactions",
    "clinical_studies",
]


def _fda_date(v: str | None) -> str | None:
    if v and len(v) == 8 and v.isdigit():
        return f"{v[:4]}-{v[4:6]}-{v[6:]}"
    return normalize_partial_date(v)


def _search_clause(product: str) -> str:
    p = product.replace('"', "")
    return f'(openfda.brand_name:"{p}"+openfda.generic_name:"{p}"+openfda.substance_name:"{p}")'


class _OpenFDABase(SourceAdapter):
    default_rate_limit_per_sec = 3.0  # openFDA: 240 req/min with key; 40 req/min/IP without
    freshness_slo_hours = 48
    default_schedule = "0 5 * * *"

    def __init__(self, client: SourceHttpClient | None = None, rate_per_sec: float | None = None):
        s = get_settings()
        self.api_key = s.openfda_api_key.get_secret_value() if s.openfda_api_key else None
        rate = rate_per_sec or (self.default_rate_limit_per_sec if self.api_key else 0.6)
        self.http = client or SourceHttpClient(self.key, rate)

    def rights(self) -> dict[str, Any]:
        return {
            "license": "CC0 / public domain (U.S. Government work)",
            "redistribution": "allowed",
            "attribution": "U.S. Food and Drug Administration via openFDA",
            "disclaimer": OPENFDA_DISCLAIMER,
            "terms_url": "https://open.fda.gov/terms/",
        }

    def _params(self, search: str, limit: int) -> dict[str, Any]:
        p: dict[str, Any] = {"search": search, "limit": limit}
        if self.api_key:
            p["api_key"] = self.api_key
        return p


class DrugsAtFDAAdapter(_OpenFDABase):
    key = "openfda_drugsfda"
    version = "1.1.0"
    display_name = "FDA Drugs@FDA (openFDA)"

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        for product in sorted(ctx.plan.fda_products):
            res = self.http.get(f"{BASE}/drugsfda.json", self._params(_search_clause(product), 25), allow_404=True)
            if res.status == 404:
                continue
            for app_rec in res.json().get("results", []):
                appno = app_rec.get("application_number")
                if not appno:
                    continue
                raw = json.dumps(app_rec, sort_keys=True).encode()
                yield FetchedRecord(
                    source_object_id=appno,
                    uri=f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={appno[-6:]}",
                    raw=raw,
                    content_type="application/json",
                    retrieved_at=res.retrieved_at,
                    title=f"{appno} - {app_rec.get('sponsor_name')}",
                    query_provenance={"product": product, "api_url": res.url, "dataset": "drug/drugsfda"},
                )

    def parse(self, record: FetchedRecord) -> list[NormalizedRecord]:
        d = json.loads(record.raw)
        ofda = d.get("openfda", {}) or {}
        subs = [
            {
                "submission_type": s.get("submission_type"),
                "submission_number": s.get("submission_number"),
                "status": s.get("submission_status"),
                "status_date": _fda_date(s.get("submission_status_date")),
                "class_code": s.get("submission_class_code"),
                "class_description": s.get("submission_class_code_description"),
                "review_priority": s.get("review_priority"),
            }
            for s in d.get("submissions", [])
        ]
        subs.sort(key=lambda s: (s["status_date"] or "", s["submission_type"] or "", s["submission_number"] or ""))
        products = sorted(
            {
                f"{clean_text(p.get('brand_name'))} ({clean_text(p.get('dosage_form'))}, {clean_text(p.get('route'))})"
                for p in d.get("products", [])
            }
        )
        brand = sorted({clean_text(b) for b in ofda.get("brand_name", [])})
        generic = sorted({clean_text(g) for g in ofda.get("generic_name", [])})
        normalized = {
            "application_number": d.get("application_number"),
            "sponsor": clean_text(d.get("sponsor_name")),
            "brand_names": brand,
            "generic_names": generic,
            "products": products,
            "submissions": subs,
            "approved_submissions": [
                f"{s['submission_type']}-{s['submission_number']}" for s in subs if (s["status"] or "").upper() == "AP"
            ],
        }
        mentions = [Mention(normalized["sponsor"], "company", "sponsor")] if normalized["sponsor"] else []
        mentions += [Mention(n, "asset", "product", {"application_number": d.get("application_number")})
                     for n in brand + generic]
        text = (
            f"FDA application {normalized['application_number']} ({', '.join(brand) or ', '.join(generic)}), sponsor "
            f"{normalized['sponsor']}. Submissions: "
            + "; ".join(
                f"{s['submission_type']} {s['submission_number']} status {s['status']} on {s['status_date']}"
                f" ({s['class_description'] or s['class_code']})"
                for s in subs
            )
        )
        return [NormalizedRecord("drug_application", record.source_object_id, normalized, mentions,
                                 [TextSection("submissions", "drugsfda.submissions", text, record.title)],
                                 record.title)]


class DrugLabelAdapter(_OpenFDABase):
    key = "openfda_label"
    version = "1.1.0"
    display_name = "FDA Drug Labeling (openFDA SPL)"

    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        for product in sorted(ctx.plan.fda_products):
            res = self.http.get(f"{BASE}/label.json", self._params(_search_clause(product), 10), allow_404=True)
            if res.status == 404:
                continue
            for lab in res.json().get("results", []):
                set_id = lab.get("set_id")
                if not set_id:
                    continue
                raw = json.dumps(lab, sort_keys=True).encode()
                brand = ", ".join((lab.get("openfda") or {}).get("brand_name", [])) or product
                yield FetchedRecord(
                    source_object_id=set_id,
                    uri=f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}",
                    raw=raw,
                    content_type="application/json",
                    retrieved_at=res.retrieved_at,
                    title=f"{brand} prescribing information",
                    source_last_updated=_fda_date(lab.get("effective_time")),
                    query_provenance={"product": product, "api_url": res.url, "dataset": "drug/label"},
                )

    def parse(self, record: FetchedRecord) -> list[NormalizedRecord]:
        lab = json.loads(record.raw)
        ofda = lab.get("openfda", {}) or {}
        sections = {s: clean_text(" ".join(lab.get(s, []))) for s in LABEL_SECTIONS if lab.get(s)}
        normalized = {
            "set_id": lab.get("set_id"),
            "version": lab.get("version"),
            "effective_date": _fda_date(lab.get("effective_time")),
            "brand_names": sorted(ofda.get("brand_name", [])),
            "generic_names": sorted(ofda.get("generic_name", [])),
            "manufacturer": sorted(ofda.get("manufacturer_name", [])),
            "application_numbers": sorted(ofda.get("application_number", [])),
            "sections": sections,
        }
        mentions = [Mention(n, "asset", "product") for n in normalized["brand_names"] + normalized["generic_names"]]
        mentions += [Mention(m, "company", "manufacturer") for m in normalized["manufacturer"]]
        text_sections = [
            TextSection(name, f"label.{name}", body, record.title) for name, body in sections.items() if body
        ]
        return [NormalizedRecord("label", record.source_object_id, normalized, mentions, text_sections, record.title,
                                 parse_datetime(normalized["effective_date"]))]
