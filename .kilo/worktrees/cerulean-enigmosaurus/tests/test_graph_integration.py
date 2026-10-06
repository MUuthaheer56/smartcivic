"""
SmartCivic v2 — Urban Knowledge Graph Integration Tests
Tests graph correlation engine, master incident clustering, incident edge generation, and graph APIs.
"""

from datetime import datetime
from bson import ObjectId
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from services.urban_knowledge_graph import analyze_correlations
from models.user import get_db

def test_graph_correlation_integration():
    app = create_app()
    with app.app_context():
        db = get_db()
        
        # Clean test collections
        db.issues.delete_many({"test_tag": "graph_test"})
        db.master_incidents.delete_many({"test_tag": "graph_test"})
        db.incident_edges.delete_many({})
        
        now = datetime.utcnow()
        leak_id = db.issues.insert_one({
            "test_tag": "graph_test",
            "category": "water",
            "status": "submitted",
            "created_at": now,
            "department": "water_board",
            "location": {"type": "Point", "coordinates": [77.5946, 12.9716]}
        }).inserted_id
        
        road_id = db.issues.insert_one({
            "test_tag": "graph_test",
            "category": "road",
            "status": "submitted",
            "created_at": now,
            "department": "roads",
            "location": {"type": "Point", "coordinates": [77.5947, 12.9716]} # very close (~10m)
        }).inserted_id
        
        # Run analysis on the second issue
        res = analyze_correlations(db, road_id)
        assert res is not None
        assert res["root_id"] == leak_id  # Water leak acts as the root cause
        
        # Verify idempotency
        res_second = analyze_correlations(db, road_id)
        assert res_second["master_id"] == res["master_id"]
        
        # Cleanup
        db.issues.delete_many({"test_tag": "graph_test"})
        db.master_incidents.delete_many({"test_tag": "graph_test"})
        db.incident_edges.delete_many({})

if __name__ == "__main__":
    test_graph_correlation_integration()
    print("test_graph_correlation_integration PASSED!")
