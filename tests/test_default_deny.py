import pytest
from app import create_app

# Explicit Canonical Whitelist of Public Endpoints
# Any endpoint registered in Flask url_map that is NOT in this whitelist
# MUST be protected by an authentication decorator carrying `_is_auth_protected = True`.
PUBLIC_ENDPOINTS = {
    # Public Information & Transparency Pages
    "index",
    "login_page",
    "register_page",
    "transparency_page",
    "live_map_page",
    "health_check",
    "static",
    
    # Public APIs & Visualizations
    "analytics_api.get_public_stats",
    "map_api.get_public_map",

    # Public Authentication & Onboarding Routes
    "api_auth.login",
    "api_auth.logout",
    "api_auth.refresh",
    "api_auth.register",
    "api_auth.verify_ward",
    "api_mobile_auth.mobile_login",
    "auth.login",
    "auth.logout",
    "auth.refresh",
    "auth.register",
    "auth.verify_ward",
    "citizen.verify_ward_page",

    # Private Authenticated File Proxy (handles its own internal token/permission checks)
    "private_file",

    # Worker PWA Service Worker & Manifest
    "worker.pwa_manifest",
    "worker.service_worker"
}

@pytest.fixture(scope="module")
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

def test_default_deny_all_endpoints(app_instance):
    """
    Default-Deny Authorization Gate:
    Iterates through app.url_map and verifies that every single endpoint is either:
    1. Listed in the explicit PUBLIC_ENDPOINTS allowlist, OR
    2. Marked with `_is_auth_protected = True` via @require_auth, @require_role,
       @verified_required, @require_citizen_page, @require_officer_page, or @require_worker_page.
    """
    violations = []

    print("\n--- Canonical PUBLIC_ENDPOINTS Allowlist ---")
    for endpoint in sorted(PUBLIC_ENDPOINTS):
        print(f"  [PUBLIC] {endpoint}")
    print("-------------------------------------------\n")

    for rule in app_instance.url_map.iter_rules():
        endpoint = rule.endpoint
        view_func = app_instance.view_functions.get(endpoint)

        if not view_func:
            continue

        is_public = endpoint in PUBLIC_ENDPOINTS
        is_protected = getattr(view_func, "_is_auth_protected", False)

        if not is_public and not is_protected:
            violations.append(
                f"UNPROTECTED ENDPOINT: rule='{rule.rule}' endpoint='{endpoint}' function='{view_func.__name__}'"
            )

    assert not violations, (
        f"Default-Deny failure! {len(violations)} endpoint(s) lack authentication decorators "
        f"and are not in PUBLIC_ENDPOINTS allowlist:\n" + "\n".join(violations)
    )
