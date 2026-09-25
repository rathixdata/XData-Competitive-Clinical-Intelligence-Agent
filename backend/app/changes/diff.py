"""Structured and document-level diffing with noise suppression (FR-CHG-002/003/005/006)."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.changes.taxonomy import HALTED_STATUSES, IGNORED_TRIAL_FIELDS, TRIAL_FIELD_TYPES, ChangeType
from app.core.crypto import stable_hash
from app.pipeline.normalize import (
    comparable_text,
    months_between,
    normalize_partial_date,
    partial_date_to_date,
)


@dataclass
class FieldChange:
    field: str
    change_type: str
    old: Any
    new: Any
    tags: list[str] = field(default_factory=list)
    magnitude: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)
    suppressed: bool = False
    suppression_reason: str | None = None


def _comparable(value: Any) -> Any:
    """Canonical form for equivalence: ignores case, whitespace, punctuation, ordering."""
    if isinstance(value, dict):
        return tuple(sorted((k, _comparable(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(sorted((_comparable(v) for v in value), key=repr))
    if isinstance(value, str):
        return comparable_text(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def fingerprint(object_id: Any, field_name: str, old: Any, new: Any, from_snapshot_id: Any) -> str:
    return stable_hash(["chg", str(object_id), field_name, _comparable(old), _comparable(new), str(from_snapshot_id)])


def sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;:!?])\s+|\s+(?=\d+\.\s)|\s+(?=[-*•]\s)", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def document_diff(old: str, new: str, *, context: int = 0) -> dict[str, Any]:
    """Passage-level diff for labels, eligibility text, disclosures (FR-CHG-003)."""
    a, b = sentence_split(old), sentence_split(new)
    ca, cb = [comparable_text(x) for x in a], [comparable_text(x) for x in b]
    sm = difflib.SequenceMatcher(a=ca, b=cb, autojunk=False)
    passages = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        passages.append({"op": op, "old": " ".join(a[i1:i2]), "new": " ".join(b[j1:j2]),
                         "old_range": [i1, i2], "new_range": [j1, j2]})
    ratio = sm.ratio() if (ca or cb) else 1.0
    added_words = sum(len(p["new"].split()) for p in passages)
    removed_words = sum(len(p["old"].split()) for p in passages)
    return {"passages": passages, "similarity": round(ratio, 4), "added_words": added_words,
            "removed_words": removed_words}


def _item_key(x: Any) -> str:
    if isinstance(x, str):
        return comparable_text(x)
    return comparable_text(x.get("name") or x.get("label") or x.get("facility") or str(x))


def _list_delta(old: list, new: list, key) -> tuple[list, list]:  # type: ignore[no-untyped-def]
    ok = {key(x): x for x in old or []}
    nk = {key(x): x for x in new or []}
    added = [nk[k] for k in nk.keys() - ok.keys()]
    removed = [ok[k] for k in ok.keys() - nk.keys()]
    return added, removed


def diff_trial(old: dict[str, Any], new: dict[str, Any], *, monitored_fields: set[str] | None = None) -> list[FieldChange]:
    changes: list[FieldChange] = []
    fields = set(TRIAL_FIELD_TYPES) if monitored_fields is None else monitored_fields & set(TRIAL_FIELD_TYPES)
    for f in sorted(fields - IGNORED_TRIAL_FIELDS):
        ov, nv = old.get(f), new.get(f)
        if ov == nv:
            continue
        ctype = TRIAL_FIELD_TYPES[f]
        ch = FieldChange(f, ctype, ov, nv)
        is_date = f in ("start_date", "primary_completion_date", "completion_date")
        if is_date and normalize_partial_date(ov) == normalize_partial_date(nv):
            ch.suppressed, ch.suppression_reason = True, "formatting_only"
            changes.append(ch)
            continue
        if _comparable(ov) == _comparable(nv):
            ch.suppressed = True
            ch.suppression_reason = "ordering_only" if isinstance(ov, list) else "formatting_only"
            changes.append(ch)
            continue

        if f == "status":
            if (ov or "").startswith("Not yet") and nv in ("Recruiting", "Enrolling by invitation"):
                ch.change_type = ChangeType.TRIAL_STARTED
            if nv in HALTED_STATUSES:
                ch.tags.append("TRIAL_HALTED")
                ch.magnitude["halted"] = True
                if new.get("why_stopped"):
                    ch.detail["why_stopped"] = new["why_stopped"]
            if nv == "Completed":
                ch.tags.append("TRIAL_COMPLETED")
        elif f == "enrollment":
            if isinstance(ov, int) and isinstance(nv, int) and ov:
                pct = round((nv - ov) / ov * 100, 1)
                ch.magnitude.update({"delta": nv - ov, "pct_change": pct})
                ch.tags.append("ENROLLMENT_INCREASE" if nv > ov else "ENROLLMENT_DECREASE")
        elif f in ("primary_endpoints", "secondary_endpoints"):
            added, removed = _list_delta(ov or [], nv or [], lambda o: comparable_text(o.get("measure")))
            tf_changed = []
            om = {comparable_text(o.get("measure")): o for o in ov or []}
            for o in nv or []:
                prev = om.get(comparable_text(o.get("measure")))
                if prev and comparable_text(prev.get("time_frame")) != comparable_text(o.get("time_frame")):
                    tf_changed.append({"measure": o["measure"], "old": prev.get("time_frame"), "new": o.get("time_frame")})
            ch.detail = {"added": [a["measure"] for a in added], "removed": [r["measure"] for r in removed],
                         "time_frame_changed": tf_changed}
            ch.magnitude["endpoint_level"] = "primary" if f == "primary_endpoints" else "secondary"
            if f == "secondary_endpoints":
                ch.tags.append("SECONDARY_ENDPOINT")
            if added and removed:
                ch.tags.append("ENDPOINT_REPLACED")
                ch.magnitude["replaced"] = True
            elif added:
                ch.tags.append("ENDPOINT_ADDED")
            elif removed:
                ch.tags.append("ENDPOINT_REMOVED")
            elif tf_changed:
                ch.tags.append("ENDPOINT_TIMEFRAME")
            else:
                # only descriptions changed in non-equivalent way
                ch.tags.append("ENDPOINT_DESCRIPTION")
        elif f in ("start_date", "primary_completion_date", "completion_date"):
            shift = months_between(ov, nv)
            ch.magnitude.update({"shift_months": shift, "date_field": f})
            if shift is not None:
                ch.tags.append("DELAY" if shift > 0 else "ACCELERATION")
            ch.tags.append(f.upper())
        elif f in ("eligibility_criteria",):
            dd = document_diff(ov or "", nv or "")
            ch.detail = dd
            ch.magnitude["similarity"] = dd["similarity"]
            if dd["similarity"] >= 0.995 and dd["added_words"] + dd["removed_words"] <= 2:
                ch.suppressed, ch.suppression_reason = True, "trivial_text_edit"
        elif f in ("countries", "locations", "conditions", "collaborators", "interventions", "arms"):
            added, removed = _list_delta(ov or [], nv or [], _item_key)
            ch.detail = {"added": added, "removed": removed}
            if f == "locations":
                ch.magnitude["sites_delta"] = len(nv or []) - len(ov or [])
                # Site-level churn is low-signal; country changes are captured separately.
                ch.tags.append("SITE_UPDATE")
        elif f == "phase":
            ch.tags.append("PHASE_TRANSITION")
        changes.append(ch)

    # Actualization of an anticipated date without a value change is informative but not a date move.
    if (old.get("primary_completion_date_type") != new.get("primary_completion_date_type")
            and old.get("primary_completion_date") == new.get("primary_completion_date")
            and new.get("primary_completion_date_type") == "ACTUAL"):
        changes.append(FieldChange("primary_completion_date_type", ChangeType.DATE_CHANGED,
                                   old.get("primary_completion_date_type"), "ACTUAL",
                                   tags=["DATE_ACTUALIZED"], magnitude={"shift_months": 0}))
    return changes


def diff_label(old: dict[str, Any], new: dict[str, Any]) -> list[FieldChange]:
    changes = []
    os_, ns = old.get("sections", {}), new.get("sections", {})
    for sec in sorted(set(os_) | set(ns)):
        a, b = os_.get(sec, ""), ns.get(sec, "")
        if comparable_text(a) == comparable_text(b):
            continue
        dd = document_diff(a, b)
        if not dd["passages"]:
            continue
        tags = [f"SECTION_{sec.upper()}"]
        if sec == "boxed_warning":
            tags.append("BOXED_WARNING")
        if sec == "indications_and_usage":
            tags.append("INDICATION_UPDATE")
        changes.append(FieldChange(f"sections.{sec}", ChangeType.LABEL_CHANGED,
                                   {"effective_date": old.get("effective_date")},
                                   {"effective_date": new.get("effective_date")}, tags=tags,
                                   magnitude={"similarity": dd["similarity"], "section": sec}, detail=dd))
    return changes


def diff_drug_application(old: dict[str, Any] | None, new: dict[str, Any], *, baseline_days: int = 60) -> list[FieldChange]:
    old_ap = set((old or {}).get("approved_submissions", []))
    changes = []
    cutoff = (datetime.now(UTC) - timedelta(days=baseline_days)).date()
    for s in new.get("submissions", []):
        sid = f"{s['submission_type']}-{s['submission_number']}"
        if (s.get("status") or "").upper() != "AP" or sid in old_ap:
            continue
        is_orig = (s.get("submission_type") or "").upper() == "ORIG"
        ctype = ChangeType.APPROVAL if is_orig else ChangeType.SUPPLEMENTAL_APPROVAL
        tags = []
        cls = (s.get("class_code") or "").upper()
        if cls in ("EFFICACY", "TYPE 6") or "efficacy" in (s.get("class_description") or "").lower():
            tags.append("NEW_INDICATION_OR_EFFICACY")
        if (s.get("review_priority") or "").upper() == "PRIORITY":
            tags.append("PRIORITY_REVIEW")
        ch = FieldChange(f"submissions.{sid}", ctype, None, s, tags=tags,
                         magnitude={"submission_class": cls, "orig": is_orig})
        d = partial_date_to_date(s.get("status_date"))
        if old is None and (d is None or d < cutoff):
            ch.suppressed, ch.suppression_reason = True, "baseline_historical"
        changes.append(ch)
    return changes


def first_observation(object_type: str, normalized: dict[str, Any], *, recent_days: int = 45) -> list[FieldChange]:
    """Changes emitted when an object is observed for the first time (baseline vs. genuinely new)."""
    today = datetime.now(UTC).date()

    def recent(d: date | None) -> bool:
        return d is not None and (today - d).days <= recent_days

    if object_type == "trial":
        start = partial_date_to_date(normalized.get("start_date"))
        registered_recent = recent(start) or (start is not None and start > today)
        ch = FieldChange("trial", ChangeType.TRIAL_REGISTERED, None,
                         {k: normalized.get(k) for k in ("nct_id", "status", "phase", "enrollment", "sponsor")},
                         tags=["NEW_ENTRANT_CANDIDATE"])
        if not registered_recent:
            ch.suppressed, ch.suppression_reason = True, "baseline_historical"
        return [ch]
    if object_type == "publication":
        d = partial_date_to_date(normalized.get("pub_date"))
        types = {t.lower() for t in normalized.get("publication_types", [])}
        tags = []
        if types & {"review", "systematic review", "meta-analysis"}:
            tags.append("REVIEW")
        if any("clinical trial" in t for t in types) or normalized.get("nct_ids"):
            tags.append("CLINICAL_TRIAL")
        ch = FieldChange("publication", ChangeType.NEW_PUBLICATION, None,
                         {"pmid": normalized.get("pmid"), "title": normalized.get("title")}, tags=tags)
        if d is not None and not recent(d) and (today - d).days > 180:
            ch.suppressed, ch.suppression_reason = True, "baseline_historical"
        return [ch]
    if object_type == "disclosure":
        d = partial_date_to_date(normalize_partial_date(normalized.get("filing_date") or normalized.get("published")))
        ch = FieldChange("disclosure", ChangeType.CORPORATE_EVENT, None,
                         {"form": normalized.get("form"), "title": normalized.get("title"), "url": normalized.get("url")})
        if d is not None and not recent(d):
            ch.suppressed, ch.suppression_reason = True, "baseline_historical"
        return [ch]
    if object_type == "conference_abstract":
        return [FieldChange("abstract", ChangeType.CONFERENCE_ABSTRACT, None, {"title": normalized.get("title")})]
    if object_type == "drug_application":
        return diff_drug_application(None, normalized)
    if object_type == "label":
        return []  # first label version is baseline; later versions are diffed
    return []


def diff_objects(object_type: str, old: dict[str, Any] | None, new: dict[str, Any], **kw: Any) -> list[FieldChange]:
    if old is None:
        return first_observation(object_type, new)
    if object_type == "trial":
        return diff_trial(old, new, monitored_fields=kw.get("monitored_fields"))
    if object_type == "label":
        return diff_label(old, new)
    if object_type == "drug_application":
        return diff_drug_application(old, new)
    return []
