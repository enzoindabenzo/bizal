# health_only_locustfile.py
# Isolates the web tier from the DB entirely: hits ONLY /health/,
# nothing that touches Postgres, Redis, or Celery. If this stays fast
# under 1000 concurrent users, worker capacity is NOT the ceiling — the
# bookings-run slowdown must come from something DB/lock related instead.

from locust import HttpUser, task, between

class HealthOnlyUser(HttpUser):
    wait_time = between(0.5, 1.5)

    @task
    def health(self):
        self.client.get("/health/", headers={"Host": "bizal.al"})