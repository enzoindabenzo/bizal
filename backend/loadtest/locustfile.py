"""
BizAL — Multi-Tenant Load Test (Locust)
=========================================

Purpose
-------
Answers the "performance" arm of the thesis research question: does the
multi-tenant architecture hold up (response time, error rate) as the number
of concurrently-active tenants grows? This is the piece that was completely
missing from the project before this file — the other three arms (onboarding
time, data isolation, usability) already had evidence; this is the fourth.

What it simulates
------------------
Each Locust "user" is pinned to ONE tenant subdomain for its whole session
(via HTTP Host header spoofing — no real DNS/wildcard subdomain needed to
run this) and repeatedly hits a realistic mix of read-heavy storefront
endpoints, occasionally writing (booking creation, review submission). This
mirrors real traffic: many browsers reading a menu/catalogue, few visitors
actually completing a booking.

Run it
-------
    cd backend
    pip install locust
    python manage.py runserver 0.0.0.0:8000          # in one terminal
    locust -f loadtest/locustfile.py --host=http://localhost:8000

Then open http://localhost:8089, set number of users (e.g. 50) and spawn
rate (e.g. 5/s), and start. Locust reports p50/p95/p99 response time,
requests/sec, and failure rate live, and you can export a CSV/HTML report
at the end for the thesis writeup.

To specifically test "does one busy tenant slow down another" (the
noisy-neighbour question implied by "performance" + "data isolation" in the
research question), run two separate Locust processes: one hammering a
single tenant with WriteHeavyTenantUser, another timing plain GETs against a
different tenant, and compare that second tenant's response times with vs.
without the first process running.
"""

import random

from locust import HttpUser, task, between, tag


# Seeded tenants from backend/seed.py — mix of business types and plans so
# the load test exercises different feature sets (menu vs. rooms vs. cars),
# not just one code path repeated.
TENANT_SLUGS = [
    "restorant-adriatiku",   # restaurant, Pro — menu + bookings
    "hertz-albania",         # car rental, Enterprise — rentals + chatbot
    "klinika-shendeti",      # clinic, Pro — appointments
    "hotel-riviera",         # hotel, Enterprise — rooms + seasonal pricing
    "market-express",        # retail, Starter — inventory/products
    "barber-kings-tirana",   # services
]


def tenant_host(slug: str) -> dict:
    """Host header that makes TenantMiddleware resolve to `slug` without
    needing real wildcard DNS — matches how the test suite itself fakes
    subdomains (see backend/tenants/tests.py, HTTP_HOST=<slug>.bizal.al)."""
    return {"Host": f"{slug}.bizal.al"}


class ReadHeavyTenantUser(HttpUser):
    """The common case: a visitor browsing one tenant's storefront.
    Weighted much higher than the write-heavy user below, since in
    practice most traffic to any given tenant is anonymous browsing, not
    checkout — this is what "performance under load" should mostly be
    measured against.
    """

    weight = 8
    wait_time = between(1, 3)

    def on_start(self):
        self.slug = random.choice(TENANT_SLUGS)
        self.headers = tenant_host(self.slug)

    @task(5)
    @tag("read")
    def view_storefront_home(self):
        self.client.get(
            "/api/storefront/pages/",
            headers=self.headers,
            name="/api/storefront/pages/ [tenant]",
        )

    @task(4)
    @tag("read")
    def view_tenant_info(self):
        # NOTE: /api/tenants/me/ is owner-only (auth required) — public
        # storefront visitors hit /api/tenants/info/ instead, which is what
        # the SPA shell actually calls on page load to render branding.
        self.client.get(
            "/api/tenants/info/",
            headers=self.headers,
            name="/api/tenants/info/ [tenant]",
        )

    @task(3)
    @tag("read")
    def browse_reviews(self):
        self.client.get(
            "/api/reviews/",
            headers=self.headers,
            name="/api/reviews/ [tenant]",
        )

    @task(2)
    @tag("read")
    def browse_menu_or_catalogue(self):
        # /api/menu/ (MenuListView) is the public read; /api/menu/categories/
        # is actually an owner-only manage endpoint (POST), so it's excluded
        # here — hitting it as a GET would just measure 401s, not real load.
        self.client.get(
            "/api/menu/",
            headers=self.headers,
            name="/api/menu/ [tenant]",
        )


class WriteHeavyTenantUser(HttpUser):
    """The rarer but more expensive case: someone actually submitting a
    booking. Kept as a separate, lower-weight user class so its load can be
    isolated/scaled independently when testing the noisy-neighbour
    question described in the module docstring.
    """

    weight = 2
    wait_time = between(2, 5)

    def on_start(self):
        self.slug = random.choice(TENANT_SLUGS)
        self.headers = tenant_host(self.slug)

    @task
    @tag("write")
    def submit_booking_request(self):
        # Matches Booking model + BookingSerializer fields exactly (see
        # bookings/models.py, bookings/serializers.py) — booking_type is a
        # real choice field, guest_* is how anonymous (non-registered)
        # bookings identify themselves.
        payload = {
            "booking_type": "table_reservation",
            "guest_name": f"Load Test {random.randint(1, 100000)}",
            "guest_email": f"loadtest{random.randint(1, 100000)}@example.com",
            "guest_phone": "+355691234567",
            "guest_count": random.randint(1, 6),
            "notes": "locust load test — safe to ignore/delete",
        }
        self.client.post(
            "/api/bookings/",
            json=payload,
            headers=self.headers,
            name="/api/bookings/ [tenant, POST]",
        )


class MainDomainUser(HttpUser):
    """Traffic that never touches a tenant at all — landing page, signup
    flow discovery. Included because the research question is about the
    platform as a whole, not just tenant storefronts, and main-domain
    requests skip the tenant-resolution branch of the middleware entirely
    — useful as a baseline to compare tenant-request overhead against.
    """

    weight = 1
    wait_time = between(2, 4)

    @task
    @tag("read")
    def view_landing_page(self):
        self.client.get("/health/", name="/health/ [main domain]")
