"""
SmartCivic AI — NLP Issue Classifier
Zero-shot keyword + heuristic scoring. No external ML library required.
Maps issue text → category + responsible department.
"""
from typing import Dict, List, Tuple
import re

# Extended keyword taxonomy with weights
CATEGORY_KEYWORDS: Dict[str, List[Tuple[str, float]]] = {
    "pothole": [
        ("pothole", 3.0), ("crater", 2.5), ("road damage", 2.5), ("broken road", 2.0),
        ("road hole", 2.0), ("bump", 1.5), ("tarmac", 1.5), ("asphalt", 1.5),
        ("road surface", 1.5), ("road crack", 1.5), ("pavement", 1.2)
    ],
    "garbage": [
        ("garbage", 3.0), ("waste", 2.5), ("trash", 2.5), ("dump", 2.0),
        ("litter", 2.0), ("rubbish", 2.0), ("overflowing bin", 2.5), ("solid waste", 2.0),
        ("decomposing", 1.8), ("smelly pile", 2.0), ("open dumping", 2.5)
    ],
    "streetlight": [
        ("streetlight", 3.0), ("street light", 3.0), ("lamp post", 2.5), ("dark lane", 2.5),
        ("no light", 2.0), ("bulb", 1.5), ("electrical", 1.5), ("light out", 2.0),
        ("led", 1.5), ("darkness", 1.8), ("power outage", 1.5)
    ],
    "water": [
        ("water", 2.0), ("pipe", 2.0), ("leak", 2.5), ("water shortage", 3.0),
        ("no water", 3.0), ("burst pipe", 3.0), ("water main", 2.5), ("tap dry", 2.5),
        ("water supply", 2.0), ("waterlogging", 2.0)
    ],
    "sewage": [
        ("sewage", 3.0), ("sewer", 3.0), ("drain overflow", 3.0), ("drainage", 2.5),
        ("stink", 2.0), ("smell", 1.8), ("manhole", 2.0), ("blockage", 2.0),
        ("clogged drain", 2.5), ("septic", 2.0)
    ],
    "noise": [
        ("noise", 3.0), ("loud", 2.5), ("sound", 1.8), ("music", 2.0),
        ("barking", 2.0), ("construction noise", 2.5), ("horn", 2.0), ("nuisance", 1.8),
        ("decibel", 2.0), ("disturbance", 1.8)
    ],
    "animals": [
        ("stray", 2.5), ("dog", 1.5), ("cow", 1.5), ("animal", 2.0),
        ("cattle", 2.0), ("stray animal", 3.0), ("biting", 2.5)
    ],
    "construction": [
        ("construction", 2.0), ("excavation", 2.5), ("digging", 2.0), ("work order", 1.5),
        ("building debris", 2.0), ("scaffolding", 1.8), ("unauthorized construction", 2.5)
    ]
}

DEPARTMENT_MAP: Dict[str, str] = {
    "pothole": "BBMP Road Engineering",
    "garbage": "BBMP Solid Waste Management",
    "streetlight": "BESCOM / BBMP Electrical",
    "water": "BWSSB Water Supply",
    "sewage": "BWSSB Drainage",
    "noise": "BBMP Enforcement",
    "animals": "BBMP Animal Husbandry",
    "construction": "BBMP Building Control",
    "other": "BBMP General Services"
}

URGENCY_KEYWORDS = ["urgent", "emergency", "danger", "hazard", "critical", "immediately",
                    "accident", "injury", "flooding", "collapsed", "burst"]


def _tokenize(text: str) -> str:
    return re.sub(r'[^a-z0-9 ]', ' ', text.lower())


def classify_issue(title: str, description: str = "") -> dict:
    """
    Classify an issue using weighted keyword scoring.
    
    Returns:
        {
            "category": str,
            "department": str,
            "confidence_score": float,   # 0.0 – 1.0
            "urgency_flag": bool,
            "top_matches": list          # top 3 [(category, score)]
        }
    """
    combined = _tokenize(f"{title} {description}")
    
    scores: Dict[str, float] = {}
    for category, kw_list in CATEGORY_KEYWORDS.items():
        score = 0.0
        for keyword, weight in kw_list:
            if keyword in combined:
                score += weight
        if score > 0:
            scores[category] = score

    urgency_flag = any(kw in combined for kw in URGENCY_KEYWORDS)

    if not scores:
        return {
            "category": "other",
            "department": DEPARTMENT_MAP["other"],
            "confidence_score": 0.0,
            "urgency_flag": urgency_flag,
            "top_matches": []
        }

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_category, top_score = sorted_scores[0]

    # Normalise confidence (cap at 10.0 raw for 1.0 confidence)
    confidence = min(1.0, top_score / 10.0)

    return {
        "category": top_category,
        "department": DEPARTMENT_MAP.get(top_category, DEPARTMENT_MAP["other"]),
        "confidence_score": round(confidence, 3),
        "urgency_flag": urgency_flag,
        "top_matches": [(cat, round(sc, 2)) for cat, sc in sorted_scores[:3]]
    }
