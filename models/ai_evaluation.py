"""
SmartCivic+ — AI Prediction Evaluation Data Model Schema
Stores human reviews and corrections of AI decisions.
"""
from marshmallow import Schema, fields

def create_ai_evaluation_doc(
    issue_id,
    ai_task: str,
    ai_prediction: dict,
    human_decision: dict,
    was_correct: bool,
    correction_field: str = None,
    correction_delta: str = None,
    evaluated_by_id = None,
    ai_confidence: float = 1.0,
    ai_provider: str = "gemini"
) -> dict:
    from datetime import datetime
    from bson import ObjectId
    return {
        "issue_id": ObjectId(issue_id),
        "ai_task": ai_task, # "classification", "image_detection", "duplicate", "resolution_verification"
        "ai_prediction": ai_prediction,
        "human_decision": human_decision,
        "was_correct": was_correct,
        "correction_field": correction_field,
        "correction_delta": correction_delta,
        "evaluated_by_id": ObjectId(evaluated_by_id) if evaluated_by_id else None,
        "evaluated_at": datetime.utcnow(),
        "ai_confidence": float(ai_confidence),
        "ai_provider": ai_provider
    }
