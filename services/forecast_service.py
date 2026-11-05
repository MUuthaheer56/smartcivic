"""
SmartCivic — Forecasting & Demand Analytics Service
Provides predictive modeling for municipal civic operations.
Forecasts are strictly framed as expected reporting demand / volume, NEVER as predicted failures.
Implements:
1. Moving Average Baseline (MA-3 / MA-6)
2. Seasonal Naive Baseline (same month prior seasonal cycle)
3. Tree-based ML Model (Random Forest / XGBoost with calendar features)
Stores runs in db.forecasts with method and horizon.
"""
import os
import math
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from app import db
from services.ai.envelope import make_ai_result

logger = logging.getLogger(__name__)

CATEGORIES = ["roads", "water", "electricity", "sanitation", "storm_drainage"]
DEFAULT_HORIZON_MONTHS = 1


def compute_moving_average_forecast(history: List[float], window: int = 3) -> float:
    """Computes simple moving average baseline over the last k periods."""
    if not history:
        return 0.0
    k = min(len(history), window)
    return float(np.mean(history[-k:]))


def compute_seasonal_naive_forecast(history: List[float], season_lag: int = 12) -> float:
    """Computes seasonal naive baseline (same month from prior cycle)."""
    if not history:
        return 0.0
    if len(history) >= season_lag:
        return float(history[-season_lag])
    # Fallback to last observed period if history < seasonal cycle
    return float(history[-1])


def extract_calendar_features(year: int, month: int, lag_history: List[float]) -> Dict[str, float]:
    """Generates feature dict for ML demand forecast."""
    quarter = (month - 1) // 3 + 1
    is_monsoon = 1.0 if 6 <= month <= 9 else 0.0

    l1 = lag_history[-1] if len(lag_history) >= 1 else 0.0
    l2 = lag_history[-2] if len(lag_history) >= 2 else l1
    l3 = lag_history[-3] if len(lag_history) >= 3 else l2
    roll_3 = float(np.mean([l1, l2, l3])) if lag_history else 0.0

    return {
        "month": float(month),
        "quarter": float(quarter),
        "is_monsoon": is_monsoon,
        "lag_1": float(l1),
        "lag_2": float(l2),
        "lag_3": float(l3),
        "rolling_mean_3": round(roll_3, 2)
    }


def get_monthly_complaint_series(db_conn, ward_id: str, category: str) -> List[Dict[str, Any]]:
    """
    Extracts monthly complaint counts from db.issues for (ward_id, category).
    Returns list of dicts: [{"year": y, "month": m, "count": c}, ...] sorted ascending.
    """
    match_q: Dict[str, Any] = {}
    if ward_id and ward_id not in ["all", "*"]:
        match_q["$or"] = [
            {"ward": ward_id},
            {"ward_id": ward_id},
            {"location.ward": ward_id}
        ]
    if category and category not in ["all", "*"]:
        match_q["category"] = {"$in": [category, category.lower()]}

    pipeline = [
        {"$match": match_q} if match_q else {"$match": {}},
        {
            "$project": {
                "created_at": {
                    "$cond": [
                        {"$eq": [{"$type": "$created_at"}, "date"]},
                        "$created_at",
                        {"$dateFromString": {"dateString": "$created_at", "onError": datetime.utcnow()}}
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$created_at"},
                    "month": {"$month": "$created_at"}
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id.year": 1, "_id.month": 1}}
    ]

    try:
        agg = list(db_conn.issues.aggregate(pipeline))
        series = [
            {"year": item["_id"]["year"], "month": item["_id"]["month"], "count": item["count"]}
            for item in agg if item.get("_id") and item["_id"].get("year")
        ]
        return series
    except Exception as e:
        logger.warning(f"[ForecastService] Aggregation error: {e}")
        return []


def generate_forecast(db_conn,
                      ward_id: str,
                      category: str,
                      horizon_months: int = DEFAULT_HORIZON_MONTHS,
                      method: str = "ensemble") -> Dict[str, Any]:
    """
    Generates expected reporting volume forecast for a given ward and category.
    Supports 'moving_average', 'seasonal_naive', 'ml_tree', or 'ensemble'.
    Persists result into db.forecasts.
    """
    series = get_monthly_complaint_series(db_conn, ward_id, category)
    counts = [item["count"] for item in series]

    now = datetime.utcnow()
    target_year = now.year
    target_month = now.month + horizon_months
    if target_month > 12:
        target_year += (target_month - 1) // 12
        target_month = ((target_month - 1) % 12) + 1

    # 1. Baseline predictions
    ma_val = compute_moving_average_forecast(counts, window=3)
    sn_val = compute_seasonal_naive_forecast(counts, season_lag=12)

    # 2. ML Tree Model prediction
    if len(counts) >= 6:
        # Fit a quick regressor on historical lags
        X_train, y_train = [], []
        for i in range(3, len(series)):
            lags = [series[j]["count"] for j in range(i)]
            feat = extract_calendar_features(series[i]["year"], series[i]["month"], lags)
            X_train.append(list(feat.values()))
            y_train.append(series[i]["count"])

        reg = RandomForestRegressor(n_estimators=30, max_depth=3, random_state=42)
        reg.fit(X_train, y_train)

        target_feat = extract_calendar_features(target_year, target_month, counts)
        ml_val = float(reg.predict([list(target_feat.values())])[0])
    else:
        # If history too short, default to moving average
        ml_val = ma_val

    # Select final expected volume by method
    if method == "moving_average":
        expected_vol = round(ma_val, 2)
    elif method == "seasonal_naive":
        expected_vol = round(sn_val, 2)
    elif method == "ml_tree":
        expected_vol = round(max(0.0, ml_val), 2)
    else:  # ensemble: weighted blend
        expected_vol = round(max(0.0, 0.5 * ml_val + 0.3 * ma_val + 0.2 * sn_val), 2)

    # Uncertainty range (95% CI approximation)
    std_err = float(np.std(counts)) if len(counts) > 2 else max(1.0, expected_vol * 0.2)
    ci_lower = round(max(0.0, expected_vol - 1.96 * (std_err / math.sqrt(max(1, len(counts))))), 2)
    ci_upper = round(expected_vol + 1.96 * (std_err / math.sqrt(max(1, len(counts)))), 2)

    forecast_doc = {
        "ward_id": str(ward_id),
        "category": str(category),
        "method": method,
        "horizon_months": horizon_months,
        "target_period": f"{target_year}-{target_month:02d}",
        "expected_reporting_volume": expected_vol,
        "metric_description": "expected reporting volume",
        "confidence_interval": {"lower": ci_lower, "upper": ci_upper},
        "baselines": {
            "moving_average_3m": round(ma_val, 2),
            "seasonal_naive": round(sn_val, 2),
            "ml_tree": round(ml_val, 2)
        },
        "history_months_count": len(series),
        "synthetic": len(series) < 12,  # Flagged synthetic if data history is short
        "computed_at": now.isoformat()
    }

    # Upsert into db.forecasts
    db_conn.forecasts.update_one(
        {
            "ward_id": str(ward_id),
            "category": str(category),
            "target_period": forecast_doc["target_period"]
        },
        {"$set": forecast_doc},
        upsert=True
    )

    return forecast_doc


def get_ward_forecasts_summary(db_conn, ward_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves latest expected reporting volume forecasts for display on officer dashboard.
    Wording: 'expected reporting volume'.
    """
    q: Dict[str, Any] = {}
    if ward_id and ward_id not in ["all", "*"]:
        q["ward_id"] = str(ward_id)

    forecasts = list(db_conn.forecasts.find(q, {"_id": 0}).sort("computed_at", -1))
    return forecasts
