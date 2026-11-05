import pytest
import jwt
from flask_socketio import SocketIO
from bson import ObjectId

from app import create_app, socketio, db

@pytest.fixture(scope="module")
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

@pytest.fixture(scope="module")
def test_users(app_instance):
    jwt_secret = app_instance.config["JWT_SECRET"]
    
    officer_id = str(ObjectId())
    citizen_id = str(ObjectId())
    other_citizen_id = str(ObjectId())
    
    officer_token = jwt.encode(
        {"user_id": officer_id, "role": "officer", "ward": "12"},
        jwt_secret,
        algorithm="HS256"
    )
    citizen_token = jwt.encode(
        {"user_id": citizen_id, "role": "citizen", "ward": "12"},
        jwt_secret,
        algorithm="HS256"
    )
    other_citizen_token = jwt.encode(
        {"user_id": other_citizen_id, "role": "citizen", "ward": "14"},
        jwt_secret,
        algorithm="HS256"
    )
    
    return {
        "officer": {"id": officer_id, "token": officer_token, "role": "officer", "ward": "12"},
        "citizen": {"id": citizen_id, "token": citizen_token, "role": "citizen", "ward": "12"},
        "other_citizen": {"id": other_citizen_id, "token": other_citizen_token, "role": "citizen", "ward": "14"}
    }

def test_unauthenticated_connection_rejected(app_instance):
    """Clients attempting to connect without a valid JWT are rejected immediately."""
    client = socketio.test_client(app_instance, namespace="/civic")
    assert not client.is_connected(namespace="/civic"), "Unauthenticated client should be rejected on connect"

def test_invalid_token_connection_rejected(app_instance):
    """Clients with corrupted or forged tokens are rejected."""
    client = socketio.test_client(app_instance, namespace="/civic", auth={"token": "forged.jwt.token"})
    assert not client.is_connected(namespace="/civic"), "Client with invalid token should be rejected"

def test_authenticated_connection_with_cookie_and_auth_payload(app_instance, test_users):
    """Clients connect successfully either via cookie or auth handshake payload."""
    officer = test_users["officer"]
    citizen = test_users["citizen"]
    
    # Via auth payload
    c_auth = socketio.test_client(app_instance, namespace="/civic", auth={"token": officer["token"]})
    assert c_auth.is_connected(namespace="/civic")
    c_auth.disconnect(namespace="/civic")
    
    # Via cookie
    c_cookie = socketio.test_client(
        app_instance,
        namespace="/civic",
        headers={"Cookie": f"access_token={citizen['token']}"}
    )
    assert c_cookie.is_connected(namespace="/civic")
    c_cookie.disconnect(namespace="/civic")

def test_auto_join_and_isolated_emergency_broadcast(app_instance, test_users):
    """
    On connect, users auto-join role and ward rooms.
    Emergency broadcast to role_officer is received by officer but NOT by citizen.
    Emergency payload contains sanitized public fields and no raw PII/citizen_id.
    """
    officer = test_users["officer"]
    citizen = test_users["citizen"]
    
    c_officer = socketio.test_client(app_instance, namespace="/civic", auth={"token": officer["token"]})
    c_citizen = socketio.test_client(app_instance, namespace="/civic", auth={"token": citizen["token"]})
    
    # Trigger emergency declaration logic
    from services.complaint_service import declare_emergency
    
    issue_doc = {
        "title": "Severe road sinkhole",
        "description": "Massive collapse at junction",
        "ward": "12",
        "citizen_id": ObjectId(citizen["id"]),
        "status": "submitted",
        "priority": "P1"
    }
    inserted_id = str(db.issues.insert_one(issue_doc).inserted_id)
    
    declare_emergency(inserted_id, officer["id"], "structural_failure")
    
    # Check messages received
    officer_msgs = c_officer.get_received(namespace="/civic")
    citizen_msgs = c_citizen.get_received(namespace="/civic")
    
    c_officer.disconnect(namespace="/civic")
    c_citizen.disconnect(namespace="/civic")
    
    emergency_events = [m for m in officer_msgs if m.get("name") == "emergency_declared"]
    assert len(emergency_events) >= 1, f"Officer did not receive emergency_declared: {officer_msgs}"
    
    payload = emergency_events[0]["args"][0]
    assert payload.get("emergency") is True
    assert payload.get("emergency_category") == "structural_failure"
    assert "citizen_id" not in payload, "Emergency payload MUST NOT leak citizen_id"
    
    # Citizen should NOT receive emergency_declared broadcast
    citizen_emergency = [m for m in citizen_msgs if m.get("name") == "emergency_declared"]
    assert len(citizen_emergency) == 0, f"Citizen should not receive emergency broadcast: {citizen_emergency}"

def test_targeted_notification_delivery(app_instance, test_users):
    """
    Notification sent to a specific user arrives in their user room
    and does not leak to other users. Event name is standardized to 'notification'.
    """
    citizen = test_users["citizen"]
    other = test_users["other_citizen"]
    
    c_citizen = socketio.test_client(app_instance, namespace="/civic", auth={"token": citizen["token"]})
    c_other = socketio.test_client(app_instance, namespace="/civic", auth={"token": other["token"]})
    
    from services.notification_service import create_notification
    create_notification(db, citizen["id"], "Test Alert", "Your issue was verified")
    
    citizen_msgs = c_citizen.get_received(namespace="/civic")
    other_msgs = c_other.get_received(namespace="/civic")
    
    c_citizen.disconnect(namespace="/civic")
    c_other.disconnect(namespace="/civic")
    
    cit_notifs = [m for m in citizen_msgs if m.get("name") == "notification"]
    assert len(cit_notifs) >= 1, f"Citizen should receive 'notification' event: {citizen_msgs}"
    assert cit_notifs[0]["args"][0]["title"] == "Test Alert"
    
    other_notifs = [m for m in other_msgs if m.get("name") == "notification"]
    assert len(other_notifs) == 0, f"Other user should not receive targeted notification: {other_msgs}"

def test_sla_breach_alert_received_by_officer(app_instance, test_users):
    """SLA breach emitted to role_officer on /civic namespace is received by officer."""
    officer = test_users["officer"]
    c_officer = socketio.test_client(app_instance, namespace="/civic", auth={"token": officer["token"]})
    
    socketio.emit(
        "sla_breach",
        {"issue_id": "TEST-ISSUE-123", "priority": "P0", "escalation_level": 2, "sla_hours": 4},
        room="role_officer",
        namespace="/civic"
    )
    
    msgs = c_officer.get_received(namespace="/civic")
    c_officer.disconnect(namespace="/civic")
    
    breaches = [m for m in msgs if m.get("name") == "sla_breach"]
    assert len(breaches) >= 1, f"Officer should receive sla_breach: {msgs}"
    assert breaches[0]["args"][0]["issue_id"] == "TEST-ISSUE-123"

def test_per_sid_rate_limiting_on_socket(app_instance, test_users):
    """Excessive client-to-server events from a single SID trigger rate limiting error."""
    citizen = test_users["citizen"]
    c_citizen = socketio.test_client(app_instance, namespace="/civic", auth={"token": citizen["token"]})
    
    for i in range(70):
        c_citizen.emit("join_room", {"room": f"ward_{citizen['ward']}"}, namespace="/civic")
        
    msgs = c_citizen.get_received(namespace="/civic")
    c_citizen.disconnect(namespace="/civic")
    
    errors = [m for m in msgs if m.get("name") == "error"]
    assert len(errors) >= 1, "Flooding socket events must trigger rate limit error"
    assert "Rate limit exceeded" in errors[0]["args"][0].get("message", "")

def test_health_endpoints(app_instance):
    """Both /health and /api/health return 200 with JSON status."""
    client = app_instance.test_client()
    
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert res1.get_json()["status"] == "healthy"
    
    res2 = client.get("/api/health")
    assert res2.status_code == 200
    assert res2.get_json()["status"] == "healthy"
