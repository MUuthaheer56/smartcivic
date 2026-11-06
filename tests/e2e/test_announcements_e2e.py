"""
tests/e2e/test_announcements_e2e.py - Playwright E2E Multi-Context Test for Announcement Broadcast
Flow:
1. Admin logs in, opens Broadcasts tab, fills out form, accepts confirm dialog, broadcasts notice.
2. Verified citizen logs in, views citizen dashboard, sees active notice banner rendered via DOM.
3. Citizen clicks Dismiss, banner hides and status is updated.
4. Admin views history, retracts notice.
Invariants checked:
- Zero unhandled console errors
- Zero CSP violations
- Zero failed network requests
- Strictly safe text rendering (no undefined, no [object Object])
"""

import os
import pytest
from playwright.sync_api import sync_playwright

os.environ["APP_ENV"] = "development"
os.environ["FLASK_ENV"] = "development"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["WTF_CSRF_ENABLED"] = "true"

from app import db
from tests.e2e.test_smoke import live_server
from tests.e2e.test_actions import attach_error_monitors, login, assert_invariants


def test_announcement_broadcast_and_dismiss_e2e(browser, live_server):
    admin_ctx = browser.new_context()
    admin_page = admin_ctx.new_page()
    admin_errors, admin_failed = attach_error_monitors(admin_page)

    citizen_ctx = browser.new_context()
    citizen_page = citizen_ctx.new_page()
    cit_errors, cit_failed = attach_error_monitors(citizen_page)

    try:
        # Step 1: Admin logs in and opens Broadcasts tab
        login(admin_page, live_server, "admin@smartcivic.com", "smartcivic123")
        admin_page.wait_for_selector("#btn-tab-announcements", state="visible")
        admin_page.click("#btn-tab-announcements")
        admin_page.wait_for_selector("#tab-announcements", state="visible")
        assert_invariants(admin_page, admin_errors, admin_failed, "admin_open_broadcasts")

        # Step 2: Admin composes notice and broadcasts
        admin_page.fill("#annTitle", "E2E Scheduled Road Work Notice")
        admin_page.fill("#annBody", "Road resurfacing is planned along 100ft road from 9 PM to 5 AM.")
        admin_page.select_option("#annSeverity", "warning")
        admin_page.select_option("#annAudience", "both")

        # Handle browser confirmation dialog
        admin_page.on("dialog", lambda dialog: dialog.accept())

        admin_page.click("#btnSubmitBroadcast")
        admin_page.wait_for_selector("#annBroadcastStatus:has-text('Notice broadcast successfully')", state="visible", timeout=6000)
        assert_invariants(admin_page, admin_errors, admin_failed, "admin_submit_broadcast")

        # Step 3: Citizen logs in and views dashboard
        login(citizen_page, live_server, "citizen@smartcivic.com", "smartcivic123")
        citizen_page.wait_for_selector("#activeAnnouncementBanner", state="visible", timeout=8000)
        banner_text = citizen_page.locator("#activeAnnouncementBanner").text_content()
        assert "E2E Scheduled Road Work Notice" in banner_text
        assert_invariants(citizen_page, cit_errors, cit_failed, "citizen_view_announcement")

        # Step 4: Citizen dismisses notice
        citizen_page.click("#activeAnnouncementBanner button:has-text('Dismiss')")
        citizen_page.wait_for_selector("#activeAnnouncementBanner", state="hidden", timeout=5000)
        assert_invariants(citizen_page, cit_errors, cit_failed, "citizen_dismiss_announcement")

        # Step 5: Admin retracts announcement
        admin_page.wait_for_selector("#announcementsHistoryList button:has-text('Retract')", state="visible")
        admin_page.click("#announcementsHistoryList button:has-text('Retract')")
        admin_page.wait_for_timeout(1000)
        assert_invariants(admin_page, admin_errors, admin_failed, "admin_retract_announcement")

    finally:
        admin_ctx.close()
        citizen_ctx.close()
        # Clean up test announcements
        db.announcements.delete_many({"title": "E2E Scheduled Road Work Notice"})
        db.audit_logs.delete_many({"action": {"$in": ["ADMIN_ANNOUNCEMENT_BROADCAST", "ADMIN_ANNOUNCEMENT_RETRACTED"]}})
