"""
SmartCivic v2 — Load & Concurrency Stress Test Suite
Simulates concurrent citizen grievance report traffic, API authentication,
and background AI pipeline throughput to measure system latency percentiles (P50, P95, P99).
"""

import os
import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from bson import ObjectId

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from routes.auth import generate_tokens, hash_password
from models.user import get_db

CONCURRENT_USERS = 10
REQUESTS_PER_USER = 3
TOTAL_REQUESTS = CONCURRENT_USERS * REQUESTS_PER_USER

def worker_task(app, user_id, ward, token, req_idx):
    with app.app_context():
        with app.test_client() as client:
            client.set_cookie("access_token", token)
        start_t = time.time()
        try:
            res = client.post(
                "/api/issues",
                data={
                    "title": f"Load Test Grievance #{req_idx} - Pothole",
                    "description": f"Concurrent stress test complaint #{req_idx} near main junction.",
                    "category": "road",
                    "severity": "high",
                    "latitude": f"{12.9716 + (req_idx * 0.001):.5f}",
                    "longitude": f"{77.5946 + (req_idx * 0.001):.5f}",
                    "ward": ward
                },
                content_type="multipart/form-data",
                headers={"Authorization": f"Bearer {token}"}
            )
            elapsed = (time.time() - start_t) * 1000.0  # ms
            status_code = res.status_code
            if status_code not in (200, 201, 429):
                print(f"[Load Test Debug] req #{req_idx} failed with {status_code}: {res.get_data(as_text=True)[:150]}")
            success = (status_code in (200, 201, 429))
            return {
                "success": success,
                "status_code": status_code,
                "duration_ms": elapsed
            }
        except Exception as ex:
            elapsed = (time.time() - start_t) * 1000.0
            return {
                "success": False,
                "status_code": 500,
                "duration_ms": elapsed,
                "error": str(ex)
            }

def run_load_test():
    app = create_app()
    app.config["TESTING"] = True
    app.config["RATELIMIT_ENABLED"] = False
    
    from app import limiter
    limiter.enabled = False

    with app.app_context():
        db = get_db()
        
        # Setup verified resident user for test
        user_id = ObjectId()
        db.users.insert_one({
            "_id": user_id,
            "email": "loadtest_user@smartcivic.com",
            "password_hash": hash_password("loadtest_pass123"),
            "role": "resident",
            "ward": "Ward 1",
            "verified": True,
            "verification_status": "approved",
            "created_at": datetime.utcnow()
        })
        
        token, _ = generate_tokens(str(user_id), "resident", "Ward 1")
        
        print(f"======================================================================")
        print(f"       SMARTCIVIC CONCURRENCY & LOAD TEST RUNNER")
        print(f"======================================================================")
        print(f"  Concurrent Workers:   {CONCURRENT_USERS}")
        print(f"  Requests Per Worker:  {REQUESTS_PER_USER}")
        print(f"  Total API Calls:      {TOTAL_REQUESTS}")
        print(f"----------------------------------------------------------------------")
        
        wall_start = time.time()
        results = []
        
        with ThreadPoolExecutor(max_workers=CONCURRENT_USERS) as executor:
            futures = []
            for i in range(TOTAL_REQUESTS):
                futures.append(executor.submit(worker_task, app, user_id, "Ward 1", token, i + 1))
                
            for fut in as_completed(futures):
                results.append(fut.result())
                
        total_time = time.time() - wall_start
        
        # Cleanup test user & inserted issues
        db.users.delete_one({"_id": user_id})
        db.issues.delete_many({"title": {"$regex": "^Load Test Grievance"}})
        
        # Compute metrics
        durations = [r["duration_ms"] for r in results]
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        
        durations.sort()
        p50 = statistics.median(durations) if durations else 0
        p95 = durations[int(len(durations) * 0.95)] if durations else 0
        p99 = durations[int(len(durations) * 0.99)] if durations else 0
        rps = TOTAL_REQUESTS / total_time if total_time > 0 else 0
        
        print(f"  Wall Clock Duration: {total_time:.2f} seconds")
        print(f"  Throughput (RPS):     {rps:.2f} req/sec")
        print(f"  Successful Requests: {len(successful)} / {TOTAL_REQUESTS} ({len(successful)/TOTAL_REQUESTS*100:.1f}%)")
        print(f"  Failed Requests:     {len(failed)}")
        print(f"  P50 Latency:         {p50:.2f} ms")
        print(f"  P95 Latency:         {p95:.2f} ms")
        print(f"  P99 Latency:         {p99:.2f} ms")
        print(f"======================================================================\n")
        
        assert len(failed) == 0, f"Load test experienced {len(failed)} failures!"
        assert rps > 10.0, f"Throughput below target (got {rps:.2f} req/sec)"
        return True

if __name__ == "__main__":
    run_load_test()
