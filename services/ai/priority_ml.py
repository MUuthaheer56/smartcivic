"""
SmartCivic — ML Prioritisation Advisory Service
Loads trained Random Forest / tree priority model via ModelRegistry.
Calculates suggested priority (P0–P3) and probability distribution from CEFAP signals.
Returns standardized AI result envelope.
CRITICAL CONTRACT RULE R2: This output is strictly advisory. Stored operational priority
is always determined by canonical CEFAP and never modified by this service.
"""
import os
import time
import logging
from typing import Optional, Dict, Any
import joblib
import numpy as np
import pandas as pd

from config import Config
from services.ai.registry import registry, load_model, MIN_MODEL_BYTES
from services.ai.envelope import make_ai_result

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "text_severity",
    "image_severity",
    "location_impact",
    "corroboration",
    "recurrence",
    "sla_risk",
    "evidence_reliability",
    "disagreement",
    "monsoon_active"
]

INV_LABEL_MAP = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}


def _priority_model_loader(model_path: str):
    """Safely loads serialized priority model bundle."""
    try:
        return joblib.load(model_path)
    except Exception as e:
        logger.warning(f"[PriorityML] Failed to load artifact '{model_path}': {e}")
        return None


# Register with ModelRegistry
registry.register(
    name="priority_model",
    default_rel_path="models_artifacts/priority_model_v1.joblib",
    loader_fn=_priority_model_loader
)


def _get_active_priority_model():
    """Attempts to load active priority model bundle from registry."""
    bundle = load_model("priority_model")
    if bundle is not None:
        return bundle, "models_artifacts/priority_model_v1.joblib"

    # Secondary path check in ml/models
    alt_path = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "models", "priority_model_v1.joblib")
    if os.path.exists(alt_path):
        bundle = load_model("priority_model", custom_path=alt_path)
        if bundle is not None:
            return bundle, alt_path

    return None, None


def predict_priority_ml(signals: Dict[str, Any], bundle_override: Any = None) -> Dict[str, Any]:
    """
    Computes ML-suggested priority from CEFAP signals dictionary.
    Returns standardized AI result envelope.
    Degrades cleanly if model is unavailable or a placeholder.
    """
    t0 = time.time()
    bundle, _ = (bundle_override, "override") if bundle_override else _get_active_priority_model()

    if bundle is None:
        latency = int((time.time() - t0) * 1000)
        return make_ai_result(
            value={
                "available": False,
                "suggested_priority": None,
                "confidence": 0.0,
                "probabilities": {},
                "is_critical": False,
                "advisory_only": True,
                "reason": "model_missing_or_corrupt"
            },
            confidence=0.0,
            source="ml_priority",
            model_version="priority_rf_v1",
            evidence_level="inferred",
            fallback_used=True,
            latency_ms=latency,
            error="Priority ML model unavailable"
        )

    try:
        model = bundle["model"]
        feature_names = bundle.get("feature_names", FEATURE_COLS)
        inv_map = bundle.get("inv_label_map", INV_LABEL_MAP)

        # Build feature vector
        vector = []
        for feat in feature_names:
            val = signals.get(feat, 0.0)
            if feat == "monsoon_active":
                val = 1.0 if bool(val) else 0.0
            elif val is None:
                val = 0.0
            else:
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    val = 0.0
            vector.append(val)

        X = pd.DataFrame([vector], columns=feature_names)
        probs = model.predict_proba(X)[0]
        top_idx = int(probs.argmax())
        top_priority = inv_map.get(top_idx, "P2")
        confidence = float(probs[top_idx])

        # Feature importances for explanation
        feature_importances = getattr(model, "feature_importances_", None)
        top_features = []
        if feature_importances is not None:
            sorted_feats = sorted(zip(feature_names, feature_importances), key=lambda x: x[1], reverse=True)
            top_features = [{"feature": f, "weight": round(float(w), 3)} for f, w in sorted_feats[:3]]

        latency = int((time.time() - t0) * 1000)
        prob_dict = {inv_map.get(idx, f"P{idx}"): round(float(p), 4) for idx, p in enumerate(probs)}

        return make_ai_result(
            value={
                "available": True,
                "suggested_priority": top_priority,
                "confidence": round(confidence, 4),
                "probabilities": prob_dict,
                "is_critical": top_priority in ["P0", "P1"],
                "advisory_only": True,
                "top_features": top_features
            },
            confidence=round(confidence, 4),
            source="ml_priority",
            model_version="priority_rf_v1",
            evidence_level="inferred",
            fallback_used=False,
            latency_ms=latency,
            error=None
        )

    except Exception as exc:
        latency = int((time.time() - t0) * 1000)
        logger.warning(f"[PriorityML] Inference failure: {exc}")
        return make_ai_result(
            value={
                "available": False,
                "suggested_priority": None,
                "confidence": 0.0,
                "probabilities": {},
                "is_critical": False,
                "advisory_only": True,
                "reason": f"inference_error: {str(exc)}"
            },
            confidence=0.0,
            source="ml_priority",
            model_version="priority_rf_v1",
            evidence_level="inferred",
            fallback_used=True,
            latency_ms=latency,
            error=str(exc)
        )
