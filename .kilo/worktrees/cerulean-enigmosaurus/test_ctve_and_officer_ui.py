"""
Test script for CTVE UI + CEFAP Officer Dashboard Card Integration.
Verifies all backend routes, database indexes, templates, and static JS components.
"""
import sys
import os
import re

def run_tests():
    print("=" * 60)
    print("SMARTCIVIC CTVE & CEFAP OFFICER DASHBOARD UI VERIFICATION")
    print("=" * 60)

    results = []

    # 1. Check ctve-response route in routes/api/issues.py
    issues_route_path = os.path.join("routes", "api", "issues.py")
    if os.path.exists(issues_route_path):
        with open(issues_route_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "ctve-response" in content and "def ctve_response" in content:
            results.append(("CTVE Response API Route", True, "Route /api/issues/<issue_id>/ctve-response defined"))
        else:
            results.append(("CTVE Response API Route", False, "Route /api/issues/<issue_id>/ctve-response missing in issues.py"))
    else:
        results.append(("CTVE Response API Route", False, f"File {issues_route_path} not found"))

    # 2. Check setup_indexes.py for cefap_ctve_events index
    index_path = "setup_indexes.py"
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "cefap_ctve_events" in content:
            results.append(("CEFAP CTVE Events Index", True, "cefap_ctve_events index defined in setup_indexes.py"))
        else:
            results.append(("CEFAP CTVE Events Index", False, "cefap_ctve_events missing in setup_indexes.py"))
    else:
        results.append(("CEFAP CTVE Events Index", False, "setup_indexes.py not found"))

    # 3. Check get_issue route returns CEFAP signals
    if os.path.exists(issues_route_path):
        with open(issues_route_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "evidence_reliability" in content and "evidence_agreement" in content and "ctve_triggered" in content:
            results.append(("Issue Detail API CEFAP Signals", True, "GET /api/issues/<id> returns CEFAP signals & CTVE flags"))
        else:
            results.append(("Issue Detail API CEFAP Signals", False, "Missing signals or CTVE flags in get_issue endpoint"))

    # 4. Check renderCefapCard in static/js/dashboard.js
    dashboard_js_path = os.path.join("static", "js", "dashboard.js")
    if os.path.exists(dashboard_js_path):
        with open(dashboard_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "function renderCefapCard" in content and "cefap-card" in content:
            results.append(("Officer renderCefapCard JS", True, "renderCefapCard function defined in dashboard.js"))
        else:
            results.append(("Officer renderCefapCard JS", False, "renderCefapCard function missing in dashboard.js"))
    else:
        results.append(("Officer renderCefapCard JS", False, "static/js/dashboard.js not found"))

    # 5. Check #ctve-modal in templates
    t1 = os.path.join("templates", "report_issue.html")
    t2 = os.path.join("templates", "citizen", "dashboard.html")
    m1 = os.path.exists(t1) and "ctve-modal" in open(t1, "r", encoding="utf-8").read()
    m2 = os.path.exists(t2) and "ctve-modal" in open(t2, "r", encoding="utf-8").read()
    if m1 and m2:
        results.append(("Citizen CTVE Modal HTML", True, "#ctve-modal present in report_issue.html and citizen/dashboard.html"))
    else:
        results.append(("Citizen CTVE Modal HTML", False, f"#ctve-modal missing in templates (report_issue: {m1}, citizen/dashboard: {m2})"))

    # 6. Check #cefap-card in templates/officer/dashboard.html
    t_off = os.path.join("templates", "officer", "dashboard.html")
    if os.path.exists(t_off) and "cefap-card" in open(t_off, "r", encoding="utf-8").read():
        results.append(("Officer CEFAP Card HTML", True, "#cefap-card present in officer/dashboard.html"))
    else:
        results.append(("Officer CEFAP Card HTML", False, "#cefap-card missing in officer/dashboard.html"))

    # 7. Check CTVE JS functions in static/js/citizen.js
    citizen_js_path = os.path.join("static", "js", "citizen.js")
    if os.path.exists(citizen_js_path):
        with open(citizen_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        required_funcs = ["showCtveModal", "handleCtvePhotoUpload", "confirmCtveOriginal"]
        all_found = all(fn in content for fn in required_funcs)
        if all_found:
            results.append(("Citizen CTVE JS Logic", True, "showCtveModal, handleCtvePhotoUpload, confirmCtveOriginal present in citizen.js"))
        else:
            results.append(("Citizen CTVE JS Logic", False, "Missing CTVE functions in citizen.js"))
    else:
        results.append(("Citizen CTVE JS Logic", False, "static/js/citizen.js not found"))

    print("\nSUMMARY OF VERIFICATION RESULTS:")
    print("-" * 60)
    all_passed = True
    for name, status, msg in results:
        flag = "PASS" if status else "FAIL"
        if not status:
            all_passed = False
        print(f"[{flag}] {name}: {msg}")

    print("-" * 60)
    if all_passed:
        print("RESULT: ALL TESTS PASSED!")
        return 0
    else:
        print("RESULT: SOME TESTS FAILED!")
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
