"""
SmartCivic+ — Canonical State Machine & Lifecycle Transitions
Single Source of Truth for all issue states, statuses, aliases, and role transitions.
Consolidates previous conflicting rules across models/issue.py, validators.py, and security.py.
"""

STATUSES = [
    "submitted",
    "under_review",
    "ai_reviewed",
    "officer_reviewed",
    "verified",
    "assigned",
    "en_route",
    "in_progress",
    "work_started",
    "work_completed",
    "officer_verified",
    "citizen_verification",
    "resolved",
    "closed",
    "reopened",
    "rejected",
    "duplicate"
]

ISSUE_STATES = [
    "SUBMITTED",
    "AI_ANALYZED",
    "OFFICER_REVIEW",
    "VERIFIED",
    "ASSIGNED",
    "EN_ROUTE",
    "IN_PROGRESS",
    "WORK_COMPLETED",
    "OFFICER_VERIFICATION",
    "RESOLVED",
    "RESIDENT_CONFIRMATION",
    "CLOSED",
    "REOPENED",
    "REJECTED",
    "DUPLICATE"
]

STATUS_ALIASES = {
    # Upper-case / standard variants
    "ai_analyzed": "ai_reviewed",
    "officer_review": "officer_reviewed",
    "work_started": "in_progress",
    "officer_verification": "officer_verified",
    "resident_confirmation": "citizen_verification",
    "verified": "officer_verified",
    "completed": "work_completed",
    # Upper-case mappings
    "AI_REVIEWED": "ai_reviewed",
    "AI_ANALYZED": "ai_reviewed",
    "UNDER_REVIEW": "under_review",
    "OFFICER_REVIEW": "officer_reviewed",
    "OFFICER_REVIEWED": "officer_reviewed",
    "VERIFIED": "verified",
    "ASSIGNED": "assigned",
    "EN_ROUTE": "en_route",
    "WORK_STARTED": "in_progress",
    "IN_PROGRESS": "in_progress",
    "WORK_COMPLETED": "work_completed",
    "OFFICER_VERIFICATION": "officer_verified",
    "OFFICER_VERIFIED": "officer_verified",
    "CITIZEN_VERIFICATION": "citizen_verification",
    "RESIDENT_CONFIRMATION": "citizen_verification",
    "RESOLVED": "resolved",
    "CLOSED": "closed",
    "REOPENED": "reopened",
    "REJECTED": "rejected",
    "DUPLICATE": "duplicate"
}

# Canonical Legal State Transitions Matrix
LEGAL_TRANSITIONS = {
    "submitted":             ["under_review", "ai_reviewed", "officer_reviewed", "assigned", "rejected", "duplicate", "closed", "cancelled"],
    "ai_reviewed":           ["under_review", "officer_reviewed", "verified", "assigned", "rejected", "duplicate"],
    "under_review":          ["verified", "officer_reviewed", "assigned", "rejected", "duplicate"],
    "officer_reviewed":      ["verified", "assigned", "rejected", "duplicate"],
    "verified":              ["assigned", "rejected"],
    "assigned":              ["en_route", "work_started", "in_progress", "rejected"],
    "en_route":              ["work_started", "in_progress", "work_completed", "resolved"],
    "work_started":          ["in_progress", "work_completed", "resolved"],
    "in_progress":           ["work_completed", "resolved"],
    "work_completed":        ["resolved", "officer_verified", "work_started", "citizen_verification", "closed", "reopened"],
    "officer_verified":      ["citizen_verification", "resolved", "closed", "reopened"],
    "citizen_verification":  ["closed", "reopened", "resolved"],
    "resolved":              ["officer_verified", "citizen_verification", "closed", "reopened"],
    "closed":                ["reopened"],
    "reopened":              ["under_review", "officer_reviewed", "assigned", "rejected"],
    "duplicate":             ["under_review", "officer_reviewed", "rejected"],
    "rejected":              ["under_review", "reopened"]
}

# Role-Based Permissions Transition Matrix
ROLE_TRANSITIONS = {
    "citizen": {
        "submitted": ["cancelled", "closed"],
        "citizen_verification": ["closed", "reopened"],
        "resolved": ["closed", "reopened"],
        "work_completed": ["closed", "reopened"],
        "closed": ["reopened"]
    },
    "resident": {
        "submitted": ["cancelled", "closed"],
        "citizen_verification": ["closed", "reopened"],
        "resolved": ["closed", "reopened"],
        "work_completed": ["closed", "reopened"],
        "closed": ["reopened"]
    },
    "worker": {
        "assigned": ["en_route", "work_started", "in_progress", "work_completed", "resolved"],
        "en_route": ["work_started", "in_progress", "work_completed", "resolved"],
        "work_started": ["in_progress", "work_completed", "resolved"],
        "in_progress": ["work_completed", "resolved"]
    },
    "officer": {
        "submitted": ["under_review", "ai_reviewed", "officer_reviewed", "verified", "assigned", "rejected", "duplicate"],
        "ai_reviewed": ["under_review", "officer_reviewed", "verified", "assigned", "rejected", "duplicate"],
        "under_review": ["verified", "officer_reviewed", "assigned", "rejected", "duplicate"],
        "officer_reviewed": ["verified", "assigned", "rejected", "duplicate"],
        "verified": ["assigned", "rejected"],
        "assigned": ["en_route", "work_started", "in_progress", "rejected"],
        "en_route": ["work_started", "in_progress", "work_completed", "resolved"],
        "work_started": ["in_progress", "work_completed", "resolved"],
        "in_progress": ["work_completed", "resolved"],
        "work_completed": ["resolved", "officer_verified", "closed", "citizen_verification", "reopened"],
        "resolved": ["officer_verified", "closed", "reopened", "citizen_verification"],
        "officer_verified": ["citizen_verification", "closed", "reopened"],
        "citizen_verification": ["closed", "reopened"],
        "reopened": ["under_review", "officer_reviewed", "assigned", "rejected"],
        "duplicate": ["under_review", "officer_reviewed", "rejected"]
    },
    "admin": {
        "submitted": ["under_review", "ai_reviewed", "officer_reviewed", "assigned", "rejected", "duplicate", "closed"],
        "under_review": ["verified", "officer_reviewed", "assigned", "rejected", "duplicate", "closed"],
        "ai_reviewed": ["under_review", "officer_reviewed", "verified", "assigned", "rejected", "duplicate"],
        "officer_reviewed": ["verified", "assigned", "rejected", "duplicate"],
        "verified": ["assigned", "rejected"],
        "assigned": ["en_route", "work_started", "in_progress", "resolved", "rejected", "closed"],
        "en_route": ["work_started", "in_progress", "work_completed", "resolved"],
        "work_started": ["in_progress", "work_completed", "resolved"],
        "in_progress": ["work_completed", "resolved", "rejected", "closed"],
        "work_completed": ["resolved", "officer_verified", "closed", "citizen_verification", "reopened"],
        "resolved": ["officer_verified", "closed", "reopened"],
        "officer_verified": ["citizen_verification", "closed", "reopened"],
        "citizen_verification": ["closed", "reopened"],
        "reopened": ["under_review", "officer_reviewed", "assigned", "rejected", "closed"],
        "duplicate": ["under_review", "officer_reviewed", "rejected"],
        "closed": ["reopened"]
    }
}

ALLOWED_TRANSITIONS = LEGAL_TRANSITIONS
STATUS_TRANSITION_MATRIX = ROLE_TRANSITIONS

def normalize_status(status: str) -> str:
    """Normalizes any status string (case-insensitive, alias mapped) to its canonical lowercase form."""
    if not status:
        return ""
    st = str(status).strip()
    # Check direct alias
    if st in STATUS_ALIASES:
        return STATUS_ALIASES[st]
    st_lower = st.lower()
    return STATUS_ALIASES.get(st_lower, st_lower)

def validate_state_transition(current_state: str, target_state: str, role: str = None) -> bool:
    """
    Validates whether transitioning from current_state to target_state is permitted.
    Handles aliases and casing transparently. If role is provided, enforces role permissions.
    """
    curr = normalize_status(current_state)
    target = normalize_status(target_state)

    if not curr or not target:
        return False
    if curr == target:
        return True

    allowed_targets = LEGAL_TRANSITIONS.get(curr, [])
    # Check directly or via normalized forms
    if target not in allowed_targets and not any(normalize_status(a) == target for a in allowed_targets):
        return False

    if role:
        role_lower = str(role).strip().lower()
        role_map = ROLE_TRANSITIONS.get(role_lower, {})
        allowed_for_role = role_map.get(curr, [])
        if target not in allowed_for_role and not any(normalize_status(a) == target for a in allowed_for_role):
            return False

    return True
