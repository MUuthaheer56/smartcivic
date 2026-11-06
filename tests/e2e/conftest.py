"""
tests/e2e/conftest.py - Shared Playwright browser fixture for all E2E suites.
"""

import asyncio
import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def browser():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        yield b
        b.close()
