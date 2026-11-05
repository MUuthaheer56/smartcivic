# FIX REPORT: Phase 6 — AI Decision Logic, Fallbacks, and Safety Hardening

**Branch**: `fix/phase-6`  
**Date**: November 5, 2026  
**Status**: COMPLETE & VERIFIED  

---

## 1. Executive Summary

Phase 6 addressed critical defects identified in `AUDIT_06_AI_ROUTING.md`, including vocabulary mismatches that caused sanitation and drainage complaints to collapse into `unknown_other`, high false-negative rates in safety emergency detection, Indic language translation failures when Gemini is offline, slow model fallback cascades under HTTP 429 quota exhaustion, perverse disagreement penalties in CEFAP priority scoring, and uncalibrated heuristic confidence metrics.

All changes maintain strict backwards compatibility with mobile and web frontend payload expectations, while establishing deterministic safety boundaries around untrusted AI model outputs.

---

## 2. Issues Remediated

| Vulnerability ID | Component | Defect | Resolution Applied | Verification |
| :--- | :--- | :--- | :--- | :--- |
| **AI-01** | `services/ai_classifier.py` | Vocabulary mismatch: `SERVICE_CLASSES` lacked `"sanitation"` and `"drainage"`, causing rule-based and Gemini outputs for waste/drainage to collapse into `"unknown_other"` and trigger unnecessary `HUMAN_TRIAGE`. | Added `"sanitation"`, `"drainage"`, and `"noise"` to canonical `SERVICE_CLASSES`. | `tests/test_phase6_ai_routing.py::test_shared_vocabulary_sanitation_and_drainage` |
| **AI-02** | `services/ai_classifier.py` | Emergency pattern regex failed on 43.3% of critical emergencies (cardiac arrest, drowning, electrocution, collapsed sinkholes, chemical/chlorine leaks, and vernacular phrasing in Kannada and Hinglish). | Expanded `EMERGENCY_PATTERNS` to cover vehicular/pedestrian collisions, structural collapses, cardiac/medical trauma, drowning, electrical arcing/shocks, chemical/gas leaks, and Kannada (`ತುರ್ತು`, `ಅಪಘಾತ`, `ಬೆಂಕಿ`) & Hinglish (`madad`, `khatra`, `aag lag`) emergencies. | `tests/test_phase6_ai_routing.py::test_expanded_emergency_detection_english_kannada_hinglish` (20/20 benchmark passed, 100% recall). |
| **AI-03** | `services/ai_service.py` | Offline Indic language translation fallback returned untranslated text directly (`translated_text: text`), dropping Kannada accuracy to 0% and classifying reports as `unknown_other`. | Added offline Indic civic glossary mapping Kannada, Hindi, Tamil, and Telugu municipal keywords (e.g. `ಗುಂಡಿ`, `ಕಸ`, `ಚರಂಡಿ`, `ನೀರು`, `ಗಡ್ढा`) into English civic tokens before downstream classification. | `tests/test_phase6_ai_routing.py::test_offline_indic_translation_fallback` |
| **AI-05** | `services/ai_service.py` | Sequential candidate model loop (`candidates = [...]`) executed multiple remote queries when Google Gemini returned HTTP 429 quota exhaustion, adding 3–8s latency penalties. | Added fail-fast logic on HTTP 429 / `RESOURCE_EXHAUSTED` / `rate limit`: immediately trips `gemini_circuit_breaker` to `OPEN` and aborts directly to resilient rules without looping through other candidates. | `tests/test_phase6_ai_routing.py::test_fail_fast_on_429_quota` |
| **AI-06** | `services/cefap_pipeline.py` | Perverse disagreement penalty: $E = C_{avg} \times (1 - D)$ crushed priority from P0 to P3 when an uploaded photo had low visual confidence, penalizing citizens who uploaded photos compared to text alone. | Capped effective disagreement penalty at $0.50$ (`effective_disagreement = min(disagreement, 0.50)`), preserving evidence reliability floor ($E \ge 0.35$). | `tests/test_phase6_ai_routing.py::test_cefap_disagreement_damping` |
| **AI-07** | `services/ai_service.py` | Confidence scores were hardcoded to static values (`0.75`), providing zero calibration or uncertainty estimation. | Implemented dynamic confidence calculation based on keyword match specificity, department alignment, and text richness. | `tests/test_phase6_ai_routing.py::test_calibrated_confidence` |

---

## 3. Test Verification & Results

### Dedicated Phase 6 Test Suite (`tests/test_phase6_ai_routing.py`)
- `test_shared_vocabulary_sanitation_and_drainage`: **PASSED** (sanitation and drainage resolve to proper service classes and do not default to `unknown_other`).
- `test_expanded_emergency_detection_english_kannada_hinglish`: **PASSED** (100% recall across 20 emergency test cases in English, Kannada, and Hinglish; negations handled cleanly).
- `test_offline_indic_translation_fallback`: **PASSED** (Kannada phrases for road damage and garbage successfully translated to civic tokens offline).
- `test_fail_fast_on_429_quota`: **PASSED** (trips circuit breaker and fails fast without cycling through redundant candidates).
- `test_cefap_disagreement_damping`: **PASSED** (severe text + weak image retains $E \ge 0.35$ and does not collapse priority).
- `test_calibrated_confidence`: **PASSED** (specific rich descriptions achieve higher confidence than short vague descriptions).

```
============================== 6 passed in 3.76s ==============================
```

### Full Regression Suite
- **174 passed in 44.52s** (0 failures, 0 regressions across all phases).

---

## 4. Next Phase Gate

Phase 6 remediation is fully tested and committed to branch `fix/phase-6`. Per the Master Fix Plan, the agent must halt and wait for user confirmation before proceeding to **Phase 7: Mobile, dependencies, tests, frontend quality** (`after_image` vs `image` in mobile resolve, pip-audit dependency upgrades, mock Gemini offline test suite, Leaflet/toast frontend deduplication).
