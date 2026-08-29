from datetime import datetime, timedelta
from bson import ObjectId

def compute_ward_trust_scores(db) -> list:
    # Get distinct wards, fallback to community_id if ward is not present
    wards = db.issues.distinct("ward")
    fallback_community = False
    if not wards or None in wards:
        wards = [str(cid) for cid in db.issues.distinct("community_id") if cid]
        fallback_community = True
        
    scores = []

    for ward in wards:
        if not ward:
            continue

        now = datetime.utcnow()
        month_ago = now - timedelta(days=30)
        quarter_ago = now - timedelta(days=90)

        def ward_q(extra={}):
            if fallback_community:
                return {"community_id": ObjectId(ward), **extra}
            return {"ward": ward, **extra}

        total = db.issues.count_documents(ward_q({"created_at": {"$gte": month_ago}}))
        if total == 0:
            continue

        # Component 1: Response rate
        # First response is when status is not pending_validation anymore
        acknowledged = db.issues.count_documents(ward_q({
            "created_at": {"$gte": month_ago},
            "status": {"$ne": "pending_validation"},
            "validated_at": {"$exists": True},
            "$expr": {
                "$lte": [
                    {"$subtract": ["$validated_at", "$created_at"]},
                    86400000  # 24h in ms
                ]
            }
        }))
        response_rate = acknowledged / total if total > 0 else 1.0

        # Component 2: AI-verified resolution quality
        resolved = db.issues.count_documents(ward_q({
            "created_at": {"$gte": month_ago},
            "status": {"$in": ["resolved", "verified"]}
        }))
        # In mock flow, PASS / True works
        ai_verified = db.issues.count_documents(ward_q({
            "created_at": {"$gte": month_ago},
            "repair_verified": True
        }))
        resolution_quality = (ai_verified / resolved) if resolved > 0 else 0.5

        # Component 3: SLA compliance
        sla_met = db.issues.count_documents(ward_q({
            "created_at": {"$gte": month_ago},
            "sla_breached": {"$ne": True},
            "status": {"$in": ["resolved", "verified"]}
        }))
        sla_rate = (sla_met / resolved) if resolved > 0 else 0.5

        # Component 4: Recurrence (inverse)
        reopened = db.issues.count_documents(ward_q({
            "created_at": {"$gte": month_ago},
            "status": "reopened"
        }))
        recurrence_rate = reopened / total if total > 0 else 0.0
        recurrence_score = max(0.0, min(1.0, 1.0 - recurrence_rate * 3.0))

        # Component 5: Filing trend
        this_month = total
        prev_quarter_avg = db.issues.count_documents(
            ward_q({"created_at": {"$gte": quarter_ago, "$lt": month_ago}})
        ) / 2.0  # 2-month average
        if prev_quarter_avg > 0:
            trend_ratio = this_month / prev_quarter_avg
            trend_score = min(1.0, trend_ratio)
        else:
            trend_score = 0.5

        trust_score = (
            response_rate      * 30.0 +
            resolution_quality * 30.0 +
            sla_rate           * 20.0 +
            recurrence_score   * 100.0 * 0.10 +
            trend_score        * 100.0 * 0.10
        )

        if trust_score >= 75:
            trust_level = "HIGH"
        elif trust_score >= 50:
            trust_level = "MEDIUM"
        elif trust_score >= 30:
            trust_level = "LOW"
        else:
            trust_level = "CRITICAL"

        scores.append({
            "ward": ward,
            "trust_score": round(trust_score, 1),
            "trust_level": trust_level,
            "components": {
                "response_rate": round(response_rate * 100, 1),
                "resolution_quality": round(resolution_quality * 100, 1),
                "sla_compliance": round(sla_rate * 100, 1),
                "recurrence_score": round(recurrence_score * 100, 1),
                "filing_trend": round(trend_score * 100, 1)
            },
            "total_complaints": total,
            "computed_at": now
        })

    # save
    db.ward_trust_scores.delete_many({})
    if scores:
        db.ward_trust_scores.insert_many(scores)

    return sorted(scores, key=lambda x: x["trust_score"])
