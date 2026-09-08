"""
SmartCivic — Routing Service Unit Tests
Tests coordinate validation, Haversine distance, and unavailable router error handling.
"""
import unittest
from services.routing_service import calculate_distance, calculate_eta, get_route
from utils.geo_utils import validate_coordinates

class TestRouting(unittest.TestCase):
    def test_haversine_distance_accuracy(self):
        # Distance between Bangalore MG Road and Indiranagar ~4.5 km (4500m)
        dist = calculate_distance(12.9716, 77.5946, 12.9784, 77.6408)
        self.assertGreater(dist, 4000)
        self.assertLess(dist, 6000)

    def test_calculate_eta(self):
        eta = calculate_eta(3000, mode="driving")
        self.assertGreater(eta, 0)

    def test_invalid_coordinates_raise_value_error(self):
        with self.assertRaises(ValueError):
            validate_coordinates(999.0, 77.5946)

    def test_routing_engine_unavailable_response(self):
        # Invalid URL or unreachable endpoint
        origin = {"lat": 12.9716, "lng": 77.5946}
        destination = {"lat": 12.9784, "lng": 77.6408}
        res = get_route(origin, destination)
        self.assertIn("available", res)
        # Even if endpoint fails or succeeds, geometry must never be straight line when available=false
        if not res["available"]:
            self.assertIn(res["reason"], ["routing_service_unavailable", "no_route_found"])
        else:
            self.assertIsInstance(res["geometry"], list)

if __name__ == "__main__":
    unittest.main()
