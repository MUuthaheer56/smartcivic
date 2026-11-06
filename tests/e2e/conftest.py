"""
tests/e2e/conftest.py - Shared Playwright browser and live_server fixtures for all E2E suites.
"""
import os
import sys
import time
import socket
import threading
import urllib.request
import pytest
from playwright.sync_api import sync_playwright

os.environ["APP_ENV"] = "development"
os.environ["FLASK_ENV"] = "development"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["WTF_CSRF_ENABLED"] = "true"

from app import create_app, socketio


def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    port = get_free_port()
    os.environ["ALLOWED_ORIGINS"] = f"http://localhost:{port},http://127.0.0.1:{port}"
    app = create_app()
    app.config["TESTING"] = False

    server_thread = threading.Thread(
        target=lambda: socketio.run(
            app,
            host="127.0.0.1",
            port=port,
            debug=False,
            use_reloader=False,
            allow_unsafe_werkzeug=True
        ),
        daemon=True
    )
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    started = False
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1) as resp:
                if resp.status == 200:
                    started = True
                    break
        except Exception:
            time.sleep(0.25)

    if not started:
        pytest.fail("Live test server failed to start within timeout.")

    yield base_url


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        try:
            yield b
        finally:
            b.close()
