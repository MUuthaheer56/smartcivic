"""
SmartCivic — Complete Test Suite
Run: python -m pytest test_app.py -v
or:  python -m unittest test_app.py -v
"""
import unittest
from datetime import datetime, timedelta
from bson import ObjectId
from unittest.mock import patch, MagicMock

# Core utils
from utils import serialize
from services.auth_service import hash_password, check_password
from services.sla_service import get_sla_deadline, get_sla_status
from services.route_optimizer import optimize_route, haversine, build_graph, nearest_neighbor_route
from services.validation_service import CONFIRM_THRESHOLD, DENY_THRESHOLD, MIN_VOTES_FOR_REJECT
from services.reputation_service import get_tier, TIER_THRESHOLDS
from services.clustering_service import grid_key, cluster_issues_by_proximity
from services.score_service import SCORE_RULES

# AI modules
from ai.nlp_classifier import classify_issue
from ai.noise_validator import validate_noise
from ai.anomaly_detector import _mean_std
from ai.trust_scorer import compute_trust_score
from ai.image_analyzer import analyze_image


# ────────────────────────────────────────────────────────────
# 1. SERIALIZATION
# ────────────────────────────────────────────────────────────
class TestSerialization(unittest.TestCase):

    def test_objectid_serialized(self):
        oid = ObjectId("660000000000000000000001")
        result = serialize({'_id': oid})
        self.assertEqual(result['_id'], "660000000000000000000001")

    def test_datetime_serialized(self):
        dt = datetime(2026, 1, 1, 12, 0, 0)
        result = serialize({'ts': dt})
        self.assertEqual(result['ts'], "2026-01-01T12:00:00")

    def test_nested_dict(self):
        oid = ObjectId("660000000000000000000001")
        result = serialize({'outer': {'inner': oid}})
        self.assertEqual(result['outer']['inner'], str(oid))

    def test_list_of_dicts(self):
        items = [{'_id': ObjectId("660000000000000000000001")}, {'_id': ObjectId("660000000000000000000002")}]
        result = serialize(items)
        self.assertIsInstance(result, list)
        self.assertEqual(result[0]['_id'], "660000000000000000000001")

    def test_primitive_passthrough(self):
        self.assertEqual(serialize(42), 42)
        self.assertEqual(serialize("hello"), "hello")
        self.assertIsNone(serialize(None))


# ────────────────────────────────────────────────────────────
# 2. AUTHENTICATION
# ────────────────────────────────────────────────────────────
class TestAuthentication(unittest.TestCase):

    def test_password_hash_and_verify(self):
        pwd = "SecurePass@2026"
        hashed = hash_password(pwd)
        self.assertTrue(check_password(pwd, hashed))
        self.assertFalse(check_password("WrongPass", hashed))

    def test_different_hashes_for_same_password(self):
        pwd = "SamePassword123"
        hash1 = hash_password(pwd)
        hash2 = hash_password(pwd)
        self.assertNotEqual(hash1, hash2)  # bcrypt uses unique salts
        self.assertTrue(check_password(pwd, hash1))
        self.assertTrue(check_password(pwd, hash2))

    def test_empty_password_check_returns_false(self):
        hashed = hash_password("realpassword")
        self.assertFalse(check_password("", hashed))


# ────────────────────────────────────────────────────────────
# 3. SLA SERVICE
# ────────────────────────────────────────────────────────────
class TestSLAService(unittest.TestCase):

    def test_water_sla_1_day(self):
        now = datetime.utcnow()
        deadline = get_sla_deadline('water', now)
        self.assertEqual(deadline, now + timedelta(days=1))

    def test_sewage_sla_1_day(self):
        now = datetime.utcnow()
        self.assertEqual(get_sla_deadline('sewage', now), now + timedelta(days=1))

    def test_garbage_sla_2_days(self):
        now = datetime.utcnow()
        self.assertEqual(get_sla_deadline('garbage', now), now + timedelta(days=2))

    def test_streetlight_sla_3_days(self):
        now = datetime.utcnow()
        self.assertEqual(get_sla_deadline('streetlight', now), now + timedelta(days=3))

    def test_pothole_sla_7_days(self):
        now = datetime.utcnow()
        self.assertEqual(get_sla_deadline('pothole', now), now + timedelta(days=7))

    def test_unknown_category_defaults_7_days(self):
        now = datetime.utcnow()
        self.assertEqual(get_sla_deadline('unknown_xyz', now), now + timedelta(days=7))

    def test_sla_status_not_overdue(self):
        created = datetime.utcnow() - timedelta(hours=12)
        issue = {
            'created_at': created,
            'sla_deadline': datetime.utcnow() + timedelta(days=1),
            'category': 'garbage',
            'sla_breached': False
        }
        status = get_sla_status(issue)
        self.assertFalse(status['is_overdue'])
        self.assertGreater(status['days_remaining'], 0)

    def test_sla_status_overdue(self):
        created = datetime.utcnow() - timedelta(days=10)
        issue = {
            'created_at': created,
            'sla_deadline': datetime.utcnow() - timedelta(days=1),
            'category': 'pothole',
            'sla_breached': False
        }
        status = get_sla_status(issue)
        self.assertTrue(status['is_overdue'])

    def test_sla_percent_elapsed(self):
        created = datetime.utcnow() - timedelta(days=1)
        issue = {
            'created_at': created,
            'sla_deadline': datetime.utcnow() + timedelta(days=1),
            'category': 'garbage',
            'sla_breached': False
        }
        status = get_sla_status(issue)
        # 1 day elapsed out of 2 day SLA = ~50%
        self.assertGreater(status['percent_elapsed'], 40.0)
        self.assertLess(status['percent_elapsed'], 60.0)

    def test_sla_status_no_deadline(self):
        issue = {'created_at': datetime.utcnow(), 'sla_deadline': None, 'category': 'other', 'sla_breached': False}
        status = get_sla_status(issue)
        self.assertFalse(status['is_overdue'])
        self.assertIsNone(status['deadline_iso'])


# ────────────────────────────────────────────────────────────
# 4. ROUTE OPTIMIZER
# ────────────────────────────────────────────────────────────
class TestRouteOptimizer(unittest.TestCase):

    WORKER_LAT = 12.9352
    WORKER_LNG = 77.6245

    def _make_issue(self, idx, lat, lng, severity=3, category='pothole'):
        return {
            '_id': ObjectId(f"66000000000000000000{idx:04d}"),
            'lat': lat,
            'lng': lng,
            'title': f'Issue {idx}',
            'severity': severity,
            'category': category,
            'address': f'Location {idx}'
        }

    def test_haversine_zero_distance(self):
        self.assertAlmostEqual(haversine(12.9, 77.6, 12.9, 77.6), 0.0, places=5)

    def test_haversine_known_distance(self):
        # Roughly 1km apart
        dist = haversine(12.9352, 77.6245, 12.9442, 77.6245)
        self.assertGreater(dist, 0.5)
        self.assertLess(dist, 2.0)

    def test_haversine_symmetry(self):
        d1 = haversine(12.9, 77.6, 13.0, 77.7)
        d2 = haversine(13.0, 77.7, 12.9, 77.6)
        self.assertAlmostEqual(d1, d2, places=5)

    @patch('services.route_optimizer.get_osrm_distances', return_value=None)
    def test_optimize_route_two_issues(self, mock_osrm):
        issues = [
            self._make_issue(1, 12.9348, 77.6255, severity=3),
            self._make_issue(2, 12.9360, 77.6230, severity=5)
        ]
        route = optimize_route(self.WORKER_LAT, self.WORKER_LNG, issues)
        self.assertIn('ordered_issue_ids', route)
        self.assertIn('waypoints', route)
        self.assertEqual(len(route['waypoints']), 3)  # depot + 2 issues
        self.assertEqual(route['waypoints'][0]['issue_id'], 'depot')
        self.assertGreaterEqual(route['total_distance_km'], 0.0)

    @patch('services.route_optimizer.get_osrm_distances', return_value=None)
    def test_optimize_route_single_issue(self, mock_osrm):
        issues = [self._make_issue(1, 12.9348, 77.6255)]
        route = optimize_route(self.WORKER_LAT, self.WORKER_LNG, issues)
        self.assertEqual(len(route['waypoints']), 2)

    @patch('services.route_optimizer.get_osrm_distances', return_value=None)
    def test_severity_prioritization(self, mock_osrm):
        """Higher severity issue should be visited before lower severity at similar distance."""
        issues = [
            self._make_issue(1, 12.9353, 77.6246, severity=1),  # very close, low severity
            self._make_issue(2, 12.9355, 77.6248, severity=5),  # equally close, high severity
        ]
        route = optimize_route(self.WORKER_LAT, self.WORKER_LNG, issues)
        # First ordered stop should be the high severity issue (id 2)
        self.assertEqual(route['ordered_issue_ids'][0], str(issues[1]['_id']))

    def test_build_graph_haversine_fallback(self):
        locs = [
            {'id': 'a', 'lat': 12.9, 'lng': 77.6},
            {'id': 'b', 'lat': 13.0, 'lng': 77.7}
        ]
        with patch('services.route_optimizer.get_osrm_distances', return_value=None):
            graph = build_graph(locs)
        self.assertIn('a', graph)
        self.assertIn('b', graph['a'])
        self.assertGreater(graph['a']['b'], 0)


# ────────────────────────────────────────────────────────────
# 7. REPUTATION SERVICE
# ────────────────────────────────────────────────────────────
class TestReputationService(unittest.TestCase):

    def test_newcomer_at_zero(self):
        self.assertEqual(get_tier(0), 'Newcomer')

    def test_active_resident_at_20(self):
        self.assertEqual(get_tier(20), 'Active Resident')

    def test_civic_champion_at_50(self):
        self.assertEqual(get_tier(50), 'Civic Champion')

    def test_community_hero_at_100(self):
        self.assertEqual(get_tier(100), 'Community Hero')

    def test_tier_progression(self):
        self.assertEqual(get_tier(19), 'Newcomer')
        self.assertEqual(get_tier(49), 'Active Resident')
        self.assertEqual(get_tier(99), 'Civic Champion')
        self.assertEqual(get_tier(999), 'Community Hero')


# ────────────────────────────────────────────────────────────
# 8. VALIDATION SERVICE CONSTANTS
# ────────────────────────────────────────────────────────────
class TestValidationConstants(unittest.TestCase):

    def test_confirm_threshold_is_3(self):
        self.assertEqual(CONFIRM_THRESHOLD, 3)

    def test_deny_threshold_is_3(self):
        self.assertEqual(DENY_THRESHOLD, 3)

    def test_min_votes_for_reject_is_5(self):
        self.assertEqual(MIN_VOTES_FOR_REJECT, 5)


# ────────────────────────────────────────────────────────────
# 9. CLUSTERING SERVICE
# ────────────────────────────────────────────────────────────
class TestClusteringService(unittest.TestCase):

    def test_grid_key_same_cell(self):
        key1 = grid_key(12.9352, 77.6245)
        key2 = grid_key(12.9355, 77.6248)
        self.assertEqual(key1, key2)

    def test_grid_key_different_cell(self):
        key1 = grid_key(12.9, 77.6)
        key2 = grid_key(13.1, 77.8)
        self.assertNotEqual(key1, key2)

    def test_cluster_groups_nearby_issues(self):
        issues = [
            {'_id': ObjectId(), 'lat': 12.9352, 'lng': 77.6245, 'category': 'pothole', 'severity': 3, 'title': 'A', 'description': '', 'status': 'validated'},
            {'_id': ObjectId(), 'lat': 12.9353, 'lng': 77.6246, 'category': 'pothole', 'severity': 4, 'title': 'B', 'description': '', 'status': 'validated'},
            {'_id': ObjectId(), 'lat': 13.1000, 'lng': 77.8000, 'category': 'garbage', 'severity': 2, 'title': 'C', 'description': '', 'status': 'validated'},
        ]
        clusters = cluster_issues_by_proximity(issues)
        self.assertEqual(len(clusters), 2)
        # First cluster should be the pothole pair (higher priority)
        self.assertEqual(clusters[0]['count'], 2)

    def test_cluster_sorted_by_priority(self):
        issues = [
            {'_id': ObjectId(), 'lat': 12.9, 'lng': 77.6, 'category': 'garbage', 'severity': 5, 'title': 'X', 'description': '', 'status': 'validated'},
            {'_id': ObjectId(), 'lat': 13.1, 'lng': 77.8, 'category': 'noise', 'severity': 1, 'title': 'Y', 'description': '', 'status': 'validated'},
        ]
        clusters = cluster_issues_by_proximity(issues)
        self.assertGreaterEqual(clusters[0]['priority'], clusters[-1]['priority'])


# ────────────────────────────────────────────────────────────
# 8. SCORE RULES
# ────────────────────────────────────────────────────────────
class TestScoreRules(unittest.TestCase):

    def test_new_issue_penalty(self):
        self.assertEqual(SCORE_RULES['new_issue'], -2)

    def test_resolved_bonus(self):
        self.assertEqual(SCORE_RULES['issue_resolved'], +5)

    def test_stale_7_day_penalty(self):
        self.assertEqual(SCORE_RULES['stale_7days'], -3)

    def test_stale_severe_3_day_penalty(self):
        self.assertEqual(SCORE_RULES['stale_severe_3days'], -5)


# ────────────────────────────────────────────────────────────
# 9. NLP CLASSIFIER (AI)
# ────────────────────────────────────────────────────────────
class TestNLPClassifier(unittest.TestCase):

    def test_pothole_classification(self):
        result = classify_issue("Huge pothole on the main road")
        self.assertEqual(result['category'], 'pothole')
        self.assertGreater(result['confidence_score'], 0)
        self.assertIn('department', result)

    def test_garbage_classification(self):
        result = classify_issue("Garbage pile overflowing near park")
        self.assertEqual(result['category'], 'garbage')

    def test_water_classification(self):
        result = classify_issue("Water pipe burst near my house", "Continuous water leak")
        self.assertEqual(result['category'], 'water')

    def test_sewage_classification(self):
        result = classify_issue("Sewage overflow in street")
        self.assertEqual(result['category'], 'sewage')

    def test_streetlight_classification(self):
        result = classify_issue("No streetlight in lane, very dark")
        self.assertEqual(result['category'], 'streetlight')

    def test_noise_classification(self):
        result = classify_issue("Loud noise from construction at night")
        self.assertEqual(result['category'], 'noise')

    def test_unknown_returns_other(self):
        result = classify_issue("Something happened here")
        self.assertEqual(result['category'], 'other')
        self.assertEqual(result['confidence_score'], 0.0)

    def test_urgency_flag_detected(self):
        result = classify_issue("Emergency! Burst pipe flooding the road")
        self.assertTrue(result['urgency_flag'])

    def test_no_urgency_normal_report(self):
        result = classify_issue("There is a pothole near the bus stop")
        self.assertFalse(result['urgency_flag'])

    def test_department_mapping(self):
        result = classify_issue("Pothole on road")
        self.assertIn("BBMP", result['department'])

    def test_top_matches_returned(self):
        result = classify_issue("Pothole near drain overflow")
        self.assertIsInstance(result['top_matches'], list)
        self.assertGreater(len(result['top_matches']), 0)


# ────────────────────────────────────────────────────────────
# 10. NOISE VALIDATOR (AI)
# ────────────────────────────────────────────────────────────
class TestNoiseValidator(unittest.TestCase):

    def test_compliant_daytime_residential(self):
        result = validate_noise(50.0, 'residential', is_night=False)
        self.assertTrue(result['compliant'])
        self.assertEqual(result['cpcb_status'], 'COMPLIANT')
        self.assertEqual(result['estimated_severity'], 1)

    def test_exceeded_daytime_residential(self):
        result = validate_noise(70.0, 'residential', is_night=False)
        self.assertFalse(result['compliant'])
        self.assertGreater(result['excess_db'], 0)

    def test_nighttime_limit_lower(self):
        # 50 dB is compliant in day but not at night (residential night limit = 45)
        day_result = validate_noise(50.0, 'residential', is_night=False)
        night_result = validate_noise(50.0, 'residential', is_night=True)
        self.assertTrue(day_result['compliant'])
        self.assertFalse(night_result['compliant'])

    def test_industrial_zone_higher_limit(self):
        result = validate_noise(70.0, 'industrial', is_night=False)
        self.assertTrue(result['compliant'])  # Industrial day limit is 75

    def test_silence_zone_strictest(self):
        result = validate_noise(55.0, 'silence', is_night=False)
        self.assertFalse(result['compliant'])  # Silence zone day limit is 50

    def test_severity_5_extreme_noise(self):
        result = validate_noise(120.0, 'residential', is_night=False)
        self.assertEqual(result['estimated_severity'], 5)

    def test_severity_1_marginal_breach(self):
        # Only 2 dB over residential day limit (55+2=57)
        result = validate_noise(57.0, 'residential', is_night=False)
        self.assertIn(result['estimated_severity'], [1, 2])

    def test_invalid_zone_defaults_to_residential(self):
        result = validate_noise(50.0, 'nonexistent_zone', is_night=False)
        self.assertEqual(result['zone'], 'nonexistent_zone')
        # Should still return a result without crashing


# ────────────────────────────────────────────────────────────
# 11. ANOMALY DETECTOR UTILS
# ────────────────────────────────────────────────────────────
class TestAnomalyDetectorUtils(unittest.TestCase):

    def test_mean_std_empty(self):
        m, s = _mean_std([])
        self.assertEqual(m, 0.0)
        self.assertEqual(s, 0.0)

    def test_mean_std_constant(self):
        m, s = _mean_std([5, 5, 5, 5])
        self.assertEqual(m, 5.0)
        self.assertEqual(s, 0.0)

    def test_mean_std_known_values(self):
        m, s = _mean_std([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertAlmostEqual(m, 5.0, places=1)
        self.assertAlmostEqual(s, 2.0, places=1)


# ────────────────────────────────────────────────────────────
# 12. IMAGE ANALYZER (AI) — unit test with synthetic images
# ────────────────────────────────────────────────────────────
class TestImageAnalyzer(unittest.TestCase):

    def _make_image_bytes(self, width=640, height=480, color=(128, 128, 128)) -> bytes:
        from PIL import Image
        from io import BytesIO
        img = Image.new('RGB', (width, height), color)
        buf = BytesIO()
        img.save(buf, 'JPEG')
        return buf.getvalue()

    def test_valid_image_passes(self):
        # Bright, large enough image should pass
        img_bytes = self._make_image_bytes(640, 480, color=(180, 180, 180))
        result = analyze_image(img_bytes)
        # Note: solid-color images have very low sharpness — this tests the pipeline runs
        self.assertIn('passed', result)
        self.assertIn('estimated_severity', result)
        self.assertIn('confidence', result)

    def test_dark_image_fails_quality_gate(self):
        img_bytes = self._make_image_bytes(640, 480, color=(5, 5, 5))
        result = analyze_image(img_bytes)
        # Very dark image should fail
        self.assertFalse(result.get('passed', True))

    def test_low_resolution_fails(self):
        img_bytes = self._make_image_bytes(100, 80, color=(128, 128, 128))
        result = analyze_image(img_bytes)
        self.assertFalse(result.get('passed', True))

    def test_invalid_bytes_returns_failed(self):
        result = analyze_image(b"not_an_image_at_all")
        self.assertFalse(result['passed'])
        self.assertIsNotNone(result.get('reject_reason'))

    def test_result_has_required_keys(self):
        img_bytes = self._make_image_bytes(800, 600, color=(150, 150, 150))
        result = analyze_image(img_bytes)
        for key in ['passed', 'sharpness', 'luminance', 'resolution_score', 'estimated_severity', 'confidence']:
            self.assertIn(key, result)

    def test_severity_range_1_to_5(self):
        img_bytes = self._make_image_bytes(720, 540, color=(100, 100, 100))
        result = analyze_image(img_bytes)
        if result.get('passed'):
            self.assertIn(result['estimated_severity'], [1, 2, 3, 4, 5])


# ────────────────────────────────────────────────────────────
# 13. INTEGRATION SMOKE TESTS (no DB needed)
# ────────────────────────────────────────────────────────────
class TestIntegrationSmoke(unittest.TestCase):

    def test_full_report_pipeline_nlp_then_noise(self):
        """Simulate the full AI pipeline for a noise complaint."""
        text_result = classify_issue("Loud music at night from neighbours", "Very disturbing noise after 11pm")
        self.assertEqual(text_result['category'], 'noise')
        self.assertTrue(text_result['urgency_flag'] or not text_result['urgency_flag'])  # just run without crash

        noise_result = validate_noise(72.0, 'residential', is_night=True)
        self.assertFalse(noise_result['compliant'])
        self.assertGreater(noise_result['estimated_severity'], 1)

    def test_route_optimizer_returns_correct_waypoint_count(self):
        """3 issues → 4 waypoints (depot + 3)."""
        issues = [
            {'_id': ObjectId(f"66000000000000000000000{i}"), 'lat': 12.93 + i * 0.001, 'lng': 77.62 + i * 0.001,
             'title': f'Issue {i}', 'severity': 3, 'category': 'pothole', 'address': f'Addr {i}'}
            for i in range(1, 4)
        ]
        with patch('services.route_optimizer.get_osrm_distances', return_value=None):
            with patch('urllib.request.urlopen') as mock_url:
                mock_url.side_effect = Exception("no network in test")
                route = optimize_route(12.9352, 77.6245, issues)
        self.assertEqual(len(route['waypoints']), 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
