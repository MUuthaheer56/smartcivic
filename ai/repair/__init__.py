from bson import ObjectId
from datetime import datetime

def verify_repair_performance(complaint_id: str, before_confidence: float, after_confidence: float) -> dict:
    """
    Compare before and after repair confidences to determine repair status.
    - Effective repair: after_confidence < 30% AND (before_confidence - after_confidence) > 50 percentage points
    """
    from app import db
    
    # Calculate confidence drop in percentage points
    confidence_drop = before_confidence - after_confidence
    
    # Decision rule
    is_verified = (after_confidence < 0.30) and (confidence_drop >= 0.50)
    result = "VERIFIED" if is_verified else "FAILED"
    
    # Record verification in database
    verification_doc = {
        "complaint_id": ObjectId(complaint_id),
        "before_confidence": round(before_confidence, 3),
        "after_confidence": round(after_confidence, 3),
        "severity_change": round((after_confidence - before_confidence) * 10, 1),
        "result": result,
        "created_at": datetime.utcnow()
    }
    
    db.repair_verification.insert_one(verification_doc)
    
    # Update issue state in DB
    db.issues.update_one(
        {'_id': ObjectId(complaint_id)},
        {
            '$set': {
                'repair_verified': is_verified,
                'status': 'resolved' if is_verified else 'in_progress'
            },
            '$push': {
                'status_history': {
                    'status': 'resolved' if is_verified else 'in_progress',
                    'changed_by': None,
                    'timestamp': datetime.utcnow(),
                    'note': f"AI Repair Verification: {result}. (Before: {before_confidence:.1%}, After: {after_confidence:.1%})"
                }
            }
        }
    )
    
    return {
        "result": result,
        "before_confidence": before_confidence,
        "after_confidence": after_confidence,
        "confidence_drop": confidence_drop
    }
