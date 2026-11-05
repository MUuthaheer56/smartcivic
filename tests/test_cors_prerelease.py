import os
import unittest
from unittest.mock import patch
import pytest

from app import _get_cors_origins, create_app
from config import Config


class TestCorsHardening(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {}, clear=False)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_allowed_origins_parsed_from_env(self):
        os.environ["ALLOWED_ORIGINS"] = "https://civic.bengaluru.gov.in, https://admin.smartcivic.org"
        os.environ["FLASK_ENV"] = "development"
        origins = _get_cors_origins()
        self.assertEqual(origins, ["https://civic.bengaluru.gov.in", "https://admin.smartcivic.org"])

    def test_cors_origins_fallback_to_cors_allowed_origins_env(self):
        if "ALLOWED_ORIGINS" in os.environ:
            del os.environ["ALLOWED_ORIGINS"]
        os.environ["CORS_ALLOWED_ORIGINS"] = "https://portal.smartcivic.in"
        os.environ["FLASK_ENV"] = "development"
        origins = _get_cors_origins()
        self.assertEqual(origins, ["https://portal.smartcivic.in"])

    def test_development_mode_defaults(self):
        if "ALLOWED_ORIGINS" in os.environ:
            del os.environ["ALLOWED_ORIGINS"]
        if "CORS_ALLOWED_ORIGINS" in os.environ:
            del os.environ["CORS_ALLOWED_ORIGINS"]
        os.environ["FLASK_ENV"] = "development"
        origins = _get_cors_origins()
        self.assertIn("http://localhost:5000", origins)
        self.assertIn("http://127.0.0.1:5000", origins)

    def test_production_mode_refuses_localhost(self):
        os.environ["FLASK_ENV"] = "production"
        os.environ["ALLOWED_ORIGINS"] = "http://localhost:5000, https://smartcivic.gov.in"
        with self.assertRaises(RuntimeError) as ctx:
            _get_cors_origins()
        self.assertIn("refuses localhost/loopback", str(ctx.exception))

    def test_production_mode_refuses_127_0_0_1(self):
        os.environ["FLASK_ENV"] = "production"
        os.environ["ALLOWED_ORIGINS"] = "http://127.0.0.1:3000, https://smartcivic.gov.in"
        with self.assertRaises(RuntimeError) as ctx:
            _get_cors_origins()
        self.assertIn("refuses localhost/loopback", str(ctx.exception))

    def test_production_mode_refuses_missing_allowed_origins(self):
        os.environ["FLASK_ENV"] = "production"
        if "ALLOWED_ORIGINS" in os.environ:
            del os.environ["ALLOWED_ORIGINS"]
        if "CORS_ALLOWED_ORIGINS" in os.environ:
            del os.environ["CORS_ALLOWED_ORIGINS"]
        with self.assertRaises(RuntimeError) as ctx:
            _get_cors_origins()
        self.assertIn("ALLOWED_ORIGINS environment variable must be explicitly defined", str(ctx.exception))

    def test_production_mode_allows_clean_domains(self):
        os.environ["FLASK_ENV"] = "production"
        os.environ["ALLOWED_ORIGINS"] = "https://smartcivic.gov.in, https://bbmp.smartcivic.gov.in"
        origins = _get_cors_origins()
        self.assertEqual(origins, ["https://smartcivic.gov.in", "https://bbmp.smartcivic.gov.in"])

    def test_flask_and_socketio_share_same_cors_origins(self):
        os.environ["ALLOWED_ORIGINS"] = "https://app.smartcivic.gov.in"
        os.environ["FLASK_ENV"] = "development"
        app = create_app()
        from app import socketio
        expected_origins = ["https://app.smartcivic.gov.in"]
        self.assertEqual(socketio.server.eio.cors_allowed_origins, expected_origins)
