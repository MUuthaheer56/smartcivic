# db.votes schema representation:
# {
#   _id: ObjectId,
#   issue_id: ObjectId,
#   voter_id: ObjectId,
#   vote_type: str("confirm"|"deny"),
#   severity_vote: int(1-5),
#   timestamp: datetime
# }

def create_vote_doc(issue_id, voter_id, vote_type, severity_vote):
    from datetime import datetime
    from bson import ObjectId
    return {
        "issue_id": ObjectId(issue_id),
        "voter_id": ObjectId(voter_id),
        "vote_type": vote_type,
        "severity_vote": int(severity_vote),
        "timestamp": datetime.utcnow()
    }
