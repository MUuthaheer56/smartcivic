import unittest
import sys
import os

# Ensure the root folder is in sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'services')))

from security_service import (
    hash_password, verify_password, create_access_token,
    decode_access_token, sanitize_input, check_rate_limit
)
from upload_service import validate_and_sanitize_image
from routing_service import RoutingService

class TestSmartCivicCore(unittest.TestCase):

    def test_password_hashing_and_verification(self):
        pwd = "ComplexPassword@2026"
        hashed = hash_password(pwd)
        self.assertTrue(verify_password(hashed, pwd))
        self.assertFalse(verify_password(hashed, "WrongPassword"))

    def test_jwt_token_claims_and_expiration(self):
        token = create_access_token("usr-123", "WORKER", "worker@civic.gov")
        claims = decode_access_token(token)
        self.assertEqual(claims["sub"], "usr-123")
        self.assertEqual(claims["role"], "WORKER")

    def test_xss_input_sanitization(self):
        raw = '<script>alert("xss")</script>Open Pothole on Main St & 4th Ave'
        sanitized = sanitize_input(raw)
        self.assertNotIn("<script>", sanitized)
        self.assertIn("Open Pothole on Main St &amp; 4th Ave", sanitized)

    def test_rate_limiter(self):
        ip = "192.0.2.1"
        for _ in range(5):
            allowed = check_rate_limit(ip, max_requests=5, window_seconds=60)
            self.assertTrue(allowed)
        # 6th request must be blocked
        blocked = check_rate_limit(ip, max_requests=5, window_seconds=60)
        self.assertFalse(blocked)

    def test_upload_magic_byte_validation(self):
        # Valid PNG magic bytes
        valid_png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
        clean, filename = validate_and_sanitize_image(valid_png, "test.png")
        self.assertTrue(filename.endswith(".png"))

        # Executable disguised as JPG
        fake_jpg = b'MZ\x90\x00' + b'\x00' * 50
        with self.assertRaises(ValueError):
            validate_and_sanitize_image(fake_jpg, "malicious.jpg")

    def test_osrm_road_routing_valid_coordinates(self):
        # Bengaluru City Center to Indiranagar
        origin = (12.9716, 77.5946)
        dest = (12.9784, 77.6408)
        route = RoutingService.get_road_route(origin, dest)
        self.assertIn(route["status"], ["SUCCESS", "FALLBACK_OFFLINE"])
        self.assertGreater(route["distance_meters"], 1000)
        self.assertGreater(route["eta_minutes"], 0)

if __name__ == "__main__":
    unittest.main()
