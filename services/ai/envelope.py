"""
SmartCivic — Shared AI Result Envelope
Standardized return contract for all models, rules, Gemini, and heuristics.
"""
from typing import Any, Optional, Dict

VALID_SOURCES = {"yolo", "gemini", "local_text", "embeddings", "rules", "human", "cefap"}
VALID_EVIDENCE_LEVELS = {"detected", "inferred", "verified"}

def make_ai_result(
    value: Any,
    confidence: Optional[float] = None,
    source: str = "rules",
    model_version: str = "v1.0",
    evidence_level: str = "inferred",
    fallback_used: bool = False,
    latency_ms: int = 0,
    error: Optional[str] = None
) -> Dict[str, Any]:
    """
    Constructs a validated AI result envelope conforming to the SmartCivic Master Plan.
    """
    if confidence is not None:
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (ValueError, TypeError):
            confidence = None

    if evidence_level not in VALID_EVIDENCE_LEVELS:
        evidence_level = "inferred"

    return {
        "value": value,
        "confidence": confidence,
        "source": source,
        "model_version": str(model_version),
        "evidence_level": evidence_level,
        "fallback_used": bool(fallback_used),
        "latency_ms": int(latency_ms),
        "error": error
    }

