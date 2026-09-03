try:
    from transformers import pipeline
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False

# Mapping of categories and subcategories
CIVIC_TAXONOMY = {
    "road damage": ["pothole", "longitudinal crack", "transverse crack", "alligator crack"],
    "waste management": ["garbage overflow", "illegal dumping"],
    "electricity": ["streetlight outage", "hanging wire"],
    "water utility": ["pipeline leak", "water shortage"],
    "sewage": ["drainage overflow", "sewer blockage"]
}

def classify_complaint_text(description: str) -> dict:
    """
    NLP auto-tagger suggesting complaint category/subcategory based on text description.
    """
    desc_lower = description.lower()
    
    if HAS_TRANSFORMERS:
        try:
            # Zero-shot classification pipeline
            classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")
            categories = list(CIVIC_TAXONOMY.keys())
            res = classifier(description, candidate_labels=categories)
            
            best_cat = res['labels'][0]
            confidence = res['scores'][0]
            
            # Find best matching subcategory
            subcategories = CIVIC_TAXONOMY[best_cat]
            sub_res = classifier(description, candidate_labels=subcategories)
            best_sub = sub_res['labels'][0]
            
            return {
                "category": best_cat,
                "subcategory": best_sub,
                "confidence": round(confidence, 3)
            }
        except Exception as e:
            print(f"[Transformers] Classification error: {e}. Using baseline keyword matching.")

    # Baseline rule engine
    category = "other"
    subcategory = "other"
    confidence = 0.50
    
    # 1. Road damage check
    if any(w in desc_lower for w in ["hole", "pothole", "road", "crack", "asphalt", "pavement"]):
        category = "road damage"
        subcategory = "pothole"
        if "crack" in desc_lower:
            subcategory = "alligator crack"
        confidence = 0.88
        
    # 2. Waste check
    elif any(w in desc_lower for w in ["garbage", "trash", "dump", "litter", "waste", "bin"]):
        category = "waste management"
        subcategory = "garbage overflow"
        confidence = 0.92
        
    # 3. Water utility check
    elif any(w in desc_lower for w in ["water", "leak", "pipe", "burst"]):
        category = "water utility"
        subcategory = "pipeline leak"
        confidence = 0.85
        
    # 4. Sewage check
    elif any(w in desc_lower for w in ["sewage", "sewer", "drain", "stink", "clog"]):
        category = "sewage"
        subcategory = "drainage overflow"
        confidence = 0.87
        
    # 5. Electricity check
    elif any(w in desc_lower for w in ["light", "street", "electricity", "dark", "wire"]):
        category = "electricity"
        subcategory = "streetlight outage"
        confidence = 0.89

    return {
        "category": category,
        "subcategory": subcategory,
        "confidence": confidence
    }
