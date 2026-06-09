import unittest
from datetime import datetime, timedelta
from bson import ObjectId

# Import parts to test
from utils import serialize
from services.auth_service import hash_password, check_password
from services.sla_service import get_sla_deadline, get_sla_status
from services.route_optimizer import optimize_route, haversine

class SmartCivicUnitTest(unittest.TestCase):
    
    def test_serialization(self):
        obj_id = ObjectId("660000000000000000000001")
        dt = datetime(2026, 5, 23, 12, 0, 0)
        raw_dict = {
            '_id': obj_id,
            'title': 'Test Issue',
            'created_at': dt,
            'tags': ['a', 'b'],
            'nested': {
                'id': obj_id
            }
        }
        
        serialized = serialize(raw_dict)
        
        self.assertEqual(serialized['_id'], str(obj_id))
        self.assertEqual(serialized['created_at'], dt.isoformat())
        self.assertEqual(serialized['nested']['id'], str(obj_id))
        self.assertEqual(serialized['tags'], ['a', 'b'])

    def test_auth_hashing(self):
        pwd = "testpassword123"
        hashed = hash_password(pwd)
        
        self.assertTrue(check_password(pwd, hashed))
        self.assertFalse(check_password("wrongpassword", hashed))

    def test_sla_computations(self):
        created = datetime.utcnow()
        
        # Pothole: 7 days
        deadline_pothole = get_sla_deadline('pothole', created)
        self.assertEqual(deadline_pothole, created + timedelta(days=7))
        
        # Water: 1 day
        deadline_water = get_sla_deadline('water', created)
        self.assertEqual(deadline_water, created + timedelta(days=1))
        
        # SLA status
        issue = {
            'created_at': created,
            'sla_deadline': created + timedelta(days=2),
            'category': 'garbage',
            'sla_breached': False
        }
        
        status = get_sla_status(issue)
        self.assertEqual(status['sla_days'], 2)
        self.assertFalse(status['is_overdue'])

    def test_route_optimizer(self):
        # Coordinates of Bengaluru Koramangala
        worker_lat = 12.9352
        worker_lng = 77.6245
        
        issues = [
            {
                '_id': ObjectId("660000000000000000000010"),
                'lat': 12.9348,
                'lng': 77.6255,
                'title': 'Issue 1',
                'severity': 3,
                'category': 'pothole',
                'address': 'Location 1'
            },
            {
                '_id': ObjectId("660000000000000000000011"),
                'lat': 12.9360,
                'lng': 77.6230,
                'title': 'Issue 2',
                'severity': 5,
                'category': 'garbage',
                'address': 'Location 2'
            }
        ]
        
        route = optimize_route(worker_lat, worker_lng, issues)
        
        self.assertIn('ordered_issue_ids', route)
        self.assertIn('waypoints', route)
        self.assertEqual(len(route['waypoints']), 3) # including depot starting point
        self.assertTrue(route['total_distance_km'] >= 0.0)

if __name__ == '__main__':
    unittest.main()
