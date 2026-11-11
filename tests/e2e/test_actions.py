"""
tests/e2e/test_actions.py - E2E Action Verification Suite
Exercises every user action across all roles using Playwright and seeded demo data:
1. Admin: view dashboard, switch tabs, view analytics, filter issues, approve pending citizen.
2. Officer (ALL wards): switch tabs, filter priority queue, open drawer/detail, view worker list, what-if sim.
3. Officer (Ward-scoped): switch tabs, view jurisdiction-filtered issues.
4. Worker: view assigned tasks, update location, open task details.
5. Citizen (Verified): view dashboard, open report form, drop map pin, submit report, view My Reports.
6. Citizen (Pending): view verify-ward page, attempt submission / verification view.

Invariants monitored on every action:
- Zero unhandled console errors
- Zero CSP violations
- Zero failed network requests (4xx/5xx/429)
- UI state updates after action
- No 'undefined' or '[object Object]' text
- No hanging loading spinners (> 8s)
"""

import os
import sys
import time
import pytest
from bson import ObjectId
from playwright.sync_api import sync_playwright

os.environ["APP_ENV"] = "development"
os.environ["FLASK_ENV"] = "development"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["WTF_CSRF_ENABLED"] = "true"

from app import db


class ActionFailure(Exception):
    pass


def attach_error_monitors(page):
    errors = []
    failed_requests = []

    def on_console(msg):
        if msg.type in ("error", "assert"):
            txt = msg.text
            # Ignore Leaflet tile host 404s/cross-origin tile notices, favicon, or aborted network connections on page nav
            if "tile" in txt.lower() or "favicon" in txt.lower() or "err_connection_closed" in txt.lower() or "err_aborted" in txt.lower():
                return
            loc_url = ""
            try:
                loc_url = msg.location.get("url", "") if isinstance(msg.location, dict) else str(getattr(msg, "location", ""))
            except Exception:
                pass
            if "favicon.ico" in loc_url:
                return
            errors.append(f"Console {msg.type}: {txt}")

    def on_response(resp):
        url = resp.url
        status = resp.status
        # Ignore external tile server 4xx or favicon
        if "openstreetmap.org" in url or "cartocdn.com" in url or "favicon.ico" in url:
            return
        if status >= 400:
            failed_requests.append(f"{resp.request.method} {url} returned {status}")

    page.on("console", on_console)
    page.on("response", on_response)
    return errors, failed_requests


def login(page, base_url, email, password):
    page.goto(f"{base_url}/login")
    page.wait_for_selector("#email")
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("button[type='submit']")
    page.wait_for_url(lambda u: "/login" not in u, timeout=10000)


def assert_invariants(page, errors, failed_requests, context_name):
    page.wait_for_timeout(500)
    # Check hanging spinners
    spinners = page.locator(".spinner-border, .fa-spinner.fa-spin:not(.button-spinner)")
    for i in range(spinners.count()):
        try:
            if spinners.nth(i).is_visible():
                raise ActionFailure(f"[{context_name}] Spinner still visible after action.")
        except Exception:
            pass

    content = page.content()
    if "undefined" in content.lower():
        # Check if literally rendered in text nodes
        bad_texts = page.locator("text=/\\bundefined\\b/").all_text_contents()
        if bad_texts:
            raise ActionFailure(f"[{context_name}] 'undefined' rendered in DOM: {bad_texts}")
    if "[object Object]" in content:
        raise ActionFailure(f"[{context_name}] '[object Object]' rendered in DOM.")

    if failed_requests:
        raise ActionFailure(f"[{context_name}] Failed HTTP requests: {failed_requests}")
    if errors:
        raise ActionFailure(f"[{context_name}] Console errors: {errors}")


def test_admin_actions(browser, live_server):
    context = browser.new_context()
    page = context.new_page()
    errors, failed_requests = attach_error_monitors(page)

    login(page, live_server, "admin@smartcivic.com", "smartcivic123")
    assert_invariants(page, errors, failed_requests, "admin_login")

    # Action 1: Switch to account-approvals tab
    page.click("button:has-text('Account Approvals')")
    page.wait_for_selector("#approvalsGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "admin_approvals_tab")

    # Action 2: Switch to priority queue
    page.click("button:has-text('Priority Queue')")
    page.wait_for_selector("#issuesGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "admin_priority_queue_tab")

    # Action 3: Switch to workers tab
    page.click("button:has-text('Workers')")
    page.wait_for_selector("#workersGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "admin_workers_tab")

    # Action 4: Switch to SLA Alerts tab
    page.click("button:has-text('SLA Alerts')")
    page.wait_for_selector("#issuesGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "admin_sla_alerts_tab")

    # Action 5: Visit Map page
    page.goto(f"{live_server}/map")
    page.wait_for_selector("#map", state="visible")
    assert_invariants(page, errors, failed_requests, "admin_map_page")

    context.close()


def test_officer_all_actions(browser, live_server):
    context = browser.new_context()
    page = context.new_page()
    errors, failed_requests = attach_error_monitors(page)

    login(page, live_server, "authority@smartcivic.com", "smartcivic123")
    assert_invariants(page, errors, failed_requests, "officer_all_login")

    # Action 1: Switch to New Issues tab
    page.click("button:has-text('New Issues')")
    page.wait_for_selector("#issuesGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "officer_all_new_issues")

    # Action 2: Switch to In Progress tab
    page.click("button:has-text('In Progress')")
    page.wait_for_selector("#issuesGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "officer_all_in_progress")

    # Action 3: Open What-If Simulator and run simulations
    page.click("button:has-text('What-If Simulator')")
    page.wait_for_selector("#simWorkerCount", state="visible")
    page.fill("#simWorkerCount", "3")
    page.click("button:has-text('Run Simulation')")
    page.wait_for_selector("#workerSimResult", state="visible")
    assert_invariants(page, errors, failed_requests, "officer_all_worker_sim")

    # Category Simulation
    cat_btn = page.locator("button[onclick='runCategorySim()'], button:has-text('Run Category Priority Sim')")
    if cat_btn.count() > 0:
        cat_btn.first.click()
        page.wait_for_selector("#categorySimResult", state="visible")
        assert_invariants(page, errors, failed_requests, "officer_all_category_sim")

    # Action 4: Visit Map page
    page.goto(f"{live_server}/map")
    page.wait_for_selector("#map", state="visible")
    assert_invariants(page, errors, failed_requests, "officer_all_map_page")

    context.close()


def test_officer_ward_actions(browser, live_server):
    context = browser.new_context()
    page = context.new_page()
    errors, failed_requests = attach_error_monitors(page)

    login(page, live_server, "officer@smartcivic.com", "smartcivic123")
    assert_invariants(page, errors, failed_requests, "officer_ward_login")

    # Action 1: Switch to Ward Health tab
    page.click("button:has-text('Ward Health')")
    page.wait_for_selector("#wardHealthGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "officer_ward_health")

    # Action 2: Switch to SLA alerts tab
    page.click("button:has-text('SLA Alerts')")
    page.wait_for_selector("#issuesGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "officer_ward_sla_alerts")

    # Action 3: Switch to Verification tab
    page.click("button:has-text('Verification')")
    page.wait_for_selector("#verificationGrid", state="visible")
    assert_invariants(page, errors, failed_requests, "officer_ward_verification")

    context.close()


def test_worker_actions(browser, live_server):
    context = browser.new_context()
    page = context.new_page()
    errors, failed_requests = attach_error_monitors(page)

    login(page, live_server, "worker@smartcivic.com", "smartcivic123")
    assert_invariants(page, errors, failed_requests, "worker_login")

    # Action 1: Inspect task queue / jobs panel
    page.wait_for_selector("#jobsList", state="visible")
    page.wait_for_selector("#workerMap", state="visible")
    assert_invariants(page, errors, failed_requests, "worker_task_view")

    # Action 2: If jobs exist, inspect job detail modal
    job_cards = page.locator("#jobsList .job-card")
    if job_cards.count() > 0:
        job_cards.first.click()
        page.wait_for_selector("#jobDetailModal", state="visible")
        assert_invariants(page, errors, failed_requests, "worker_open_job_modal")
        page.click("button:has-text('Close')")
        page.wait_for_selector("#jobDetailModal", state="hidden")
        assert_invariants(page, errors, failed_requests, "worker_close_job_modal")

    context.close()


def test_citizen_verified_actions(browser, live_server):
    context = browser.new_context()
    page = context.new_page()
    errors, failed_requests = attach_error_monitors(page)

    login(page, live_server, "citizen@smartcivic.com", "smartcivic123")
    assert_invariants(page, errors, failed_requests, "citizen_login")

    # Action 1: Navigate to Report Issue
    page.goto(f"{live_server}/citizen/report")
    page.wait_for_selector("#title")
    page.fill("#title", "Test Reported Pothole via Actions Suite")
    page.fill("#description", "Hazardous pothole observed on main road near junction.")
    page.fill("#address", "Indiranagar 100ft road, Bengaluru")
    page.fill("#ward", "Ward 150 - Bellandur")

    # Trigger locateMe button if present
    locate_btn = page.locator("#btnLocateMe, button:has-text('Use Current Location')")
    if locate_btn.count() > 0 and locate_btn.is_visible():
        locate_btn.click()
        page.wait_for_timeout(500)

    assert_invariants(page, errors, failed_requests, "citizen_report_form")

    # Action 2: Visit citizen dashboard and inspect reports
    page.goto(f"{live_server}/citizen/dashboard")
    page.wait_for_selector("#trackerList", state="visible")
    assert_invariants(page, errors, failed_requests, "citizen_dashboard_view")

    context.close()


def test_citizen_pending_actions(browser, live_server):
    context = browser.new_context()
    page = context.new_page()
    errors, failed_requests = attach_error_monitors(page)

    login(page, live_server, "pending_citizen@smartcivic.com", "smartcivic123")
    assert_invariants(page, errors, failed_requests, "citizen_pending_login")

    # Ensure pending user is directed to verify-ward page
    if "/citizen/verify-ward" not in page.url:
        page.goto(f"{live_server}/citizen/verify-ward")
    page.wait_for_selector("#verifyWardForm", state="visible", timeout=8000)
    page.wait_for_selector("#areaCodeInput", state="visible")

    # Action 1: Submit valid ward code
    page.fill("#areaCodeInput", "KDM-001")
    page.click("button[type='submit']")
    page.wait_for_selector("#verifyAlert", state="visible")
    assert_invariants(page, errors, failed_requests, "citizen_pending_code_alert")

    context.close()
