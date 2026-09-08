"""
SmartCivic+ — Central AI Service
Provides centralized entry point for text & image analysis, duplicate checks,
and resolution verification via Gemini with graceful rule-based fallbacks.
"""
import os
import math
import time
from datetime import datetime
from bson import ObjectId
import json
from services.logger_service import log_ai_call

# Fallback classifier mappings
CATEGORY_TO_DEPT = {
    "road": "roads",
    "water": "water_supply",
    "electricity": "electrical",
    "sanitation": "sanitation",
    "drainage": "drainage",
    "other": "roads"
}

VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.6-flash")
ALLOWED_CATEGORIES = {"road", "water", "electricity", "sanitation", "drainage", "noise", "other"}
ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}

def _generate_content_with_model_fallback(genai, contents, preferred_model: str):
    candidates = [preferred_model, "gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-1.5-flash", "gemini-2.5-flash", "gemini-flash-latest"]
    seen = set()
    last_err = None
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            model = genai.GenerativeModel(name)
            response = model.generate_content(contents)
            return response, name
        except Exception as e:
            err_msg = str(e)
            if any(term in err_msg.lower() for term in ["404", "429", "not found", "no longer available", "quota", "resourceexhausted", "rate"]):
                last_err = e
                continue
            raise e
    raise last_err or RuntimeError("No Gemini model candidates responded.")

def _normalize_category(value: str) -> str:
    value = str(value or "other").strip().lower()
    aliases = {
        "roads": "road",
        "road_damage": "road",
        "road surface damage": "road",
        "waste": "sanitation",
        "garbage": "sanitation",
        "streetlight": "electricity",
        "street_lighting": "electricity",
        "water_supply": "water",
        "sewer": "drainage"
    }
    return aliases.get(value, value) if value in ALLOWED_CATEGORIES or value in aliases else "other"

def _normalize_severity(value: str) -> str:
    value = str(value or "medium").strip().lower()
    return value if value in ALLOWED_SEVERITIES else "medium"

def _prediction_explanation(prediction: dict, image_analysis: dict = None, disagreement: bool = False) -> str:
    reason = (image_analysis or {}).get("reason") or ""
    if reason:
        return reason.strip()
    source = "visual and description evidence" if image_analysis and image_analysis.get("available") else "complaint description"
    qualifier = "; image and text signals disagree" if disagreement else ""
    return f"Classified as {prediction.get('severity', 'medium')} severity {prediction.get('type', 'other')} in the {prediction.get('category', 'other')} category from {source}{qualifier}."

def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences Gemini sometimes wraps JSON in."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = text.split("\n", 1)[-1]
        # Remove closing fence
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()

def _rule_based_fallback(description: str) -> dict:
    text = description.lower()
    category = "other"
    issue_type = "other"
    severity = "medium"
    
    # 1. Electricity (run first to avoid broad road match on streetlight)
    if any(k in text for k in [
        "wire", "spark", "wiring", "sparking", "live wire", "hanging wire",
        "transformer", "voltage", "short circuit", "electric", "electricity",
        "light", "streetlight", "power", "outage", "street light", "lamp post"
    ]):
        category = "electricity"
        issue_type = "streetlight_failure"
        if any(k in text for k in ["spark", "hanging wire", "live wire", "short circuit"]):
            severity = "critical"
    # 2. Water
    elif any(k in text for k in ["water", "pipe", "leak", "burst", "flooding"]):
        category = "water"
        issue_type = "pipe_leakage"
        if "flood" in text or "burst" in text:
            severity = "critical"
    # 3. Sanitation
    elif any(k in text for k in ["garbage", "waste", "trash", "dump", "litter"]):
        category = "sanitation"
        issue_type = "garbage_dump"
        if "toxic" in text or "stink" in text:
            severity = "high"
    # 4. Drainage
    elif any(k in text for k in ["drain", "flood", "sewage", "overflow", "nala"]):
        category = "drainage"
        issue_type = "drain_overflow"
        if "overflow" in text or "sewage" in text:
            severity = "high"
    # 5. Road (broad checks at the end)
    elif any(k in text for k in ["pothole", "road", "crack", "asphalt", "street"]):
        category = "road"
        issue_type = "pothole"
        if "critical" in text or "accident" in text or "crater" in text:
            severity = "high"
            
    department = CATEGORY_TO_DEPT.get(category, "roads")
    
    return {
        "category": category,
        "type": issue_type,
        "severity": severity,
        "department": department,
        "confidence": 0.75,
        "confidence_type": "heuristic",
        "provider": "rule_based",
        "ai_available": False
    }

def analyze_complaint_text(description: str) -> dict:
    """
    Returns: category, type, severity, department, confidence
    Falls back to rule-based if Gemini fails or is not configured.
    """
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        res = _rule_based_fallback(description)
        res["analyzed_at"] = datetime.utcnow()
        return res
        
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        
        prompt = f"""
        Analyze the following civic complaint description and output a JSON object containing:
        1. "category" (must be one of: "road", "water", "electricity", "sanitation", "drainage", "other")
        2. "type" (specific issue description, e.g. "pothole", "pipe_leakage", "streetlight_out")
        3. "severity" (must be one of: "low", "medium", "high", "critical")
        4. "department" (must be one of: "roads", "water_supply", "electrical", "sanitation", "drainage")
        5. "confidence" (float between 0.0 and 1.0)
        
        Complaint: "{description}"
        JSON:
        """
        t0 = time.time()
        response, used_model = _generate_content_with_model_fallback(genai, prompt, os.getenv("GEMINI_TEXT_MODEL", VISION_MODEL))
        dur = round((time.time() - t0) * 1000.0, 1)
        parsed = json.loads(_strip_json_fences(response.text))
        parsed["provider"] = "gemini"
        parsed["model"] = used_model
        parsed["ai_available"] = True
        parsed["confidence_type"] = "model_reported"
        parsed["analyzed_at"] = datetime.utcnow()
        log_ai_call("classification", "gemini", True, parsed.get("confidence", 0.9), dur)
        return parsed
    except Exception as e:
        print(f"[AI Service] Gemini error: {e}. Falling back to rules.")
        log_ai_call("classification", "gemini", False, 0.0, 0.0, str(e))
        res = _rule_based_fallback(description)
        res["provider"] = "rule_based"
        res["ai_available"] = False
        res["analyzed_at"] = datetime.utcnow()
        return res

def analyze_complaint_image(image_path: str) -> dict:
    """
    Returns a structured image result. An unavailable provider is explicit;
    this function never claims to have analyzed an image it did not inspect.
    """
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {
            "available": False,
            "status": "unavailable",
            "provider": "gemini",
            "model": VISION_MODEL,
            "reason": "Vision model unavailable because GEMINI_API_KEY is not configured.",
            "detected_issues": [],
            "image_detections": [],
            "detected_features": [],
            "hazards": [],
            "analyzed_at": datetime.utcnow()
        }

    try:
        import google.generativeai as genai
        from PIL import Image
        genai.configure(api_key=key)

        with Image.open(image_path) as img:
            prompt = """
            Analyze this civic issue image and return JSON only with these fields:
            "issue_type": a concise supported issue type such as pothole, road_surface_damage,
            garbage_dump, drain_overflow, pipe_leakage, streetlight_failure, fallen_tree, or other,
            "category": one of road, water, electricity, sanitation, drainage, noise, other,
            "severity": one of low, medium, high, critical,
            "confidence": a model-reported float from 0.0 to 1.0,
            "reason": one concise evidence-based explanation,
            "detected_features": list of visible features,
            "hazards": list of visible safety hazards.
            Do not infer details that are not visible.
            """
            t0 = time.time()
            response, used_model = _generate_content_with_model_fallback(genai, [prompt, img], VISION_MODEL)
            dur = round((time.time() - t0) * 1000.0, 1)
        parsed = json.loads(_strip_json_fences(response.text))
        category = _normalize_category(parsed.get("category"))
        issue_type = str(parsed.get("issue_type") or parsed.get("type") or "other").strip().lower()
        severity = _normalize_severity(parsed.get("severity"))
        confidence = float(parsed["confidence"])
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Vision model returned confidence outside 0.0-1.0")
        result = {
            "available": True,
            "status": "analyzed",
            "provider": "gemini",
            "model": used_model,
            "issue_type": issue_type,
            "type": issue_type,
            "category": category,
            "severity": severity,
            "department": CATEGORY_TO_DEPT.get(category, "roads"),
            "department_source": "category_mapping",
            "confidence": confidence,
            "confidence_type": "model_reported",
            "reason": str(parsed.get("reason") or "Visual evidence analyzed by the vision model.").strip(),
            "detected_features": parsed.get("detected_features") or [],
            "hazards": parsed.get("hazards") or [],
            "detected_issues": [issue_type],
            "image_detections": [issue_type],
            "analyzed_at": datetime.utcnow()
        }
        log_ai_call("image_classification", "gemini", True, confidence, dur)
        return result
    except Exception as e:
        log_ai_call("image_classification", "gemini", False, 0.0, 0.0, str(e))
        return {
            "available": False,
            "status": "unavailable",
            "provider": "gemini",
            "model": VISION_MODEL,
            "reason": f"Vision model unavailable: {type(e).__name__}.",
            "detected_issues": [],
            "image_detections": [],
            "detected_features": [],
            "hazards": [],
            "analyzed_at": datetime.utcnow()
        }

def fuse_complaint_predictions(text_analysis: dict, image_analysis: dict = None) -> dict:
    """Combine text and vision results while retaining both source analyses."""
    text = dict(text_analysis or {})
    text_category = _normalize_category(text.get("category"))
    text_type = str(text.get("type") or "other").strip().lower()
    text_severity = _normalize_severity(text.get("severity"))
    image = image_analysis if image_analysis and image_analysis.get("available") else None
    disagreement = False

    if image:
        image_category = _normalize_category(image.get("category"))
        image_type = str(image.get("issue_type") or image.get("type") or "other").strip().lower()
        image_severity = _normalize_severity(image.get("severity"))
        disagreement = image_category != text_category and text_category != "other" and image_category != "other"
        image_conf = float(image.get("confidence", 0.0))
        text_conf = float(text.get("confidence", 0.0))
        if image_conf >= max(0.7, text_conf):
            category, issue_type = image_category, image_type
        else:
            category, issue_type = text_category, text_type
        severity_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        severity = image_severity if severity_order[image_severity] >= severity_order[text_severity] else text_severity
        confidence = round(min(1.0, (image_conf * 0.65) + (text_conf * 0.35)), 3)
        confidence_type = "model_reported_fusion"
        reason = _prediction_explanation({"type": issue_type, "category": category, "severity": severity}, image, disagreement)
    else:
        category, issue_type, severity = text_category, text_type, text_severity
        confidence = text.get("confidence", 0.0)
        confidence_type = text.get("confidence_type", "heuristic")
        reason = _prediction_explanation({"type": issue_type, "category": category, "severity": severity})

    return {
        "type": issue_type,
        "issue_type": issue_type,
        "category": category,
        "severity": severity,
        "department": CATEGORY_TO_DEPT.get(category, "roads"),
        "department_source": "category_mapping",
        "confidence": confidence,
        "confidence_type": confidence_type,
        "reason": reason,
        "prediction_disagreement": disagreement,
        "image_analysis_available": bool(image)
    }

def analyze_text(description: str) -> dict:
    return analyze_complaint_text(description)

def analyze_image(image_path: str) -> dict:
    from ml.yolo_runner import run_yolo_inference
    yolo_res = run_yolo_inference(image_path)
    if yolo_res.get("available"):
        return yolo_res
    # Fallback to vision model or return unavailable
    vision_res = analyze_complaint_image(image_path)
    if vision_res.get("available"):
        return {
            "available": True,
            "issue_type": vision_res.get("issue_type"),
            "category": vision_res.get("category"),
            "severity": vision_res.get("severity"),
            "confidence": vision_res.get("confidence"),
            "confidence_type": vision_res.get("confidence_type"),
            "explanation": vision_res.get("reason")
        }
    return {
        "available": False,
        "reason": vision_res.get("reason", "Image model unavailable.")
    }

def fuse_predictions(text_result: dict, image_result: dict) -> dict:
    fused = fuse_complaint_predictions(text_result, image_result)
    fused["fusion_method"] = "image_weighted" if image_result and image_result.get("available") else "text_only"
    return fused

def validate_prediction(prediction: dict) -> bool:
    if not isinstance(prediction, dict):
        return False
    required = ["category", "severity"]
    if not all(k in prediction for k in required):
        return False
    if prediction.get("severity") not in {"low", "medium", "high", "critical"}:
        return False
    conf = prediction.get("confidence")
    if conf is not None and not (0.0 <= float(conf) <= 1.0):
        return False
    return True

def detect_duplicates(issue_id: str, description: str, location: dict) -> list:
    """
    Returns: list of candidate issue_ids that may be duplicates, with similarity scores.
    Uses simple geospatial proximity + keyword overlap similarity.
    """
    from app import db
    try:
        coords = location.get("coordinates", [0.0, 0.0])
        lng, lat = coords[0], coords[1]
    except Exception:
        return []
        
    query_ne = {"$ne": ObjectId(issue_id)} if ObjectId.is_valid(issue_id) else {"$ne": issue_id}
    candidates = list(db.issues.find({
        "_id": query_ne,
        "status": {"$nin": ["closed", "rejected"]}
    }))
    
    duplicates = []
    
    def calculate_distance(lat1, lon1, lat2, lon2):
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c
        
    desc_words = set(description.lower().split())
    
    for c in candidates:
        c_coords = c.get("location", {}).get("coordinates", [0.0, 0.0])
        c_lng, c_lat = c_coords[0], c_coords[1]
        
        distance = calculate_distance(lat, lng, c_lat, c_lng)
        if distance < 0.2: # within 200m
            c_words = set(c.get("description", "").lower().split())
            intersection = desc_words.intersection(c_words)
            union = desc_words.union(c_words)
            text_sim = len(intersection) / max(len(union), 1)
            
            geo_sim = max(0.0, 1.0 - (distance / 0.2))
            combined_sim = (geo_sim * 0.7) + (text_sim * 0.3)
            if distance < 0.05: # within 50m
                combined_sim = max(0.88, combined_sim)
                
            if combined_sim >= 0.6:
                duplicates.append({
                    "issue_id": c.get("issue_id") or str(c["_id"]),
                    "similarity": round(combined_sim, 2),
                    "distance_km": round(distance, 3)
                })
                
    return sorted(duplicates, key=lambda x: x["similarity"], reverse=True)

def verify_resolution(before_image_path: str, after_image_path: str, issue_type: str) -> dict:
    """
    Returns: status (verified / likely_verified / uncertain / not_verified), confidence, reasoning
    Uses Gemini Vision to compare before/after photos.
    Note: gemini-pro-vision is deprecated in modern Gemini APIs; use gemini-1.5-flash for new implementations.
    """
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {
            "status": "uncertain",
            "available": False,
            "confidence": 0.0,
            "reasoning": "Vision model unavailable; resolution requires human verification.",
            "provider": "gemini",
            "model": VISION_MODEL
        }
        
    try:
        import google.generativeai as genai
        from PIL import Image
        genai.configure(api_key=key)
        
        img_before = Image.open(before_image_path)
        img_after = Image.open(after_image_path)
        prompt = f"""
        Compare these two photos representing a before and after state of a resolved issue: "{issue_type}".
        Verify if the issue has been successfully resolved/fixed.
        Return JSON with:
        "status": "verified", "likely_verified", "uncertain", or "not_verified",
        "confidence": float 0.0 to 1.0,
        "reasoning": "explain your decision in one sentence"
        """
        response, used_model = _generate_content_with_model_fallback(genai, [prompt, img_before, img_after], VISION_MODEL)
        parsed = json.loads(_strip_json_fences(response.text))
        parsed["provider"] = "gemini"
        parsed["model"] = VISION_MODEL
        parsed["available"] = True
        return parsed
    except Exception as e:
        print(f"[AI Service] Gemini resolution verification error: {e}")
        return {
            "status": "uncertain",
            "available": False,
            "confidence": 0.0,
            "reasoning": "Vision model unavailable; resolution requires human verification.",
            "provider": "gemini",
            "model": VISION_MODEL
        }

verify_repair_with_images = verify_resolution

def recommend_department(category: str, issue_type: str, description: str) -> dict:
    """
    Returns: department, confidence
    """
    dept = CATEGORY_TO_DEPT.get(category.lower().strip(), "roads")
    return {
        "department": dept,
        "confidence": 0.90
    }

def detect_and_translate(text: str) -> dict:
    """
    Detects language and translates Indic languages to English.
    """
    if not text or text.strip() == "":
        return {
            "original_text": "",
            "detected_language": "english",
            "translated_text": "",
            "confidence": 1.0
        }
        
    key = os.getenv("GEMINI_API_KEY")
    if key:
        try:
            import google.generativeai as genai
            import json
            genai.configure(api_key=key)
            prompt = f"""
            Analyze the following text from a civic complaint:
            "{text}"
            
            Identify if it is in English, Kannada, Hindi, Tamil, or Telugu.
            Translate the text to English if it is not in English.
            Return a JSON object exactly with these fields:
            "detected_language": "kannada" | "hindi" | "tamil" | "telugu" | "english" | "other",
            "translated_text": "the translated text in English",
            "confidence": float 0.0 to 1.0
            """
            response, used_model = _generate_content_with_model_fallback(genai, prompt, VISION_MODEL)
            parsed = json.loads(_strip_json_fences(response.text))
            return {
                "original_text": text,
                "detected_language": parsed.get("detected_language", "unknown"),
                "translated_text": parsed.get("translated_text", text),
                "confidence": float(parsed.get("confidence", 0.0))
            }
        except Exception as e:
            print(f"[AI Service] Gemini detect_and_translate exception: {e}")
            
    # Simple rule-based keyword language detector fallback
    lang = "english"
    has_kannada = any('\u0c80' <= char <= '\u0cff' for char in text)
    has_hindi = any('\u0900' <= char <= '\u097f' for char in text)
    has_tamil = any('\u0b80' <= char <= '\u0bff' for char in text)
    has_telugu = any('\u0c00' <= char <= '\u0c7f' for char in text)
    
    if has_kannada:
        lang = "kannada"
    elif has_hindi:
        lang = "hindi"
    elif has_tamil:
        lang = "tamil"
    elif has_telugu:
        lang = "telugu"
        
    return {
        "original_text": text,
        "detected_language": lang,
        "translated_text": text,
        "confidence": 0.50
    }

def generate_officer_briefing(stats: dict) -> str:
    """
    Takes pre-computed stats dict and asks Gemini to produce a concise
    natural-language briefing (max 150 words).
    """
    key = os.getenv("GEMINI_API_KEY")
    if key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            prompt = f"""
            Synthesize a brief, professional daily briefing (maximum 150 words) for the on-duty civic officer based on these metrics:
            - Active emergencies: {stats.get('emergency_count', 0)}
            - SLA breaches: {stats.get('sla_breached_count', 0)}
            - SLA warning issues: {stats.get('sla_warning_count', 0)}
            - Available field workers: {stats.get('available_workers', 0)}
            - Pending assignments: {stats.get('pending_assignments', 0)}
            - Top duplicate cluster details: {stats.get('top_cluster_summary', 'None')}
            
            Focus on immediate priorities, resource coordination, and urgent recommendations.
            """
            response, used_model = _generate_content_with_model_fallback(genai, prompt, VISION_MODEL)
            return response.text.strip()
        except Exception as e:
            print(f"[AI Service] Gemini generate_officer_briefing exception: {e}")
            
    # Professional fallback briefing text builder
    emergencies = stats.get('emergency_count', 0)
    breached = stats.get('sla_breached_count', 0)
    warning = stats.get('sla_warning_count', 0)
    workers = stats.get('available_workers', 0)
    pending = stats.get('pending_assignments', 0)
    
    briefing = f"Good day, Officer. Today's report highlights {emergencies} active emergency situations requiring immediate dispatch. "
    briefing += f"There are currently {breached} complaints that have breached their SLA timeline and {warning} issues approaching breach thresholds. "
    briefing += f"With {workers} crew members available and {pending} assignments pending, we recommend prioritizing the emergency queue and assigning workers to overdue tasks."
    return briefing

def parse_search_query(query: str) -> dict:
    """
    Uses Gemini or local regex-keyword fallback heuristics to parse NL search query filters.
    """
    if not query or query.strip() == "":
        return {}
        
    key = os.getenv("GEMINI_API_KEY")
    if key:
        try:
            import google.generativeai as genai
            import json
            genai.configure(api_key=key)
            prompt = f"""
            Analyze this natural language search query for civic issues:
            "{query}"
            
            Convert it to key-value attributes for database filters.
            Return a JSON object exactly with these fields (use null if not mentioned):
            "category": "road" | "water" | "electricity" | "sanitation" | "drainage" | null,
            "type": string | null,
            "severity": "critical" | "high" | "medium" | "low" | null,
            "ward": string | null,
            "min_age_hours": integer | null,
            "status": "submitted" | "ai_reviewed" | "officer_reviewed" | "assigned" | "work_started" | "work_completed" | "closed" | "reopened" | null,
            "department": "roads" | "water_supply" | "electrical" | "sanitation" | "drainage" | null
            """
            response, used_model = _generate_content_with_model_fallback(genai, prompt, VISION_MODEL)
            parsed = json.loads(_strip_json_fences(response.text))
            res = {k: v for k, v in parsed.items() if v is not None}
            if "ward" in res and res["ward"]:
                ward_val = str(res["ward"]).strip()
                if not ward_val.lower().startswith("ward"):
                    res["ward"] = f"Ward {ward_val.capitalize()}"
            return res
        except Exception as e:
            print(f"[AI Service] Gemini parse_search_query exception: {e}")
            
    # Local keyword heuristics fallback parser
    filters = {}
    lower_query = query.lower()
    
    if "road" in lower_query or "pothole" in lower_query or "street" in lower_query:
        filters["category"] = "road"
    elif "water" in lower_query or "leak" in lower_query:
        filters["category"] = "water"
    elif "electricity" in lower_query or "wire" in lower_query or "light" in lower_query:
        filters["category"] = "electricity"
    elif "sanitation" in lower_query or "garbage" in lower_query or "waste" in lower_query:
        filters["category"] = "sanitation"
    elif "drain" in lower_query or "sewage" in lower_query or "overflow" in lower_query:
        filters["category"] = "drainage"
        
    if "critical" in lower_query or "emergency" in lower_query:
        filters["severity"] = "critical"
    elif "high" in lower_query or "urgent" in lower_query:
        filters["severity"] = "high"
    elif "medium" in lower_query:
        filters["severity"] = "medium"
    elif "low" in lower_query:
        filters["severity"] = "low"
        
    for st in ["submitted", "assigned", "closed", "reopened"]:
        if st in lower_query:
            filters["status"] = st
    if "work completed" in lower_query or "resolved" in lower_query:
        filters["status"] = "work_completed"
        
    import re
    ward_match = re.search(r"ward\s*(\w+)", lower_query)
    if ward_match:
        ward_num = ward_match.group(1)
        filters["ward"] = f"Ward {ward_num.capitalize()}"
        
    age_match = re.search(r"(\d+)\s*(day|hour)", lower_query)
    if age_match:
        val = int(age_match.group(1))
        unit = age_match.group(2)
        if "day" in unit:
            filters["min_age_hours"] = val * 24
        else:
            filters["min_age_hours"] = val
            
    return filters

def answer_analytics_question(question: str, context_stats: dict) -> str:
    """
    Takes a plain English question and pre-computed context stats.
    Asks Gemini to produce a concise answer (max 100 words) grounded in the stats.
    Fallback: return a template string built from the stats if Gemini fails.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    
    prompt = (
        f"You are the SmartCivic+ AI analytics assistant.\n"
        f"Analyze this city status data: {context_stats}\n"
        f"Based strictly on this data, answer this question in 100 words or less:\n"
        f"\"{question}\"\n"
        f"Be direct, precise, and numerical."
    )
    
    if api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            response, used_model = _generate_content_with_model_fallback(genai, prompt, VISION_MODEL)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"[AI Service] Gemini question answer error: {e}. Using fallback.")
            
    total = context_stats.get("total_issues_matched", 0)
    ward = context_stats.get("ward", "the city")
    category = context_stats.get("category", "all")
    status = context_stats.get("status", "any")
    
    return f"There are currently {total} complaints matching your query for category '{category}' and status '{status}' in {ward}. Check details in dashboard graphs."
