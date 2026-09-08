"""
SmartCivic — Status Machine Unit Tests
Tests transition constraints across complaint lifecycle states.
"""
import unittest
from utils.validators import validate_status_transition, ValidationError

class TestStatusMachine(unittest.TestCase):
    def test_submitted_to_verified_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_status_transition("submitted", "verified")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_resolved_to_submitted_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_status_transition("resolved", "submitted")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_in_progress_to_resolved_accepted(self):
        try:
            validate_status_transition("in_progress", "resolved")
        except ValidationError:
            self.fail("validate_status_transition raised ValidationError unexpectedly for in_progress -> resolved")

if __name__ == "__main__":
    unittest.main()
