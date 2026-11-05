import os
import json
import pytest
from datetime import datetime, timedelta
from bson import ObjectId

from app import create_app, db
from routes.auth import generate_tokens
from services.forecast_service import (
    compute_moving_average_forecast,
    compute_seasonal_naive_forecast,
    generate_forecast,
    get_ward_forecasts_summary
)
from services.civicpulse_service import (
    _build_health_timeline,
    compute_civicpulse_predictions
)
from ml.evaluate.eval_forecast import evaluate_forecasting, run_rolling_origin_backtest

@pytest.fixture
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

@pytest.fixture
def test_client(app_instance):
    return app_instance.test_client()

def test_moving_average_and_seasonal_naive_baselines():
    """Validates baseline calculations for moving average and seasonal naive."""
    # 1. Moving average baseline
    history = [10.0, 20.0, 30.0, 40.0]
    ma3 = compute_moving_average_forecast(history, window=3)
    assert ma3 == 30.0  # (20 + 30 + 40) / 3

    # Empty history fallback
    assert compute_moving_average_forecast([], window=3) == 0.0

    # 2. Seasonal naive baseline (lag 12)
    history_24m = [float(i + 1) for i in range(24)]
    sn = compute_seasonal_naive_forecast(history_24m, season_lag=12)
    assert sn == 13.0  # 12 months prior to end of 24 months (index 12 is 13.0)

    # Short history fallback
    history_short = [15.0, 25.0]
    assert compute_seasonal_naive_forecast(history_short, season_lag=12) == 25.0

def test_generate_forecast_and_wording_invariant(app_instance):
    """
    Validates forecast generation, persistence into db.forecasts,
    and strict wording invariant: 'expected reporting volume', never 'predicted failures'.
    """
    with app_instance.app_context():
        ward = "Ward 1"
        cat = "roads"

        # Insert sample complaints across months
        now = datetime.utcnow()
        for i in range(5):
            db.issues.insert_one({
                "ward": ward,
                "category": cat,
                "status": "submitted",
                "created_at": now - timedelta(days=30 * i)
            })

        forecast = generate_forecast(db, ward_id=ward, category=cat, horizon_months=1)
        assert forecast is not None
        assert "expected_reporting_volume" in forecast
        assert forecast["metric_description"] == "expected reporting volume"
        assert "confidence_interval" in forecast

        # Terminology check: strictly NO "predicted failures"
        serialized = json.dumps(forecast, default=str)
        assert "predicted failures" not in serialized.lower()

        # Check persistence in db.forecasts
        stored = db.forecasts.find_one({"ward_id": ward, "category": cat})
        assert stored is not None
        assert stored["expected_reporting_volume"] == forecast["expected_reporting_volume"]

def test_rolling_origin_backtest_refusal_on_short_data(app_instance):
    """
    CRITICAL EXIT GATE INVARIANT:
    Refuses to evaluate non-synthetic production history under 12 months.
    """
    with app_instance.app_context():
        result = evaluate_forecasting(use_synthetic_benchmark=False)
        assert result["success"] is False
        assert result["error"] == "insufficient_history"
        assert ">= 12 months" in result["refusal_reason"]

def test_rolling_origin_backtest_synthetic_benchmark(app_instance):
    """Validates rolling-origin backtest execution on 24-month benchmark."""
    with app_instance.app_context():
        result = evaluate_forecasting(use_synthetic_benchmark=True)
        assert result is not None
        assert "results" in result
        assert "MAE_Weighted_Ensemble" in result["results"]
        assert result["synthetic"] is True
        assert result["history_months_used"] >= 12

def test_civicpulse_real_repair_dates_incorporation(app_instance):
    """
    Validates that CivicPulse decay timeline incorporates real repair dates from resolved issues.
    """
    with app_instance.app_context():
        segment_id = f"seg_test_{ObjectId()}"
        now = datetime.utcnow()

        # Create resolved complaint with real repair date
        cid = str(ObjectId())
        db.issues.insert_one({
            "_id": ObjectId(cid),
            "infrastructure_segment_id": segment_id,
            "status": "closed",
            "created_at": now - timedelta(days=20),
            "resolved_at": now - timedelta(days=10) # real repair date 10 days later
        })

        # Insert repair evidence for that issue
        db.repair_evidence.insert_one({
            "issue_id": cid,
            "created_at": now - timedelta(days=10),
            "verdict": "repaired",
            "confidence": 0.95
        })

        timeline = _build_health_timeline(segment_id)
        assert len(timeline) >= 2
        # Timeline includes initial complaint event and subsequent repair restitution event
        first_event = timeline[0]
        second_event = timeline[1]
        assert second_event[0] > first_event[0]  # repair occurred after report

def test_analytics_forecasts_endpoint_rbac(app_instance, test_client):
    """Verifies RBAC and response format for GET /api/analytics/forecasts."""
    with app_instance.app_context():
        # 1. Unauthenticated -> 401
        res_anon = test_client.get("/api/analytics/forecasts")
        assert res_anon.status_code == 401

        # 2. Citizen -> 403 Forbidden
        cid = str(ObjectId())
        db.users.update_one({"_id": ObjectId(cid)}, {"$set": {"email": f"c_{cid}@test.com", "role": "citizen"}}, upsert=True)
        c_token, _ = generate_tokens(cid, "citizen", "Ward 1")
        res_cit = test_client.get("/api/analytics/forecasts", headers={"Authorization": f"Bearer {c_token}"})
        assert res_cit.status_code == 403

        # 3. Officer -> 200 OK
        oid = str(ObjectId())
        db.users.update_one({"_id": ObjectId(oid)}, {"$set": {"email": f"o_{oid}@test.com", "role": "officer"}}, upsert=True)
        o_token, _ = generate_tokens(oid, "officer", "all")
        res_off = test_client.get("/api/analytics/forecasts?ward=Ward%201&category=roads", headers={"Authorization": f"Bearer {o_token}"})
        assert res_off.status_code == 200
        data = res_off.get_json()
        assert data["success"] is True
        assert data["metric_description"] == "expected reporting volume"
        assert "current_forecast" in data
