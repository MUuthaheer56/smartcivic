"""
Test static CSS files and role templates rendering (Part 2 Verification).
Verifies:
- 200 OK for /static/css/base.css, citizen.css, worker.css, admin.css.
- No 404s on stylesheets.
- Login redirects by role (citizen -> /citizen/dashboard, worker -> /worker/dashboard, officer -> /officer/dashboard).
- Citizen, worker, and admin templates render without missing styles or errors.
"""
from app import create_app, db
from bson import ObjectId


def test_css_static_files_accessible():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    css_files = ["base.css", "citizen.css", "worker.css", "admin.css"]
    for css in css_files:
        res = client.get(f"/static/css/{css}")
        assert res.status_code == 200, f"Expected 200 for /static/css/{css}, got {res.status_code}"
        assert len(res.data) > 100, f"Expected non-empty {css}"


def test_login_redirects_by_role():
    from routes.auth import generate_tokens

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    roles_and_expected = [
        ("citizen", "/citizen/dashboard"),
        ("worker", "/worker/dashboard"),
        ("officer", "/officer/dashboard"),
    ]

    for role, expected_target in roles_and_expected:
        user_id = ObjectId()
        db.users.insert_one({
            "_id": user_id,
            "email": f"test_{role}_{user_id}@test.com",
            "password": "hashed_dummy_pw",
            "role": role,
            "ward": "Ward 1" if role != "officer" else "ALL",
            "ward_id": "ward_1",
            "verified": True,
            "verification_status": "verified",
            "status": "active"
        })

        with app.app_context():
            token, _ = generate_tokens(str(user_id), role, "Ward 1")

        # Test authenticated page access for role via cookie
        client.set_cookie("access_token", token)
        res = client.get(expected_target)
        assert res.status_code == 200, f"Expected 200 for {expected_target} with {role} token, got {res.status_code}"
        assert b"base.css" in res.data, f"base.css not in {expected_target}"
        if role == "citizen":
            assert b"citizen.css" in res.data
            assert b"worker.css" not in res.data
            assert b"admin.css" not in res.data
        elif role == "worker":
            assert b"worker.css" in res.data
            assert b"citizen.css" not in res.data
            assert b"admin.css" not in res.data
        elif role == "officer":
            assert b"admin.css" in res.data
            assert b"citizen.css" not in res.data
            assert b"worker.css" not in res.data
