"""
SmartCivic+ — SLA Configuration
Hardcoded rules for tracking resolution target deadlines.
"""
from datetime import timedelta

SLA_HOURS = {
    "P0": 1,
    "P1": 4,
    "P2": 24,
    "P3": 72,
    "critical": 1,
    "high": 4,
    "medium": 24,
    "low": 72,
}

SLA_RULES = {
    "P0": timedelta(hours=1),
    "P1": timedelta(hours=4),
    "P2": timedelta(hours=24),
    "P3": timedelta(hours=72),
    "critical": timedelta(hours=1),
    "high":     timedelta(hours=4),
    "medium":   timedelta(hours=24),
    "low":      timedelta(hours=72),
}

SLA_THRESHOLDS = {
    "warning": 0.75,
    "urgent":  0.90,
    "breached": 1.0,
}
