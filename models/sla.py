"""
SmartCivic+ — SLA Configuration
Hardcoded rules for tracking resolution target deadlines.
"""
from datetime import timedelta

SLA_RULES = {
    "critical": timedelta(hours=4),
    "high":     timedelta(hours=12),
    "medium":   timedelta(hours=24),
    "low":      timedelta(hours=72),
}

SLA_THRESHOLDS = {
    "warning": 0.75,
    "urgent":  0.90,
    "breached": 1.0,
}
