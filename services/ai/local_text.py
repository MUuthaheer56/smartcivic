"""
SmartCivic — Local Text Classifier Service (TF-IDF Baseline)
Loads local text classification bundle via ModelRegistry.
Predicts municipal service, issue type, and emergency possible flag.
Returns standardized AI envelope.
Fails safely if model is missing, corrupt, or a placeholder.
"""
import os
import time
import logging
from typing import Optional, Dict, Any
import joblib

from config import Config
from services.ai.registry import registry, load_model, MIN_MODEL_BYTES
from services.ai.envelope import make_ai_result

logger = logging.getLogger(__name__)


def _joblib_loader(model_path: str):
    """Loads joblib model bundle safely."""
    try:
        return joblib.load(model_path)
    except Exception as e:
        logger.warning(f"[LocalText] Failed to load joblib artifact '{model_path}': {e}")
        return None


# Register local text classifier with registry
registry.register(
    name="text_classifier",
    default_rel_path="models_artifacts/text_classifier_v1.joblib",
    loader_fn=_joblib_loader
)


def _get_active_text_model():
    """Attempts to load active text classifier bundle from registry with fallbacks."""
    # 1. Primary artifact path
    bundle = load_model("text_classifier")
    if bundle is not None:
        return bundle, "models_artifacts/text_classifier_v1.joblib"

    # 2. Check ml/models fallback
    ml_path = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "models", "text_classifier_v1.joblib")
    if os.path.exists(ml_path):
        bundle = load_model("text_classifier", custom_path=ml_path)
        if bundle is not None:
            return bundle, ml_path

    return None, None


def predict_local_text(text: str, bundle_override: Any = None) -> Dict[str, Any]:
    """
    Executes local text classification on description.
    Returns standardized AI envelope.
    Degrades cleanly if model is unavailable or a placeholder.
    """
    t0 = time.time()
    clean_text = (text or "").strip()

    bundle, _ = (bundle_override, "override") if bundle_override else _get_active_text_model()
    if bundle is None or not clean_text:
        latency = int((time.time() - t0) * 1000)
        return make_ai_result(
            value={
                "available": False,
                "service": "unknown_other",
                "issue_type": None,
                "emergency": False,
                "emergency_probability": 0.0,
                "confidence": 0.0,
                "reason": "model_missing_or_empty_text"
            },
            confidence=0.0,
            source="local_text",
            model_version="tfidf_logreg_v1",
            evidence_level="inferred",
            fallback_used=True,
            latency_ms=latency,
            error="Local text classifier model unavailable or empty text"
        )

    try:
        vec = bundle["vectorizer"]
        service_model = bundle["service_model"]
        type_model = bundle["issue_type_model"]
        emerg_model = bundle["emergency_model"]

        X = vec.transform([clean_text])

        # 1. Service prediction + confidence
        service_probs = service_model.predict_proba(X)[0]
        top_idx = int(service_probs.argmax())
        service_pred = str(service_model.classes_[top_idx])
        service_conf = float(service_probs[top_idx])

        # 2. Issue type prediction
        type_pred = str(type_model.predict(X)[0])

        # 3. Emergency prediction
        emerg_probs = emerg_model.predict_proba(X)[0]
        # Locate True class index if present
        classes_list = list(emerg_model.classes_)
        if True in classes_list:
            t_idx = classes_list.index(True)
            emerg_prob = float(emerg_probs[t_idx])
        elif 1 in classes_list:
            t_idx = classes_list.index(1)
            emerg_prob = float(emerg_probs[t_idx])
        else:
            emerg_prob = 0.0

        is_emergency = emerg_prob >= 0.50

        latency = int((time.time() - t0) * 1000)

        return make_ai_result(
            value={
                "available": True,
                "service": service_pred,
                "issue_type": type_pred,
                "emergency": is_emergency,
                "emergency_probability": round(emerg_prob, 3),
                "confidence": round(service_conf, 3)
            },
            confidence=round(service_conf, 3),
            source="local_text",
            model_version=bundle.get("version", "tfidf_logreg_v1"),
            evidence_level="inferred",
            fallback_used=False,
            latency_ms=latency
        )

    except Exception as exc:
        logger.warning(f"[LocalText] Prediction exception: {exc}")
        latency = int((time.time() - t0) * 1000)
        return make_ai_result(
            value={
                "available": False,
                "service": "unknown_other",
                "issue_type": None,
                "emergency": False,
                "emergency_probability": 0.0,
                "confidence": 0.0,
                "reason": f"prediction_exception:{type(exc).__name__}"
            },
            confidence=0.0,
            source="local_text",
            model_version="tfidf_logreg_v1",
            evidence_level="inferred",
            fallback_used=True,
            latency_ms=latency,
            error=str(exc)
        )

