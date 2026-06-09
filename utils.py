from bson import ObjectId
from datetime import datetime

def serialize(obj):
    if isinstance(obj, list): return [serialize(i) for i in obj]
    if isinstance(obj, dict): return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, ObjectId): return str(obj)
    if isinstance(obj, datetime): return obj.isoformat()
    return obj
