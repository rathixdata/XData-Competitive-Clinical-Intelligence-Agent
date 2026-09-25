"""Load profile for NFR-PERF-001 / NFR-SCL-001 (run against staging, never production).

    pip install locust
    XDATA_LT_TENANT=demo-oncology XDATA_LT_EMAIL=analyst@demo.example XDATA_LT_PASSWORD=... \
      locust -f deploy/loadtest/locustfile.py --host https://staging.xdata.example.com
Target: p95 < 2 s for dashboard / feed / event detail reads at 10x pilot volume.
"""

import os
import random

from locust import HttpUser, between, task


class Analyst(HttpUser):
    wait_time = between(1, 5)

    def on_start(self) -> None:
        r = self.client.post("/api/v1/auth/login", json={
            "tenant": os.environ["XDATA_LT_TENANT"], "email": os.environ["XDATA_LT_EMAIL"],
            "password": os.environ["XDATA_LT_PASSWORD"]})
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        self.event_ids = [e["id"] for e in self.client.get("/api/v1/events?limit=50").json().get("items", [])]

    @task(5)
    def feed(self) -> None:
        self.client.get("/api/v1/events?min_score=50&sort=score", name="/events [filtered]")

    @task(4)
    def event_detail(self) -> None:
        if self.event_ids:
            self.client.get(f"/api/v1/events/{random.choice(self.event_ids)}", name="/events/{id}")

    @task(3)
    def dashboard(self) -> None:
        self.client.get("/api/v1/dashboard")

    @task(1)
    def catalysts(self) -> None:
        self.client.get("/api/v1/catalysts")

    @task(1)
    def ask(self) -> None:
        self.client.post("/api/v1/ask", json={"question": "What changed this week?"}, name="/ask")
