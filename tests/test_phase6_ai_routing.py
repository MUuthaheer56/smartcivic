import pytest
import os
from unittest.mock import patch, MagicMock

from services.ai_classifier import classify_complaint, pattern_emergency_check, SERVICE_CLASSES
from services.ai_service import detect_and_translate, _rule_based_fallback
from services.cefap_pipeline import _reliability

def test_shared_vocabulary_sanitation_and_drainage():
    """
    AI-01: Classification of sanitation and drainage complaints MUST resolve
    to valid service classes rather than collapsing into 'unknown_other'.
    """
    assert "sanitation" in SERVICE_CLASSES
    assert "drainage" in SERVICE_CLASSES
    
    # Test sanitation fallback
    res_san = classify_complaint("Piles of rotting garbage dumped on roadside")
    assert res_san["service"] in ["sanitation", "solid_waste"], f"Expected sanitation/solid_waste, got {res_san['service']}"
    assert res_san["route_decision"] != "HUMAN_TRIAGE" or res_san["service"] != "unknown_other"

    # Test drainage fallback
    res_drain = classify_complaint("Stormwater drain clogged and sewage overflowing into houses")
    assert res_drain["service"] in ["drainage", "water"], f"Expected drainage/water, got {res_drain['service']}"
    assert res_drain["service"] != "unknown_other"

def test_expanded_emergency_detection_english_kannada_hinglish():
    """
    AI-02: Emergency patterns cover life hazards, drowning, cardiac arrests,
    Kannada scripts, and Hinglish phrasing without false dismissal.
    """
    emergencies = [
        "Gas cylinder blast at bakery with severe fire",
        "Vehicle accident car crashed with severe bleeding",
        "Old man had a severe heart attack on bus stand",
        "Toddler fell into open drain and is drowning",
        "Labourer electrocuted by loose underground cable",
        "Chemical factory chlorine gas leak spreading",
        "Trench collapsed at construction site workers trapped",
        "ರಸ್ತೆಯಲ್ಲಿ ಭೀಕರ ಅಪಘಾತ ರಕ್ತಸ್ರಾವವಾಗುತ್ತಿದೆ", # Kannada accident bleeding
        "ಮನೆಯಲ್ಲಿ ಬೆಂಕಿ ಹೊತ್ತಿಕೊಂಡಿದೆ ಜನ ಸಿಲುಕಿದ್ದಾರೆ", # Kannada fire trapped
        "Basti me aag lag gayi hai bahut bada khatra hai", # Hinglish fire danger
    ]
    for em in emergencies:
        assert pattern_emergency_check(em) is True, f"Failed to detect emergency in: '{em}'"

    # Negation tests
    assert pattern_emergency_check("Old extinguished fire from yesterday garbage pile") is False
    assert pattern_emergency_check("No accident reported here, just street light is dim") is False

def test_offline_indic_translation_fallback():
    """
    AI-03: When Gemini is offline, Unicode Indic text is mapped through
    vernacular keywords into English civic tokens, enabling valid classification.
    """
    # Kannada pothole
    kannada_text = "ರಸ್ತೆಯಲ್ಲಿ ದೊಡ್ಡ ಗುಂಡಿ ಬಿದ್ದಿದೆ"
    res = detect_and_translate(kannada_text)
    assert res["detected_language"] == "kannada"
    assert "road" in res["translated_text"] or "pothole" in res["translated_text"]

    # Kannada garbage
    kannada_garbage = "ಇಲ್ಲಿ ಕಸದ ರಾಶಿ ಬಿದ್ದಿದೆ"
    res_g = detect_and_translate(kannada_garbage)
    assert res_g["detected_language"] == "kannada"
    assert "garbage" in res_g["translated_text"] or "waste" in res_g["translated_text"]

def test_fail_fast_on_429_quota():
    """
    AI-05: When Gemini returns a 429 quota exhausted error,
    it trips the circuit breaker and fails fast without cycling through candidate models.
    """
    from services.ai_service import _generate_content_with_model_fallback, gemini_circuit_breaker
    
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("429 ResourceExhausted: Quota exceeded")
    
    with pytest.raises(Exception, match="429"):
        _generate_content_with_model_fallback(mock_client, "test", "gemini-1.5-flash")
        
    assert gemini_circuit_breaker.state == "OPEN"
    gemini_circuit_breaker.reset()

def test_cefap_disagreement_damping():
    """
    AI-06: Disagreement between text and photo does NOT crush priority
    to P3; effective disagreement is floored to prevent penalizing photo uploads.
    """
    # High text severity (1.0), low visual severity (0.2) -> disagreement = 0.8
    image_evidence = {"score": 0.20, "confidence": 0.80}
    rel = _reliability(1.0, 0.80, image_evidence)
    
    assert rel["ctve_triggered"] is True
    # With effective disagreement capped at 0.50, E should be at least (0.80 + 0.80)/2 * (1 - 0.50) = 0.40
    assert rel["E"] >= 0.35, f"Reliability E crushed too low: {rel['E']}"

def test_calibrated_confidence():
    """
    AI-07: Rule-based fallback produces computed, calibrated confidence
    based on keyword match specificity and text length, not static 0.75.
    """
    short_vague = _rule_based_fallback("broken")
    rich_specific = _rule_based_fallback("Severe electrical live wire spark short circuit in residential street")
    
    assert rich_specific["confidence"] > short_vague["confidence"]
    assert rich_specific["confidence_type"] == "heuristic"
