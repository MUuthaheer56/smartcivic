"""
Resident-verification flow tests for SmartCivic (v2).

Routes below come from a pasted third-party analysis of the repo
(routes/auth.py: manual_verify_user, verify-ward). I have NOT read the code
myself, so confirm each CONFIG value against routes/auth.py.

Flow under test:
  register -> PENDING -> authority sees pending -> approve/reject
  -> VERIFIED (full access) / REJECTED (blocked)

Run:  pytest -v test_resident_verification_flow.py
"""
import uuid
import pytest
from app import create_app   # adjust if your factory is named differently

# ----------------------------- CONFIG (edit me) -----------------------------
REGISTER_URL     = "/api/auth/register"
LOGIN_URL        = "/api/auth/login"
APPROVE_URL      = "/api/auth/users/{id}/approve"
VERIFY_URL       = "/api/auth/users/{id}/verify"     # same handler; reject payload below
REJECT_PAYLOAD   = {"action": "reject", "reason": "invalid proof"}   # CONFIRM in manual_verify_user
SELF_VERIFY_URL  = "/api/auth/verify-ward"           # resident area-code route
VALID_WARD_CODE  = "TST-0000"                        # a code that exists in your seed data
PENDING_LIST_URL = "/api/auth/users/pending"         # PROPOSED - does not exist yet
PROTECTED_URL    = "/api/citizen/issues"             # any verified-only resident function

RESIDENT_ROLE    = "citizen"
AUTHORITY_CREDS  = {"email": "officer@smartcivic.com", "password": "smartcivic123"}
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from app import limiter, db
    from routes.auth import hash_password
    app = create_app()
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.app_context():
        db.users.update_one(
            {"email": AUTHORITY_CREDS["email"]},
            {"$set": {
                "name": "Ward Officer",
                "email": AUTHORITY_CREDS["email"],
                "password_hash": hash_password(AUTHORITY_CREDS["password"]),
                "role": "officer",
                "ward": "Ward 1",
                "verified": True,
                "verification_status": "approved",
                "status": "active"
            }},
            upsert=True
        )
    return app.test_client()


def _tok(r):
    j = r.get_json() or {}
    return j.get("token") or j.get("access_token") or (j.get("data") or {}).get("token")


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


def _user(j):
    return j.get("user", j)


def _uid(u):
    return u.get("id") or u.get("_id") or u.get("user_id")


def _register(client):
    email = f"res_{uuid.uuid4().hex[:8]}@test.com"
    pw = "Str0ng!Pass#1"
    r = client.post(REGISTER_URL, json={"name": "Test Resident", "email": email,
                                         "password": pw, "role": RESIDENT_ROLE})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    return email, pw


def _login(client, email, pw=None, password=None):
    p = pw or password
    r = client.post(LOGIN_URL, json={"email": email, "password": p})
    return r, (r.get_json() or {})


def _authority(client):
    r, _ = _login(client, **AUTHORITY_CREDS)
    assert r.status_code == 200, "authority login failed - seed data missing?"
    return _tok(r)


def _pending_resident(client):
    """Returns (email, pw, resident_token, resident_id)."""
    email, pw = _register(client)
    r, j = _login(client, email, pw)
    return email, pw, _tok(r), _uid(_user(j))


# 1 ---- registration -------------------------------------------------------
def test_01_registration_creates_pending_account(client):
    email, pw = _register(client)
    _, j = _login(client, email, pw)
    u = _user(j)
    assert u.get("verified") is False
    assert u.get("verification_status") == "pending"
    assert u.get("status") == "pending_verification"


def test_02_login_returns_role_and_verified(client):
    email, pw = _register(client)
    _, j = _login(client, email, pw)
    u = _user(j)
    assert "role" in u and "verified" in u


# 2 ---- pending residents are blocked ---------------------------------------
def test_03_pending_resident_blocked_from_protected_functions(client):
    _, _, tok, _ = _pending_resident(client)
    assert client.get(PROTECTED_URL, headers=_hdr(tok)).status_code in (401, 403)


# 3 ---- authority queue (expected to FAIL until the list endpoint/UI exists) -
def test_04_authority_sees_pending_residents(client):
    email, _, _, rid = _pending_resident(client)
    a = _authority(client)
    r = client.get(PENDING_LIST_URL, headers=_hdr(a))
    assert r.status_code == 200, "no pending-residents endpoint yet - build it"
    body = r.get_json()
    items = body if isinstance(body, list) else (body or {}).get("users", [])
    assert any(i.get("email") == email for i in items)


# 4 ---- approve --------------------------------------------------------------
def test_05_authority_approve_makes_resident_verified(client):
    email, pw, _, rid = _pending_resident(client)
    a = _authority(client)
    assert client.post(APPROVE_URL.format(id=rid), headers=_hdr(a)).status_code == 200
    r, j = _login(client, email, pw)
    u = _user(j)
    assert u["verified"] is True
    assert u["verification_status"] == "approved"
    assert u["status"] == "active"


def test_06_verified_resident_can_use_protected_functions(client):
    email, pw, _, rid = _pending_resident(client)
    client.post(APPROVE_URL.format(id=rid), headers=_hdr(_authority(client)))
    r, _ = _login(client, email, pw)
    assert client.get(PROTECTED_URL, headers=_hdr(_tok(r))).status_code == 200


# 5 ---- reject ---------------------------------------------------------------
def test_07_authority_reject_keeps_resident_blocked(client):
    email, pw, _, rid = _pending_resident(client)
    a = _authority(client)
    assert client.post(VERIFY_URL.format(id=rid), headers=_hdr(a),
                       json=REJECT_PAYLOAD).status_code == 200
    r, j = _login(client, email, pw)
    u = _user(j)
    assert u["verified"] is False
    assert u["verification_status"] == "rejected"
    assert u["status"] == "rejected"
    if r.status_code == 200:
        assert client.get(PROTECTED_URL, headers=_hdr(_tok(r))).status_code in (401, 403)


# 6 ---- authorization --------------------------------------------------------
def test_08_resident_cannot_approve_anyone(client):
    _, _, tok, rid = _pending_resident(client)
    assert client.post(APPROVE_URL.format(id=rid), headers=_hdr(tok)).status_code in (401, 403)


def test_09_unauthenticated_cannot_approve(client):
    assert client.post(APPROVE_URL.format(id="x")).status_code in (401, 403)


def test_10_cannot_self_register_as_verified(client):
    email = f"evil_{uuid.uuid4().hex[:8]}@test.com"
    client.post(REGISTER_URL, json={"name": "E", "email": email, "password": "Str0ng!Pass#1",
                                     "role": RESIDENT_ROLE, "verified": True,
                                     "verification_status": "approved", "status": "active"})
    _, j = _login(client, email, "Str0ng!Pass#1")
    assert _user(j).get("verified") is not True


def test_11_cannot_self_register_as_officer(client):
    email = f"evil_{uuid.uuid4().hex[:8]}@test.com"
    client.post(REGISTER_URL, json={"name": "E", "email": email,
                                     "password": "Str0ng!Pass#1", "role": "officer"})
    _, j = _login(client, email, "Str0ng!Pass#1")
    assert _user(j).get("role") != "officer"


# 7 ---- the flow-violation check --------------------------------------------
def test_12_resident_cannot_self_verify_with_ward_code(client):
    """Your flow says ONLY an authority verifies. If this fails, the ward-code
    route is a bypass: decide to remove it, or make it only pre-fill the
    ward and still leave the account PENDING."""
    email, pw, tok, _ = _pending_resident(client)
    client.post(SELF_VERIFY_URL, headers=_hdr(tok), json={"ward_code": VALID_WARD_CODE})
    r, j = _login(client, email, pw)
    assert _user(j).get("verified") is not True, "resident self-verified without authority"


# 8 ---- robustness -----------------------------------------------------------
def test_13_double_approve_never_500(client):
    _, _, _, rid = _pending_resident(client)
    a = _authority(client)
    client.post(APPROVE_URL.format(id=rid), headers=_hdr(a))
    again = client.post(APPROVE_URL.format(id=rid), headers=_hdr(a))
    assert again.status_code in (200, 400, 409)
