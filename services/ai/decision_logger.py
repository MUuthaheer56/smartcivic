"""
SmartCivic — AI Decision & Correction Audit Logger
Records every AI decision envelope and officer correction for compliance, auditing,
and offline model evaluation/training.
"""
from datetime import datetime
import logging
from typing import Any, Dict, Optional
from config import Config
from services.ai.envelope import make_ai_result

logger = logging.getLogger(__name__)

def log_ai_decision(db, issue_id: Any, stage: str, envelope: Dict[str, Any], model_version: str = "v1.0") -> None:
    """
    Writes one row to db.ai_decisions for an AI stage per issue.
    Safe and fail-open: never raises an exception.
    """
    if db is None or not issue_id:
        return

    try:
        flag_snapshot = {
            "AI_LOCAL_TEXT_ENABLED": getattr(Config, "AI_LOCAL_TEXT_ENABLED", False),
            "AI_LOCAL_DETECTOR_ENABLED": getattr(Config, "AI_LOCAL_DETECTOR_ENABLED", False),
            "AI_EMBED_DUPLICATES_ENABLED": getattr(Config, "AI_EMBED_DUPLICATES_ENABLED", False),
            "AI_IMAGE_GATE_ENABLED": getattr(Config, "AI_IMAGE_GATE_ENABLED", False),
            "AI_REPAIR_V2_ENABLED": getattr(Config, "AI_REPAIR_V2_ENABLED", False),
            "AI_ML_PRIORITY_SHADOW": getattr(Config, "AI_ML_PRIORITY_SHADOW", False),
        }

        doc = {
            "issue_id": str(issue_id),
            "stage": stage,
            "envelope": envelope,
            "model_version": model_version,
            "flag_snapshot": flag_snapshot,
            "created_at": datetime.utcnow()
        }

        db.ai_decisions.insert_one(doc)
    except Exception as e:
        logger.warning(f"[AIDecisionLogger] Failed to write ai_decision for issue {issue_id}: {e}")

def log_ai_correction(
    db,
    issue_id: Any,
    field_changed: str,
    before_value: Any,
    after_value: Any,
    actor_id: Any,
    actor_role: str = "officer",
    reason: Optional[str] = None
) -> None:
    """
    Writes one row to db.ai_corrections when an officer/admin overrides an AI prediction
    or accepts/rejects a suggestion.
    Safe and fail-open: never raises an exception.
    """
    if db is None or not issue_id:
        return

    try:
        doc = {
            "issue_id": str(issue_id),
            "field_changed": field_changed,
            "before_value": before_value,
            "after_value": after_value,
            "actor_id": str(actor_id) if actor_id else None,
            "actor_role": actor_role,
            "reason": reason or "",
            "created_at": datetime.utcnow()
        }
        db.ai_corrections.insert_one(doc)
    except Exception as e:
        logger.warning(f"[AIDecisionLogger] Failed to write ai_correction for issue {issue_id}: {e}")

