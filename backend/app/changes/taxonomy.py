"""Change taxonomy (FR-CHG-004). Every event has exactly one primary type plus optional tags."""

from __future__ import annotations

from enum import StrEnum


class ChangeType(StrEnum):
    TRIAL_REGISTERED = "TRIAL_REGISTERED"
    TRIAL_STARTED = "TRIAL_STARTED"
    STATUS_CHANGED = "STATUS_CHANGED"
    PHASE_CHANGED = "PHASE_CHANGED"
    ENROLLMENT_CHANGED = "ENROLLMENT_CHANGED"
    ENDPOINT_CHANGED = "ENDPOINT_CHANGED"
    DATE_CHANGED = "DATE_CHANGED"
    ARM_CHANGED = "ARM_CHANGED"
    INTERVENTION_CHANGED = "INTERVENTION_CHANGED"
    ELIGIBILITY_CHANGED = "ELIGIBILITY_CHANGED"
    SPONSOR_CHANGED = "SPONSOR_CHANGED"
    LOCATION_CHANGED = "LOCATION_CHANGED"
    CONDITION_CHANGED = "CONDITION_CHANGED"
    TITLE_CHANGED = "TITLE_CHANGED"
    NEW_PUBLICATION = "NEW_PUBLICATION"
    APPROVAL = "APPROVAL"
    SUPPLEMENTAL_APPROVAL = "SUPPLEMENTAL_APPROVAL"
    LABEL_CHANGED = "LABEL_CHANGED"
    CORPORATE_EVENT = "CORPORATE_EVENT"
    CONFERENCE_ABSTRACT = "CONFERENCE_ABSTRACT"


# Precedence used to choose the primary type when several changes are grouped into one intelligence
# event (higher = more decision-relevant).
PRECEDENCE: dict[str, int] = {
    ChangeType.APPROVAL: 100,
    ChangeType.STATUS_CHANGED: 95,
    ChangeType.ENDPOINT_CHANGED: 90,
    ChangeType.SUPPLEMENTAL_APPROVAL: 85,
    ChangeType.LABEL_CHANGED: 80,
    ChangeType.TRIAL_STARTED: 78,
    ChangeType.PHASE_CHANGED: 76,
    ChangeType.DATE_CHANGED: 72,
    ChangeType.ENROLLMENT_CHANGED: 70,
    ChangeType.TRIAL_REGISTERED: 68,
    ChangeType.ARM_CHANGED: 65,
    ChangeType.INTERVENTION_CHANGED: 64,
    ChangeType.ELIGIBILITY_CHANGED: 60,
    ChangeType.CORPORATE_EVENT: 58,
    ChangeType.NEW_PUBLICATION: 55,
    ChangeType.CONFERENCE_ABSTRACT: 54,
    ChangeType.SPONSOR_CHANGED: 50,
    ChangeType.CONDITION_CHANGED: 45,
    ChangeType.LOCATION_CHANGED: 20,
    ChangeType.TITLE_CHANGED: 10,
}

# Default intrinsic change magnitude (C dimension base, 0-100); refined per change in materiality.
BASE_MAGNITUDE: dict[str, float] = {
    ChangeType.APPROVAL: 95,
    ChangeType.STATUS_CHANGED: 60,
    ChangeType.ENDPOINT_CHANGED: 90,
    ChangeType.SUPPLEMENTAL_APPROVAL: 70,
    ChangeType.LABEL_CHANGED: 55,
    ChangeType.TRIAL_STARTED: 65,
    ChangeType.PHASE_CHANGED: 80,
    ChangeType.DATE_CHANGED: 55,
    ChangeType.ENROLLMENT_CHANGED: 50,
    ChangeType.TRIAL_REGISTERED: 70,
    ChangeType.ARM_CHANGED: 60,
    ChangeType.INTERVENTION_CHANGED: 60,
    ChangeType.ELIGIBILITY_CHANGED: 45,
    ChangeType.CORPORATE_EVENT: 45,
    ChangeType.NEW_PUBLICATION: 45,
    ChangeType.CONFERENCE_ABSTRACT: 50,
    ChangeType.SPONSOR_CHANGED: 65,
    ChangeType.CONDITION_CHANGED: 50,
    ChangeType.LOCATION_CHANGED: 10,
    ChangeType.TITLE_CHANGED: 5,
}

# Trial field -> change type. Configurable per deployment via landscape config "monitored_fields".
TRIAL_FIELD_TYPES: dict[str, str] = {
    "status": ChangeType.STATUS_CHANGED,
    "phase": ChangeType.PHASE_CHANGED,
    "enrollment": ChangeType.ENROLLMENT_CHANGED,
    "primary_endpoints": ChangeType.ENDPOINT_CHANGED,
    "secondary_endpoints": ChangeType.ENDPOINT_CHANGED,
    "start_date": ChangeType.DATE_CHANGED,
    "primary_completion_date": ChangeType.DATE_CHANGED,
    "completion_date": ChangeType.DATE_CHANGED,
    "arms": ChangeType.ARM_CHANGED,
    "interventions": ChangeType.INTERVENTION_CHANGED,
    "eligibility_criteria": ChangeType.ELIGIBILITY_CHANGED,
    "sponsor": ChangeType.SPONSOR_CHANGED,
    "collaborators": ChangeType.SPONSOR_CHANGED,
    "countries": ChangeType.LOCATION_CHANGED,
    "locations": ChangeType.LOCATION_CHANGED,
    "conditions": ChangeType.CONDITION_CHANGED,
    "brief_title": ChangeType.TITLE_CHANGED,
    "official_title": ChangeType.TITLE_CHANGED,
}

# Fields never diffed (bookkeeping only).
IGNORED_TRIAL_FIELDS = {"last_update_posted", "nct_id", "keywords", "acronym", "enrollment_type",
                        "primary_completion_date_type", "why_stopped", "minimum_age", "sex", "study_type"}

HALTED_STATUSES = {"Terminated", "Suspended", "Withdrawn"}


def primary_of(types: list[str]) -> str:
    return max(types, key=lambda t: PRECEDENCE.get(t, 0))
