"""
SmartCivic v2 — Standard Locust Load & Performance Benchmark File
Run headless with bounded execution limits:
  locust -f qa/locustfile.py --headless -u 10 -r 2 --run-time 1m --host http://localhost:5000
"""

import time
import secrets
from locust import HttpUser, task, between

class SmartCivicLoadTestUser(HttpUser):
    # Safe wait boundaries between consecutive user requests
    wait_time = between(1, 3)

    def on_start(self):
        """User login setup."""
        self.client.post("/auth/login", json={
            "email": "uat_citizen@smartcivic.com",
            "password": "citizen_pass123"
        })

    @task(3)
    def view_public_map(self):
        self.client.get("/api/public/map")

    @task(2)
    def get_user_issues(self):
        self.client.get("/api/issues")

    @task(1)
    def submit_issue(self):
        self.client.post(
            "/api/issues",
            data={
                "title": f"Locust Load Test Report {secrets.token_hex(4)}",
                "description": "Automated stress benchmark grievance report.",
                "category": "road",
                "severity": "medium",
                "latitude": "12.9716",
                "longitude": "77.5946",
                "ward": "Ward 1"
            },
            headers={"Accept": "application/json"}
        )
