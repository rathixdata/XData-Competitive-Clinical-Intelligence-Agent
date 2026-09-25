"""Deterministic normalization helpers shared by adapters and the change engine."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

from dateutil import parser as dateparser

_WS = re.compile(r"\s+")
_ISO_PARTIAL = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

PHASE_MAP = {
    "EARLY_PHASE1": "Phase 1",
    "PHASE1": "Phase 1",
    "PHASE1/PHASE2": "Phase 1/2",
    "PHASE2": "Phase 2",
    "PHASE2/PHASE3": "Phase 2/3",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "N/A",
}

STATUS_MAP = {
    "NOT_YET_RECRUITING": "Not yet recruiting",
    "RECRUITING": "Recruiting",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation",
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "SUSPENDED": "Suspended",
    "TERMINATED": "Terminated",
    "COMPLETED": "Completed",
    "WITHDRAWN": "Withdrawn",
    "UNKNOWN": "Unknown",
}


def clean_text(value: Any) -> str:
    """Collapse whitespace, normalize unicode - used to suppress formatting-only changes (FR-CHG-005)."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return _WS.sub(" ", s).strip()


def comparable_text(value: Any) -> str:
    """Case/punctuation-insensitive form for semantic-equivalence checks."""
    s = clean_text(value).lower()
    s = re.sub(r"[^\w\s%<>=.+-]", " ", s)
    s = re.sub(r"(?<=\d)\.0+\b", "", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)  # sentence punctuation, keep decimal points
    return _WS.sub(" ", s).strip()


def normalize_partial_date(value: Any) -> str | None:
    """Return ISO partial date ('2027', '2027-06', '2027-06-30') regardless of input formatting."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = clean_text(value)
    if _ISO_PARTIAL.match(s):
        return s
    has_day = bool(re.search(r"\b\d{1,2}(st|nd|rd|th)?\b[ ,]", s + " ")) and not re.fullmatch(r"[A-Za-z]+\s+\d{4}", s)
    try:
        dt = dateparser.parse(s, default=datetime(1900, 1, 1))
    except (ValueError, OverflowError):
        return s
    if dt is None:
        return s
    if re.fullmatch(r"\d{4}", s):
        return f"{dt.year:04d}"
    if not has_day:
        return f"{dt.year:04d}-{dt.month:02d}"
    return dt.date().isoformat()


def partial_date_to_date(value: str | None, *, end_of_period: bool = False) -> date | None:
    if not value:
        return None
    try:
        parts = [int(p) for p in value.split("-")]
    except ValueError:
        return None
    if len(parts) == 3:
        return date(*parts)
    if len(parts) == 2:
        y, m = parts
        if end_of_period:
            import calendar

            return date(y, m, calendar.monthrange(y, m)[1])
        return date(y, m, 1)
    if len(parts) == 1:
        return date(parts[0], 12, 31) if end_of_period else date(parts[0], 1, 1)
    return None


def months_between(a: str | None, b: str | None) -> float | None:
    da, db = partial_date_to_date(a), partial_date_to_date(b)
    if not da or not db:
        return None
    return round((db - da).days / 30.4375, 1)


def normalize_phase(phases: list[str] | None) -> str | None:
    if not phases:
        return None
    key = "/".join(sorted(p.upper() for p in phases))
    return PHASE_MAP.get(key, " / ".join(PHASE_MAP.get(p.upper(), p) for p in phases))


def normalize_status(status: str | None) -> str | None:
    if not status:
        return None
    return STATUS_MAP.get(status.upper(), clean_text(status).capitalize())


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = dateparser.parse(str(value))
    except (ValueError, OverflowError):
        return None
    if dt and dt.tzinfo is None:
        from datetime import UTC

        dt = dt.replace(tzinfo=UTC)
    return dt
