import os
import sys
import time
import socket
import threading
import urllib.request
import pytest
from bson import ObjectId

# Testing environment setup
os.environ["APP_ENV"] = "development"
os.environ["FLASK_ENV"] = "development"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["WTF_CSRF_ENABLED"] = "true"

from app import create_app, socketio, db

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

ROLES_CONFIG = [
    {
        "role": "admin",
        "email": "admin@smartcivic.com",
        "password": "smartcivic123",
        "pages": ["/admin/dashboard", "/map"],
        "tabs": [
            ("overview", "#statTotal"),
            ("new-complaints", "#issuesGrid"),
            ("priority-queue", "#issuesGrid"),
            ("in-progress", "#issuesGrid"),
            ("account-approvals", "#approvalsGrid"),
            ("sla-alerts", "#issuesGrid"),
            ("workers-view", "#workersList"),
            ("ward-health", "#wardScoresList"),
            ("recurring", "#recurringList")
        ]
    },
    {
        "role": "officer_all",
        "email": "authority@smartcivic.com",
        "password": "smartcivic123",
        "pages": ["/officer/dashboard", "/map"],
        "tabs": [
            ("overview", "#statTotal"),
            ("new-complaints", "#issuesGrid"),
            ("priority-queue", "#issuesGrid"),
            ("in-progress", "#issuesGrid"),
            ("account-approvals", "#approvalsGrid"),
            ("sla-alerts", "#issuesGrid"),
            ("workers-view", "#workersList"),
            ("ward-health", "#wardScoresList"),
            ("recurring", "#recurringList")
        ]
    },
    {
        "role": "officer_ward",
        "email": "officer@smartcivic.com",
        "password": "smartcivic123",
        "pages": ["/officer/dashboard", "/map"],
        "tabs": [
            ("overview", "#statTotal"),
            ("new-complaints", "#issuesGrid"),
            ("priority-queue", "#issuesGrid"),
            ("in-progress", "#issuesGrid"),
            ("account-approvals", "#approvalsGrid"),
            ("sla-alerts", "#issuesGrid"),
            ("workers-view", "#workersList"),
            ("ward-health", "#wardScoresList"),
            ("recurring", "#recurringList")
        ]
    },
    {
        "role": "worker",
        "email": "worker@smartcivic.com",
        "password": "smartcivic123",
        "pages": ["/worker/dashboard", "/map"],
        "tabs": []
    },
    {
        "role": "citizen_verified",
        "email": "citizen@smartcivic.com",
        "password": "smartcivic123",
        "pages": ["/citizen/dashboard", "/citizen/report", "/citizen/verify-ward", "/map"],
        "tabs": []
    },
    {
        "role": "citizen_pending",
        "email": "pending_citizen@smartcivic.com",
        "password": "smartcivic123",
        "pages": ["/citizen/verify-ward", "/map"],
        "tabs": []
    }
]

def check_page_invariants(page, role, location_label, db_has_data=False):
    """
    Evaluates the 5 mandatory invariants:
    1. No console errors
    2. No failed network requests
    3. No loading spinner still visible after 8 seconds
    4. No 'undefined' or '[object Object]' text
    5. No empty state shown when DB has data
    """
    # 3. Check for lingering spinners after up to 8s
    spinner_selector = ".fa-spinner:visible, .spinner:visible, .loading-state:visible, [aria-busy='true']:visible"
    try:
        page.wait_for_selector(spinner_selector, state="detached", timeout=8000)
    except Exception:
        pass # Will assert visibility below

    lingering_spinners = page.locator(spinner_selector).all()
    visible_spinners = [s for s in lingering_spinners if s.is_visible()]
    assert len(visible_spinners) == 0, f"Loading spinner still visible after 8 seconds on {role} at {location_label}"

    # 4. Check for 'undefined' or '[object Object]' text
    body_text = page.locator("body").inner_text()
    assert "undefined" not in body_text, f"Found 'undefined' text in page content on {role} at {location_label}"
    assert "[object Object]" not in body_text, f"Found '[object Object]' text in page content on {role} at {location_label}"

    # 5. Check empty state if DB has data
    if db_has_data:
        # Check if an empty state container is unexpectedly displayed
        empty_states = page.locator(".empty-state:visible, .map-empty-state:visible").all()
        assert len(empty_states) == 0, f"Empty state shown when database has data on {role} at {location_label}"


@pytest.mark.parametrize("config", ROLES_CONFIG, ids=[c["role"] for c in ROLES_CONFIG])
def test_role_e2e_smoke(live_server, config):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    role = config["role"]
    email = config["email"]
    password = config["password"]
    pages = config["pages"]
    tabs = config["tabs"]

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context()
        page = context.new_page()

        console_errors = []
        page_errors = []
        failed_requests = []

        def on_console(msg):
            if msg.type == "error":
                loc_url = ""
                try:
                    loc_url = msg.location.get("url", "") if isinstance(msg.location, dict) else str(getattr(msg, "location", ""))
                except Exception:
                    pass
                if "favicon.ico" in loc_url or "favicon.ico" in msg.text:
                    return
                console_errors.append(f"{msg.text} [loc: {loc_url}]")

        def on_page_error(err):
            page_errors.append(str(err))

        def on_response(resp):
            if "favicon.ico" in resp.url:
                return
            if resp.status >= 400:
                failed_requests.append(f"{resp.request.method} {resp.url} -> {resp.status}")

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("response", on_response)

        # 1. Login
        page.goto(f"{live_server}/login")
        page.wait_for_load_state("networkidle")
        page.fill('#email', email)
        page.fill('#password', password)
        page.click('#loginSubmit')
        page.wait_for_timeout(2000)

        # 2. Visit every configured page
        for page_path in pages:
            console_errors.clear()
            page_errors.clear()
            failed_requests.clear()

            full_url = f"{live_server}{page_path}"
            page.goto(full_url, wait_until="load", timeout=12000)
            page.wait_for_timeout(2000)

            # Check network & console invariants
            assert len(page_errors) == 0, f"Page errors on {role} {page_path}: {page_errors}"
            assert len(console_errors) == 0, f"Console errors on {role} {page_path}: {console_errors}"
            assert len(failed_requests) == 0, f"Failed requests on {role} {page_path}: {failed_requests}"

            # Check UI invariants
            # On live map or citizen dashboard, DB has issues
            db_has_data = False
            if page_path == "/map":
                db_has_data = (db.issues.count_documents({"status": {"$nin": ["closed", "rejected"]}}) > 0)
            elif page_path == "/citizen/dashboard" and role == "citizen_verified":
                db_has_data = (db.issues.count_documents({"citizen_id": ObjectId("6aed722e7754529d71c908b0")}) > 0)
            elif page_path == "/worker/dashboard" and role == "worker":
                db_has_data = (db.issues.count_documents({"worker_id": ObjectId("6aed722e7754529d71c908b4")}) > 0)

            check_page_invariants(page, role, page_path, db_has_data=db_has_data)

            # If this is the officer dashboard, exercise all tabs
            if "dashboard" in page_path and tabs:
                for tab_id, expected_selector in tabs:
                    console_errors.clear()
                    page_errors.clear()
                    failed_requests.clear()

                    # Click tab button or invoke switchTab
                    page.evaluate(f"switchTab('{tab_id}')")
                    page.wait_for_timeout(1000)

                    assert len(page_errors) == 0, f"Page errors on {role} tab '{tab_id}': {page_errors}"
                    assert len(console_errors) == 0, f"Console errors on {role} tab '{tab_id}': {console_errors}"
                    assert len(failed_requests) == 0, f"Failed requests on {role} tab '{tab_id}': {failed_requests}"

                    tab_has_data = False
                    if tab_id in ["new-complaints", "priority-queue"] and role in ["officer_all", "admin"]:
                        tab_has_data = True
                    elif tab_id == "account-approvals":
                        tab_has_data = (db.users.count_documents({"verification_status": "pending"}) > 0)

                    check_page_invariants(page, role, f"tab:{tab_id}", db_has_data=tab_has_data)

        context.close()
        browser.close()

