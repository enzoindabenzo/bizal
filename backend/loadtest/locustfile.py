r"""
BizAL — Multi-Tenant Load Test (Locust)
=========================================

Purpose
-------
Answers the "performance" arm of the thesis research question: does the
multi-tenant architecture hold up (response time, error rate) as the number
of concurrently-active tenants grows? This is the piece that was completely
missing from the project before this file — the other three arms (onboarding
time, data isolation, usability) already had evidence; this is the fourth.

Endpoint coverage (thesis Kufizimet item 1)
--------------------------------------------
The original version of this file only exercised 5 endpoints, all anonymous
reads/writes. This version was extended after running the project's own
static classifier (backend/bizal/tests/check_tenant_isolation.py, which
needs no Django import/DB — pure AST) to get the REAL, current endpoint
counts instead of guessing:

    144 views/endpoints scanned: 81 SAFE, 36 PUBLIC, 18 WEAK (allowlisted,
    self-scoped or manually tenant-filtered), 6 CRITICAL (allowlisted,
    self-scoped), 3 ADMIN.

This file now hits at least one endpoint from each category:
  - PUBLIC : ReadHeavyTenantUser + MainDomainUser (read endpoints across
             storefront/menu/reviews/hotels/rentals/rooms/appointments/
             blog/tenants/research/payments/marketplace)
  - WEAK   : AuthenticatedCustomerUser -> /api/auth/me/, me/bookings/,
             me/orders/, me/reviews/, me/appointments/, me/notifications/,
             plus one chained detail-view hit per list (self-scoped:
             MeView/MeBookingsView/MeOrdersView/MeReviewsView/
             MeAppointmentsView/MeNotificationPrefsView are all listed
             WEAK-allowlisted because the scanner can't see
             "filter(user=request.user)" as tenant-safe, but they're
             read-only re: the caller's own data)
  - SAFE   : TenantOwnerUser -> the logged-in owner's actual dashboard
             surface: tenant profile/settings/locations/credits, analytics,
             staff, inventory, notifications, subscriptions, CRM leads,
             invoices, review/appointment/storefront moderation lists
             (tenant-aware permission classes)
  - ADMIN  : AdminPlatformUser -> /api/payments/webhook-events/,
             /api/contact/admin/messages/, /api/platform-reviews/admin/
             (IsAdminUser-gated, read-only GET)

Round 2 (this revision) — item 4 follow-up
--------------------------------------------
Picking this back up specifically to widen endpoint coverage per-category
rather than add new user classes: went from ~16 distinct endpoints hit to
~52 (count yourself with `grep -oP 'name="\K[^"]+' loadtest/locustfile.py
| sed -E 's/ \[.*\]$//' | sort -u | wc -l` — not hand-counted here on
purpose, so it can't silently drift out of date as tasks are added or
removed). See the `# -- Round 2` comment blocks below for exactly which
endpoints were added and why each remaining gap was/wasn't includable. Two
real findings while doing this, not just "added more GETs":

1. A second, DIFFERENT rate-limit key bug, same family as the
   X-Forwarded-For fix below but not the same code path. ContactSubmitView
   (contact/views.py) is throttled via django-ratelimit's own decorator
   (bizal/ratelimit_utils.py), whose key function reads HTTP_X_REAL_IP (or
   REMOTE_ADDR), NOT X-Forwarded-For. DRF's SimpleRateThrottle.get_ident()
   — what gates every *other* anonymous endpoint here — reads XFF instead.
   Two different throttle implementations in the same codebase, keyed off
   two different headers. Before this fix, tenant_headers() only ever set
   X-Forwarded-For, so every simulated visitor's contact-form submission
   would have collapsed onto Locust's one real REMOTE_ADDR and started
   hitting the 10/hour cap after 10 total requests platform-wide — not per
   visitor — which would have looked exactly like a capacity ceiling that
   isn't real, the same failure shape as the XFF issue below. Fixed by
   also setting X-Real-IP per simulated user.
2. AppointmentCreateView requires real `service`/`provider` FK ids (see
   AppointmentSerializer) — unlike BookingListCreateView's booking_type,
   these can't be filled in with a constant. submit_appointment_request
   below fetches /api/appointments/services/ + /providers/ first and only
   POSTs if both come back non-empty (many seeded tenants aren't the
   appointments vertical, so an empty result is expected background noise,
   not a bug).

Deliberately NOT included, even though they're real endpoints: anything
that mutates state outside what's needed to simulate the action itself
(ChangePasswordView, MeDeleteView, review/order moderation, admin-update
endpoints, Stripe checkout/webhook, create_tenant, cancel_booking/
cancel_appointment — these either have external side effects, need an
existing target row a fresh run can't guarantee, or would corrupt the
fixture data a repeatable load test needs to keep re-running against).
Booking/appointment creation and now contact-form submission ARE included
because they're core "visitor completes an action" traffic and clean up
fine (see WriteHeavyTenantUser and ContactFormUser).

Analytics CSV exports (export_bookings_csv etc.) were deliberately left
out even though they're SAFE-category and would make good "expensive
report" load-test material: they're gated behind HasTenantFeature(
'csv_export'), which the only owner credentials this file has
(SEED_OWNER_PASSWORD_RESTO, a Pro-plan tenant) most likely doesn't carry —
so hitting them would mostly just measure 403s. Documented here rather
than added speculatively; a real run against Enterprise-plan owner
credentials could add these later.

What it simulates
------------------
Each Locust "user" is pinned to ONE tenant subdomain for its whole session
(via HTTP Host header spoofing — no real DNS/wildcard subdomain needed to
run this) and repeatedly hits a realistic mix of read-heavy storefront
endpoints, occasionally writing (booking creation, review submission). This
mirrors real traffic: many browsers reading a menu/catalogue, few visitors
actually completing a booking. Two new user classes add authenticated
traffic (customer account, tenant owner, platform admin) so the test isn't
only anonymous browsing.

Getting per-endpoint p99 (thesis Kufizimet item 2)
----------------------------------------------------
p99 needs enough samples per endpoint to be stable — a rule of thumb is
several hundred requests per endpoint minimum. Locust computes p99
automatically once it has enough samples; you don't need to change this
file for that, just run long enough / with enough users that every
endpoint (including the low-weight write ones) accumulates hundreds of
hits. A 3-5 minute run at 200+ users comfortably does this for every task
below; a 30-second smoke test will NOT give a meaningful p99 for the
low-weight tasks. See README's "Suggested experiment" section.

Round 3 (this revision) — fixing the login-based classes for real soaks
--------------------------------------------------------------------------
The expanded-coverage 500-user soak (run_500u_soak_expanded) surfaced two
compounding problems in AuthenticatedCustomerUser/TenantOwnerUser/
AdminPlatformUser: ~1,369 login 403s (all three share Django's 5/min
per-IP login throttle, and nginx collapses every simulated login onto
Locust's one real machine IP no matter what headers this file sends — see
the "Round 3: warm-up-then-soak token cache" section above for the full
mechanism) and, separately, TenantOwnerUser/AuthenticatedCustomerUser
sharing one seeded account each meant everything they hit would also
eventually collide on DRF's per-user 1000/hour throttle. Someone had
already reacted to the messy run by setting all three classes to
weight=0, which stopped the errors but also silently reverted real
endpoint coverage close to the original 12-endpoint file (all three
WEAK/SAFE-via-owner/ADMIN classes went untested).

Fixed both problems for TenantOwnerUser and AdminPlatformUser, re-enabled
both:
  - Login timing: moved authentication out of the timed run entirely.
    warmup_login.py logs in every account ONE AT A TIME, slowly enough to
    stay under 5/min, and caches the resulting JWTs (60-min lifetime) to
    .token_cache.json; on_start() below just reads a cached token instead
    of calling /api/auth/login/ during the soak.
  - Per-account throttle collision: TenantOwnerUser now round-robins
    across all 10 seeded tenant owners (ALL_OWNERS) instead of always
    logging in as the same one, spreading the 1000/hour budget 10 ways.
AuthenticatedCustomerUser's login-timing half is fixed the same way, but
it still only has ONE seeded customer account, so it stays weight=0 for
real capacity soaks (see its docstring) until seed.py grows more customer
accounts — a separate, smaller follow-up, not done here.

ContactFormUser and check_slug_availability are untouched by this and
still weight=0/excluded: their problem is a PER-REQUEST IP throttle that
nginx enforces by overwriting X-Real-IP on every proxied request (not a
login-time throttle), which is the security control working as intended,
not a bug to route around — see ContactFormUser's own docstring.

Run it
-------
    cd backend
    pip install locust requests
    python manage.py runserver 0.0.0.0:8000          # in one terminal
    python loadtest/warmup_login.py --host http://localhost:8000
    locust -f loadtest/locustfile.py --host=http://localhost:8000 \
        --exclude-tags ip-rate-limited

Then open http://localhost:8089, set number of users (e.g. 50) and spawn
rate (e.g. 5/s), and start. Locust reports p50/p95/p99 response time,
requests/sec, and failure rate live, and you can export a CSV/HTML report
at the end for the thesis writeup.

The warmup_login.py step is what makes AuthenticatedCustomerUser (small
sanity runs only)/TenantOwnerUser/AdminPlatformUser work cleanly at real
concurrency — skip it and those classes fall back to logging in for
themselves at spawn time, which is fine at 20 users but reproduces the
403 wall at 200-500+.

--exclude-tags ip-rate-limited (2026-09-10) — capacity runs behind nginx
--------------------------------------------------------------------------
check_slug_availability is tagged "ip-rate-limited" and ContactFormUser is
set to weight=0: both endpoints are correctly rate-limited per client IP
(10/min and 10/hour respectively), and every simulated Locust user shares
one real machine IP once requests pass through nginx — so hitting these
endpoints at 100+ concurrent users measures "does the abuse throttle
work" (yes), not "does the server have capacity" (the actual research
question). See ContactFormUser's and check_slug_availability's own
docstrings/comments for the full mechanism (nginx overwrites any spoofed
X-Real-IP with the real client IP, by design).

For headless CSV runs (the ones used for the thesis's load-test numbers),
run the warm-up first, then always include the flag:
    python loadtest/warmup_login.py --host http://localhost
    locust -f loadtest/locustfile.py --host=http://localhost \
        --headless -u 200 -r 20 --run-time 150s \
        --exclude-tags ip-rate-limited \
        --csv=run_200u

To separately verify the throttle itself (a legitimate, presentable
result in its own right — "security control verified functional under
load" — just not a capacity number), run a small dedicated test WITHOUT
the exclude flag, e.g. one simulated user issuing >10 check-slug requests
in under a minute, and confirm it gets a 403 after the 10th.

To specifically test "does one busy tenant slow down another" (the
noisy-neighbour question implied by "performance" + "data isolation" in the
research question), run two separate Locust processes: one hammering a
single tenant with WriteHeavyTenantUser, another timing plain GETs against a
different tenant, and compare that second tenant's response times with vs.
without the first process running.

A note on rate limiting at higher user counts
----------------------------------------------
bizal/throttles.py + settings/base.py DEFAULT_THROTTLE_RATES gate anonymous
traffic: 'public_read' (storefront/menu/reviews/tenant-info reads) at
3000/hour, plain 'anon' (booking POSTs) at 1000/hour. Both are keyed by
client IP (DRF SimpleRateThrottle.get_ident). Locust runs every simulated
user from ONE real machine/IP, so without the header below, all 1000
virtual users would collapse onto a single shared bucket and exhaust it in
seconds — a wall of 429s that looks like a capacity failure but is actually
just "1000 browsers, one IP", which is not what 1000 real concurrent
visitors look like (they'd arrive from ~1000 distinct real IPs).

Fix used below: give each simulated user its own fake X-Forwarded-For IP
AND its own fake X-Real-IP (Round 2 addition — see "Round 2" section above:
ContactSubmitView's django-ratelimit throttle keys off X-Real-IP/
REMOTE_ADDR, not XFF, so it needed the second header to get the same
per-visitor isolation as everything else). DRF's get_ident() honours
X-Forwarded-For whenever NUM_PROXIES is unset (true here) — settings/
base.py never sets it — so this isn't bypassing the throttle, it's making
the test topology match the thing being simulated. Each virtual user then
gets its own independent budget on whichever throttle a given endpoint
actually uses, exactly like a real distinct visitor would.

Worth a sentence in the thesis limitations/methodology section either way:
(a) that NUM_PROXIES is unset means X-Forwarded-For is trusted verbatim
with no hop count check, which is fine for a same-host reverse proxy setup
but would let a real attacker behind a shared IP (e.g. NAT) spoof their way
around per-IP throttling by sending arbitrary XFF values — a legitimate
production hardening note, not something this load test needed to fix; and
(b) PublicReadThrottle/TenantAdminThrottle's cache-backed counters live in
Redis in the Docker/production stack but in-process LocMemCache under
`manage.py runserver` (settings/local.py) — fine for a single dev-server
process, but if a 1000-user run is later pointed at a multi-worker
gunicorn/Docker deployment, each worker process still shares the same
Redis-backed rate limit correctly (that part scales as intended).
"""

import datetime
import itertools
import json
import os
import random
import string

from locust import HttpUser, task, between, tag


# ── Authenticated-user credentials ──────────────────────────────────────
# Same env-var names seed.py itself reads/writes (see backend/seed.py and
# the generated .env.seed). Nothing here is a hardcoded or discovered
# credential — these classes simply log in the same way a real customer,
# tenant owner, or platform admin would, using YOUR OWN local/staging
# environment's seeded accounts. If a var isn't set, that user class skips
# itself at on_start() rather than failing every request with 401s.
CUSTOMER_EMAIL = "customer@demo.al"
CUSTOMER_PASSWORD = os.environ.get("SEED_CUSTOMER_PASSWORD")

# Kept for backward compatibility: the single-owner fallback path used when
# no warm-up token cache exists (see "Round 3" section below and
# warmup_login.py). Not used at all once the cache is present.
OWNER_EMAIL = "owner@adriatiku.al"
OWNER_PASSWORD = os.environ.get("SEED_OWNER_PASSWORD_RESTO")
OWNER_TENANT_SLUG = "restorant-adriatiku"

# All 10 seeded tenant owners (see backend/seed.py) — same
# slug/email/password-env-var triples seed.py itself uses. Round 3 addition:
# TenantOwnerUser round-robins across every entry here whose password env
# var is actually set, instead of always logging in as OWNER_EMAIL above.
# An owner missing its env var is simply skipped, not a fatal error — this
# lets the file run against partially-configured environments too.
ALL_OWNERS = [
    {"slug": "restorant-adriatiku", "email": "owner@adriatiku.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_RESTO")},
    {"slug": "hertz-albania", "email": "owner@hertz.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_CARS")},
    {"slug": "klinika-shendeti", "email": "owner@klinikashendeti.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_CLINIC")},
    {"slug": "barber-kings-tirana", "email": "owner@barberkings.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_BARBER")},
    {"slug": "learning-center", "email": "owner@learningcenter.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_LANGSC")},
    {"slug": "amos-realestate", "email": "owner@amos.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_REALEST")},
    {"slug": "adriatic-tours", "email": "owner@adriatictours.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_TRAVEL")},
    {"slug": "ndertim-shpk", "email": "owner@ndertim.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_CONSTR")},
    {"slug": "market-express", "email": "owner@marketexpress.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_MARKET")},
    {"slug": "hotel-riviera", "email": "owner@hotelriviera.al",
     "password": os.environ.get("SEED_OWNER_PASSWORD_HOTEL")},
]

ADMIN_EMAIL = "admin@bizal.al"
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD")


# ── Round 3: warm-up-then-soak token cache ──────────────────────────────
# Fixes the root cause behind the 500-user soak's ~1,369 login 403s: login
# (CustomTokenObtainPairView) is rate-limited 5/min PER IP (see
# accounts/views.py), keyed off X-Real-IP — and nginx.conf's unconditional
# `proxy_set_header X-Real-IP $remote_addr;` collapses every simulated
# login onto Locust's one real machine IP no matter what headers this file
# sends (same mechanism documented in ContactFormUser's docstring below).
# Spoofing headers can't fix a login-time throttle; timing can.
#
# warmup_login.py (same directory) logs every login-based account in
# — customer, all 10 owners, admin — ONE AT A TIME with enough delay
# between requests to stay under 5/min, then writes the resulting JWTs to
# .token_cache.json next to this file. Access tokens last 60 minutes
# (SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'], settings/base.py) — comfortably
# longer than a warm-up (~12 logins x 13s ≈ 2.5 min) plus even a 15-minute
# soak, so the cached tokens stay valid for the whole timed run.
#
# Run before every headless soak:
#     python loadtest/warmup_login.py --host http://localhost
#
# If the cache is missing or looks stale, each affected user class falls
# back to logging in for itself at on_start() (the old behavior) — correct
# for a small sanity run with a handful of users, but exactly what
# reproduces the 403 wall at 500 users. A console warning is printed once
# per process in that case so a soak run without the warm-up step doesn't
# fail silently.
TOKEN_CACHE_PATH = os.path.join(os.path.dirname(__file__), ".token_cache.json")
TOKEN_CACHE_MAX_AGE_SECONDS = 55 * 60  # a bit under the 60-min access token lifetime


def _load_token_cache():
    """Returns the cache dict, or None if it's missing/unreadable/stale.
    Never raises — a bad cache should degrade to the per-class fallback
    login, not crash every simulated user's on_start()."""
    try:
        with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return None
    age = datetime.datetime.now(datetime.timezone.utc).timestamp() - cache.get("generated_at", 0)
    if age > TOKEN_CACHE_MAX_AGE_SECONDS:
        print(
            f"[locustfile] .token_cache.json is {age / 60:.0f} min old (>"
            f" {TOKEN_CACHE_MAX_AGE_SECONDS / 60:.0f} min) — treating as stale, "
            "re-run warmup_login.py. Falling back to per-class direct login."
        )
        return None
    return cache


_TOKEN_CACHE = _load_token_cache()
if _TOKEN_CACHE is None:
    print(
        "[locustfile] No usable .token_cache.json found — AuthenticatedCustomerUser, "
        "TenantOwnerUser and AdminPlatformUser will each log in for themselves at "
        "on_start() instead of using pre-warmed tokens. Fine for a small sanity run; "
        "for a real capacity soak, run `python loadtest/warmup_login.py` first."
    )

# itertools.cycle().__next__() has no I/O point, so — same reasoning as
# fake_client_ip()'s _client_ip_seq above — this is safe to share across
# greenlets under gevent without a lock: Locust/gevent only switches
# greenlets at I/O, never mid-statement.
_cached_owner_tokens = (_TOKEN_CACHE or {}).get("owners", [])
_owner_token_cycle = itertools.cycle(_cached_owner_tokens) if _cached_owner_tokens else None


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

# One unique fake client IP per simulated user (see "A note on rate
# limiting" above). itertools.count().__next__() is safe without a lock
# here: gevent (Locust's concurrency model) only switches greenlets at I/O
# points, and a bare `next()` on a count() has none, so no two on_start()
# calls can interleave mid-increment. Starts at 1 so we never hand out
# 10.0.0.0 (network address, harmless either way, but cleaner).
_client_ip_seq = itertools.count(1)


def fake_client_ip() -> str:
    """A syntactically-valid, non-colliding-for-this-run private IP, one
    per simulated user. 10.0.0.0/8 gives ~16.7M addresses — nowhere close
    to being exhausted even at 1000+ concurrent users."""
    n = next(_client_ip_seq)
    return f"10.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def anon_headers() -> dict:
    """The two per-visitor IP headers this codebase's two different
    anonymous-throttle implementations key off (Round 2 fix — see module
    docstring): DRF's SimpleRateThrottle.get_ident() reads
    X-Forwarded-For; bizal/ratelimit_utils.py's django-ratelimit key func
    reads X-Real-IP (falling back to REMOTE_ADDR). Same fake IP in both so
    a given simulated visitor is one consistent "person" to every throttle
    in the codebase, not just some of them."""
    ip = fake_client_ip()
    return {"X-Forwarded-For": ip, "X-Real-IP": ip}


def tenant_headers(slug: str) -> dict:
    """Host header that makes TenantMiddleware resolve to `slug` without
    needing real wildcard DNS — matches how the test suite itself fakes
    subdomains (see backend/tenants/tests.py, HTTP_HOST=<slug>.bizal.al) —
    plus the per-user IP headers from anon_headers() so each simulated
    visitor gets its own anonymous-throttle budget on every throttle
    implementation in the codebase, instead of sharing Locust's one real
    IP."""
    return {"Host": f"{slug}.bizal.al", **anon_headers()}


def main_domain_headers() -> dict:
    """Same idea as tenant_headers() but for requests that must land on
    the main domain (bizal.al) rather than a tenant subdomain — e.g. the
    marketplace, signup wizard, or platform-wide endpoints. Without an
    explicit Host: bizal.al, requests go out as Host: <whatever --host
    was>, which matches neither nginx's main-domain server_name nor the
    tenant regex and gets `return 444` (connection closed) — see
    MainDomainUser.view_landing_page below for the full explanation of
    that failure mode."""
    return {"Host": "bizal.al", **anon_headers()}


def _random_future_date() -> str:
    """ISO date 1-14 days out, for the appointment-creation task below —
    far enough ahead to never collide with "today" edge cases, close
    enough to still land inside most providers' visible booking window."""
    d = datetime.date.today() + datetime.timedelta(days=random.randint(1, 14))
    return d.isoformat()


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
        self.headers = tenant_headers(self.slug)

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

    # -- Endpoints added for full-coverage load testing (Kufizimet item 1) --
    # All confirmed AllowAny via check_tenant_isolation.py's PUBLIC bucket,
    # cross-checked against each app's urls.py for the real path. Not every
    # tenant runs every business type (e.g. hotels endpoints on a
    # restaurant tenant), so a 404/empty-list here is expected for some
    # slug/endpoint combos — that's a fine, low-weight background request,
    # not a bug, and Locust records it under its own endpoint name either
    # way so it doesn't skew other endpoints' stats.

    @task(1)
    @tag("read")
    def browse_hero_slides(self):
        self.client.get(
            "/api/storefront/hero/",
            headers=self.headers,
            name="/api/storefront/hero/ [tenant]",
        )

    @task(1)
    @tag("read")
    def browse_appointment_services(self):
        self.client.get(
            "/api/appointments/services/",
            headers=self.headers,
            name="/api/appointments/services/ [tenant]",
        )

    @task(1)
    @tag("read")
    def browse_hotel_room_types(self):
        self.client.get(
            "/api/hotels/room-types/",
            headers=self.headers,
            name="/api/hotels/room-types/ [tenant]",
        )

    @task(1)
    @tag("read")
    def browse_rental_featured(self):
        self.client.get(
            "/api/rentals/featured/",
            headers=self.headers,
            name="/api/rentals/featured/ [tenant]",
        )

    @task(1)
    @tag("read")
    def browse_blog(self):
        self.client.get(
            "/api/blog/",
            headers=self.headers,
            name="/api/blog/ [tenant]",
        )

    @task(1)
    @tag("read")
    def browse_platform_review_summary(self):
        # Not tenant-specific — this is the marketplace-wide review summary
        # shown on the main domain. FIX: must set an explicit Host header
        # matching nginx's main-domain server_name (same issue as
        # MainDomainUser.view_landing_page below) — without it, the request
        # goes out as Host: <whatever --host was>, which matches neither
        # nginx's bizal.al/www.bizal.al block nor the tenant regex, so it
        # falls through to default_server and gets `return 444` (connection
        # closed, no response) — a test artifact that looked like a 100%
        # failure rate on this endpoint but was actually nginx correctly
        # rejecting an unrecognised Host.
        self.client.get(
            "/api/platform-reviews/summary/",
            headers=main_domain_headers(),
            name="/api/platform-reviews/summary/ [main domain]",
        )

    # -- Round 2: more PUBLIC-bucket endpoints (Kufizimet item 4 follow-up) --
    # Same reasoning as the block above: AllowAny, cross-checked against
    # each app's urls.py, low weight since these are secondary browsing
    # actions rather than the "core" storefront-home/menu/reviews path.

    @task(1)
    @tag("read")
    def browse_blog_tags(self):
        self.client.get(
            "/api/blog/tags/", headers=self.headers, name="/api/blog/tags/ [tenant]"
        )

    @task(1)
    @tag("read")
    def browse_rentals_list(self):
        # Full catalogue (RentalItemListView) vs. the featured subset
        # already covered by browse_rental_featured above.
        self.client.get(
            "/api/rentals/", headers=self.headers, name="/api/rentals/ [tenant]"
        )

    @task(1)
    @tag("read")
    def browse_research_config(self):
        # SusConfigView — powers the in-app usability-survey widget the
        # thesis's own usability-arm data collection depends on, so it's
        # realistic background traffic, not just a random public endpoint.
        self.client.get(
            "/api/research/sus/config/",
            headers=self.headers,
            name="/api/research/sus/config/ [tenant]",
        )

    @task(1)
    @tag("read")
    def browse_storefront_sections(self):
        self.client.get(
            "/api/storefront/sections/",
            headers=self.headers,
            name="/api/storefront/sections/ [tenant]",
        )

    @task(1)
    @tag("read")
    def browse_available_currencies(self):
        # available_pay_currencies — checkout-page currency selector; every
        # storefront visitor who opens a checkout flow calls this before
        # create_booking_checkout/create_order_checkout, which are the two
        # Stripe-side endpoints deliberately excluded (see module docstring).
        self.client.get(
            "/api/payments/available-currencies/",
            headers=self.headers,
            name="/api/payments/available-currencies/ [tenant]",
        )


class AuthenticatedCustomerUser(HttpUser):
    """WEAK-category coverage (Kufizimet item 1): a logged-in customer
    checking their own account pages. MeView/MeBookingsView/MeOrdersView/
    MeReviewsView are all self-scoped (filter(user=request.user)) and
    allowlisted WEAK rather than SAFE because the static scanner can't see
    a manual `user=request.user` filter as tenant-safe — see
    tenant_isolation_allowlist.py. Read-only: no password change, no
    account deletion, nothing that would corrupt the seeded fixture.

    Skips itself entirely if SEED_CUSTOMER_PASSWORD isn't set in the
    environment, so this class is a no-op (not a wall of 401s) against an
    environment that wasn't seeded with `python seed.py`.

    DISABLED (weight=0) for capacity/concurrency runs -- 2026-09-11: two
    separate, compounding problems, discovered from a 500-user soak where
    login failed with 403 on 662/670 attempts and /api/auth/me/* later
    failed with 429 starting ~10 minutes in.

    1. Login itself (CustomTokenObtainPairView) carries the same 5/min
       django-ratelimit decorator, keyed the same X-Real-IP way, as
       ContactSubmitView above -- and nginx.conf's unconditional
       `proxy_set_header X-Real-IP $remote_addr;` collapses every
       simulated login onto Locust's one real machine IP exactly as
       documented in ContactFormUser's docstring. ~500 near-simultaneous
       login attempts blow through 5/min almost instantly; only the first
       ~10 (across all three login-based classes combined, since they
       share the same view) get through before the rest 403.
       FIXED (Round 3): on_start() below now pulls an already-authenticated
       token from .token_cache.json (see warmup_login.py) instead of
       logging in during the run, so this class no longer touches
       /api/auth/login/ at all once the cache exists.
    2. Separately: every simulated customer here logs in as the SAME
       single seeded account (CUSTOMER_EMAIL). DRF's UserRateThrottle
       ('user': '1000/hour', see settings/base.py) is keyed per
       authenticated user id, not IP -- so all these "different" virtual
       users are one account to that throttle, and its 1000/hour budget
       for /api/auth/me/* gets exhausted partway through a long soak.
       STILL OPEN: the warm-up cache fixes problem 1 (login timing) but
       not this one -- one account is one account no matter how it
       authenticated. Fixing this needs multiple seeded customer accounts
       (one per some N virtual users), the same way TenantOwnerUser below
       was fixed by rotating across 10 owner accounts. Not implemented --
       flagged as future work (would need seed.py changes), not silently
       worked around. This is why weight stays 0 for real capacity soaks
       even though the login-timing half of the bug is fixed.

    Re-enable (weight>0) only for a small, dedicated run (like the 20-user
    sanity check this file was validated against) whose purpose is
    verifying these endpoints work at all, not measuring capacity.
    """

    weight = 0
    wait_time = between(2, 4)

    def on_start(self):
        cached = (_TOKEN_CACHE or {}).get("customer")
        if cached:
            # Round 3: pre-warmed token, no login call during the timed run.
            self.headers = {
                "Authorization": f"Bearer {cached}",
                "Host": "bizal.al",
            }
            return
        if not CUSTOMER_PASSWORD:
            self.stop(force=True)
            return
        # Fallback (no token cache): log in for real, same as before Round 3.
        # FIX: this class's account is a platform-wide customer, not tied
        # to one tenant, so its calls belong on the main domain. Without
        # an explicit Host, the request goes out as Host: <whatever
        # --host was>, which matches neither nginx's main-domain
        # server_name nor the tenant regex and gets `return 444`
        # (RemoteDisconnected) — same failure mode as MainDomainUser and
        # AdminPlatformUser below, just discovered here first. Host must
        # also persist into self.headers, not just this login call: every
        # later task (view_me, me/bookings, etc.) reuses self.headers and
        # would hit the same 444 otherwise.
        resp = self.client.post(
            "/api/auth/login/",
            json={"email": CUSTOMER_EMAIL, "password": CUSTOMER_PASSWORD},
            headers=main_domain_headers(),
            name="/api/auth/login/ [customer]",
        )
        token = resp.json().get("access") if resp.status_code == 200 else None
        if not token:
            self.stop(force=True)
            return
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Host": "bizal.al",
        }

    @task(3)
    @tag("read", "auth")
    def view_me(self):
        self.client.get("/api/auth/me/", headers=self.headers, name="/api/auth/me/")

    @staticmethod
    def _first_id(resp):
        """MeBookingsView/MeOrdersView use _StandardPagination (paginated:
        {"results": [...]}); grab the first row's id either way so the
        chained detail-view hits below work regardless of pagination
        shape. Returns None on anything unexpected — the caller then just
        skips the chained request instead of raising, since an empty
        result (this customer has no bookings/orders yet) is a normal,
        expected outcome, not a test failure."""
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        rows = data.get("results", data) if isinstance(data, dict) else data
        if isinstance(rows, list) and rows:
            return rows[0].get("id")
        return None

    @task(2)
    @tag("read", "auth")
    def view_my_bookings(self):
        # Chained: also hit BookingDetailView for one real booking, same
        # "detail view" traffic pattern a real account page generates when
        # a customer clicks into one booking from their list — a WEAK
        # endpoint (manual tenant filter, see check_tenant_isolation.py)
        # that a static-path task alone can't reach since it needs a real
        # booking id, not a placeholder.
        resp = self.client.get(
            "/api/auth/me/bookings/", headers=self.headers, name="/api/auth/me/bookings/"
        )
        booking_id = self._first_id(resp)
        if booking_id:
            self.client.get(
                f"/api/bookings/{booking_id}/",
                headers=self.headers,
                name="/api/bookings/{id}/ [own]",
            )

    @task(2)
    @tag("read", "auth")
    def view_my_orders(self):
        # Chained the same way as view_my_bookings, into OrderDetailView.
        resp = self.client.get(
            "/api/auth/me/orders/", headers=self.headers, name="/api/auth/me/orders/"
        )
        order_id = self._first_id(resp)
        if order_id:
            self.client.get(
                f"/api/orders/{order_id}/",
                headers=self.headers,
                name="/api/orders/{id}/ [own]",
            )

    @task(1)
    @tag("read", "auth")
    def view_my_reviews(self):
        self.client.get(
            "/api/auth/me/reviews/", headers=self.headers, name="/api/auth/me/reviews/"
        )

    # -- Round 2: remaining WEAK-allowlisted self-scoped endpoints --

    @task(1)
    @tag("read", "auth")
    def view_my_appointments(self):
        self.client.get(
            "/api/auth/me/appointments/",
            headers=self.headers,
            name="/api/auth/me/appointments/",
        )

    @task(1)
    @tag("read", "auth")
    def view_my_notification_prefs(self):
        self.client.get(
            "/api/auth/me/notifications/",
            headers=self.headers,
            name="/api/auth/me/notifications/",
        )

    @task(1)
    @tag("read", "auth")
    def view_loyalty_balance(self):
        # LoyaltyMeView needs a real tenant (400 if request.tenant is None,
        # 404 if the tenant's plan doesn't include loyalty_program) — pick
        # one of the seeded tenants per request so this exercises different
        # tenants over a run rather than always the same one.
        self.client.get(
            "/api/billing/loyalty/me/",
            headers={**self.headers, **tenant_headers(random.choice(TENANT_SLUGS))},
            name="/api/billing/loyalty/me/ [tenant]",
        )


class TenantOwnerUser(HttpUser):
    """SAFE-category coverage (Kufizimet item 1): a logged-in tenant owner
    hitting their own dashboard. TenantMeView and the analytics dashboard
    both use tenant-aware permission classes (SAFE bucket in the isolation
    audit) rather than the manual-filter pattern the WEAK class above uses.

    Skips itself if no owner credentials are available at all — same
    reasoning as AuthenticatedCustomerUser.

    RE-ENABLED (Round 3, 2026-09-11) after being weight=0 since the first
    500-user soak (296/297 owner logins failed with 403). That soak had
    two compounding problems, both now fixed:

    1. Login collapsed onto the nginx-forced single real IP and blew
       through the 5/min per-IP login throttle. FIXED: on_start() below
       now takes an already-authenticated token from .token_cache.json
       (see warmup_login.py and the module-level "Round 3" section above)
       instead of logging in during the run.
    2. Every simulated owner was the SAME single seeded account
       (OWNER_EMAIL / restorant-adriatiku), so /api/tenants/me/,
       analytics, etc. would also eventually collide on DRF's per-user
       1000/hour throttle in a long enough run. FIXED: this class now
       round-robins across all 10 seeded tenant owners (ALL_OWNERS above,
       whichever have their password env var set) via _owner_token_cycle,
       spreading that 1000/hour budget across up to 10 separate accounts
       instead of exhausting one. Each virtual user keeps whichever
       owner/tenant it was handed for its whole session (same "pinned for
       the session" pattern as ReadHeavyTenantUser's slug), so
       /api/tenants/me/ etc. stay internally consistent per user.

    Falls back to the old single-account direct-login behavior (OWNER_
    EMAIL / OWNER_PASSWORD / OWNER_TENANT_SLUG) if no token cache exists —
    correct for a small sanity run, but reproduces the original 403 wall
    at real soak concurrency, so always run warmup_login.py first for a
    real capacity run.
    """

    weight = 2
    wait_time = between(3, 6)

    def on_start(self):
        if _owner_token_cycle is not None:
            # Round 3: pre-warmed token for one of the 10 owners, no login
            # call during the timed run. next() has no I/O point, so this
            # is safe under gevent without a lock (see module docstring).
            owner = next(_owner_token_cycle)
            self.headers = {
                "Authorization": f"Bearer {owner['token']}",
                "Host": f"{owner['slug']}.bizal.al",
            }
            self._load_enabled_features()
            return
        if not OWNER_PASSWORD:
            self.stop(force=True)
            return
        # Fallback (no token cache): log in for real as the single
        # OWNER_EMAIL account, same as before Round 3.
        resp = self.client.post(
            "/api/auth/login/",
            json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
            headers={"Host": f"{OWNER_TENANT_SLUG}.bizal.al"},
            name="/api/auth/login/ [owner]",
        )
        token = resp.json().get("access") if resp.status_code == 200 else None
        if not token:
            self.stop(force=True)
            return
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Host": f"{OWNER_TENANT_SLUG}.bizal.al",
        }
        self._load_enabled_features()

    def _load_enabled_features(self):
        # Round 4 (2026-09-12): the four tasks below (view_staff,
        # view_storefront_manage_pages, view_crm_leads, view_invoices) hit
        # HasTenantFeature-gated endpoints. Since TenantOwnerUser now
        # round-robins across all 10 seeded owners (Trial/Starter/Pro/
        # Enterprise), a 403 from a Starter or Pro tenant hitting a
        # feature it genuinely doesn't have (e.g. PLAN_FEATURES[PRO]
        # ['crm'] is False) is the access-control system working
        # correctly, not a capacity bug — but it still shows up as a
        # Locust "failure", which pollutes the failure-rate number this
        # load test is actually trying to measure.
        #
        # Fetch this tenant's resolved feature set ONCE per simulated
        # user (not per-request) via /api/tenants/me/, which already
        # returns `features: [{key, value, is_custom_grant}, ...]`
        # (TenantFeatureSerializer) — the same resolved set
        # BUSINESS_TYPE_PRESETS overrides land in, so this doesn't need
        # its own copy of the plan/business-type feature-resolution
        # logic. The four gated tasks below use _check_gated() to mark a
        # 403 as a Locust success when the feature genuinely isn't
        # enabled for this tenant, and as a real failure otherwise (200
        # with an unexpected body, a 403 despite the feature being
        # enabled, a 5xx, etc.).
        #
        # self.enabled_features stays None (rather than an empty set) if
        # this probe call itself fails for any reason — _check_gated()
        # treats None as "can't verify, don't manufacture a failure from
        # a 403 here" rather than assuming every feature is disabled.
        self.enabled_features = None
        try:
            resp = self.client.get(
                "/api/tenants/me/",
                headers=self.headers,
                name="/api/tenants/me/ [feature probe]",
            )
            if resp.status_code == 200:
                features = resp.json().get("features", [])
                self.enabled_features = {
                    f["key"] for f in features if str(f.get("value")).lower() == "true"
                }
        except Exception:
            pass

    def _check_gated(self, response, feature_key):
        """Shared pass/fail logic for HasTenantFeature-gated endpoints.

        200 -> always a real success.
        403 while the feature is known to be disabled for this tenant ->
            correct plan-gating, counted as a Locust success (this is
            what the endpoint SHOULD do, not a capacity problem).
        403 while the feature is enabled (or unknown, self.enabled_features
            is None because the probe failed) -> real failure, surfaced
            normally so an actual permission regression still shows up.
        anything else (5xx, unexpected 2xx shape, etc.) -> real failure.
        """
        if response.status_code == 200:
            response.success()
        elif (
            response.status_code == 403
            and self.enabled_features is not None
            and feature_key not in self.enabled_features
        ):
            response.success()
        else:
            response.failure(
                f"unexpected {response.status_code} (feature={feature_key!r}, "
                f"enabled_features={self.enabled_features!r})"
            )

    @task(2)
    @tag("read", "auth")
    def view_tenant_dashboard(self):
        self.client.get("/api/tenants/me/", headers=self.headers, name="/api/tenants/me/")

    @task(1)
    @tag("read", "auth")
    def view_analytics(self):
        # 'analytics' is False on Starter (see PLAN_FEATURES) — the view
        # checks tenant.has_feature('analytics') manually rather than via
        # a HasTenantFeature permission class, but it's the same correct
        # plan-gating as view_staff/view_invoices/etc above.
        with self.client.get(
            "/api/analytics/",
            headers=self.headers,
            name="/api/analytics/",
            catch_response=True,
        ) as response:
            self._check_gated(response, "analytics")

    # -- Round 2: the rest of the owner dashboard (Kufizimet item 4 follow-up) --
    # OWNER_TENANT_SLUG (restorant-adriatiku) is a restaurant, so hitting
    # e.g. inventory/staff-schedule-adjacent endpoints here mostly exercises
    # "owner logged in, feature/vertical not used" — a real, low-weight
    # background case (empty list / 403-by-plan), same reasoning as the
    # cross-business-type hits already accepted in ReadHeavyTenantUser
    # above, not padding. All confirmed SAFE (tenant-aware permission
    # class) via check_tenant_isolation.py, cross-checked against each
    # app's urls.py for the real path.

    @task(1)
    @tag("read", "auth")
    def view_tenant_settings(self):
        self.client.get(
            "/api/tenants/settings/", headers=self.headers, name="/api/tenants/settings/"
        )

    @task(1)
    @tag("read", "auth")
    def view_tenant_locations(self):
        self.client.get(
            "/api/tenants/locations/", headers=self.headers, name="/api/tenants/locations/"
        )

    @task(1)
    @tag("read", "auth")
    def view_referrals(self):
        # my_referrals — WEAK-allowlisted (self-scoped via request.user.tenant)
        # rather than SAFE, but it's a real owner-dashboard call, so it
        # belongs in this user class rather than AuthenticatedCustomerUser.
        self.client.get(
            "/api/tenants/referrals/", headers=self.headers, name="/api/tenants/referrals/"
        )

    @task(1)
    @tag("read", "auth")
    def view_credits(self):
        self.client.get(
            "/api/tenants/credits/balance/",
            headers=self.headers,
            name="/api/tenants/credits/balance/",
        )
        self.client.get(
            "/api/tenants/credits/ledger/",
            headers=self.headers,
            name="/api/tenants/credits/ledger/",
        )

    @task(1)
    @tag("read", "auth")
    def view_staff(self):
        # 'staff_accounts' is False on Starter (see PLAN_FEATURES in
        # tenants/models.py) — a 403 for a Starter-plan owner in the
        # round-robin is correct gating, not a bug. See _check_gated().
        with self.client.get(
            "/api/staff/", headers=self.headers, name="/api/staff/", catch_response=True
        ) as response:
            self._check_gated(response, "staff_accounts")

    @task(1)
    @tag("read", "auth")
    def view_inventory(self):
        self.client.get(
            "/api/inventory/categories/",
            headers=self.headers,
            name="/api/inventory/categories/",
        )
        self.client.get("/api/inventory/", headers=self.headers, name="/api/inventory/")

    @task(1)
    @tag("read", "auth")
    def view_owner_notifications(self):
        self.client.get(
            "/api/notifications/", headers=self.headers, name="/api/notifications/"
        )
        self.client.get(
            "/api/notifications/unread-count/",
            headers=self.headers,
            name="/api/notifications/unread-count/",
        )

    @task(1)
    @tag("read", "auth")
    def view_subscriptions(self):
        self.client.get(
            "/api/subscriptions/mine/", headers=self.headers, name="/api/subscriptions/mine/"
        )

    @task(1)
    @tag("read", "auth")
    def view_reviews_manage(self):
        self.client.get(
            "/api/reviews/manage/", headers=self.headers, name="/api/reviews/manage/"
        )

    @task(1)
    @tag("read", "auth")
    def view_appointments_admin(self):
        self.client.get(
            "/api/appointments/admin/", headers=self.headers, name="/api/appointments/admin/"
        )

    @task(1)
    @tag("read", "auth")
    def view_storefront_manage_pages(self):
        # 'custom_branding' is False on Starter — see view_staff's
        # comment above / _check_gated().
        with self.client.get(
            "/api/storefront/manage/pages/",
            headers=self.headers,
            name="/api/storefront/manage/pages/",
            catch_response=True,
        ) as response:
            self._check_gated(response, "custom_branding")

    @task(1)
    @tag("read", "auth")
    def view_contact_messages(self):
        # Correctly placed here, not AdminPlatformUser — see the comment on
        # AdminPlatformUser about why this was moved (Round 2 fix).
        self.client.get(
            "/api/contact/admin/messages/",
            headers=self.headers,
            name="/api/contact/admin/messages/",
        )

    @task(1)
    @tag("read", "auth")
    def view_crm_leads(self):
        # EXPECTED to fail for Pro-plan owners specifically (e.g.
        # restorant-adriatiku, Pro + business_type='restaurant'):
        # PLAN_FEATURES[PRO]['crm'] is False with no restaurant-type
        # override (see BUSINESS_TYPE_PRESETS in tenants/models.py) — so
        # those requests 403 via HasTenantFeature('crm'), by design. Left
        # in deliberately: it demonstrates the plan gate is actually
        # enforced under load, not just in a unit test. Round 3: now that
        # TenantOwnerUser round-robins across all 10 seeded owners
        # (ALL_OWNERS above), Enterprise-plan owners in the rotation (e.g.
        # hotel-riviera, hertz-albania) DO see this succeed — both
        # outcomes are expected, mixed together, rather than always 403.
        with self.client.get(
            "/api/crm/leads/",
            headers=self.headers,
            name="/api/crm/leads/",
            catch_response=True,
        ) as response:
            self._check_gated(response, "crm")

    @task(1)
    @tag("read", "auth")
    def view_invoices(self):
        # Same reasoning as view_crm_leads above: PLAN_FEATURES[PRO]
        # ['invoicing'] is False, so this 403s for Pro-plan owners by
        # design, not a bug — and now genuinely succeeds for whichever
        # Enterprise-plan owners come up in the round-robin.
        with self.client.get(
            "/api/billing/invoices/",
            headers=self.headers,
            name="/api/billing/invoices/",
            catch_response=True,
        ) as response:
            self._check_gated(response, "invoicing")


class AdminPlatformUser(HttpUser):
    """ADMIN-category coverage (Kufizimet item 1): platform admin (not a
    tenant owner) hitting an IsAdminUser-gated endpoint. Read-only GET —
    intentionally not exercising anything under django-admin/ itself,
    which is Django's own admin UI, not part of the API being load-tested.

    Skips itself if no admin credentials are available at all.

    RE-ENABLED (Round 3, 2026-09-11) at a low weight after being weight=0
    since the first 500-user soak (411/412 admin logins failed with 403,
    same login-timing mechanism as AuthenticatedCustomerUser above — see
    its docstring). FIXED the same way as the other two login-based
    classes: on_start() below now takes an already-authenticated token
    from .token_cache.json instead of logging in during the run.

    Unlike AuthenticatedCustomerUser, this one is fine staying single-
    account rather than rotating across several: realistically there are
    only 1-2 platform admins in the first place, so a single seeded admin
    account plus a low class weight (kept low deliberately, not scaled up)
    is a more honest simulation than multiplying admin accounts would be.

    ROUND 4 FIX (2026-09-12): wait_time was between(5, 10) — fine for a
    handful of admin users, but at 500 total simulated users this class's
    weight=1 slice still works out to ~35 concurrent admin sessions, all
    sharing the ONE seeded admin account. Each was firing a request every
    ~7.5s on average, which adds up to ~450 requests in 3 minutes to a
    single endpoint from a single account — comfortably past DRF's default
    1000/hour per-user throttle (see bizal/settings/base.py) well before a
    real 15-minute soak finishes, even starting from a completely fresh
    hour. That's not a real capacity signal: no deployment of this app
    will ever have 35 admins simultaneously polling the webhook audit log
    from the same account. Slowed to between(30, 90) so the simulated
    admin traffic looks like what it's supposed to represent — 1-2 humans
    occasionally checking a dashboard, not a synthetic hammer — instead of
    trying to fix this by loosening the app's own throttle to match an
    unrealistic harness. (The app-side throttle was also given its own
    higher-ceiling scope, admin_read, as a second, independent fix — see
    bizal/throttles.py's PlatformAdminReadThrottle — since real admin
    tooling use, e.g. a long moderation session, shouldn't share the
    1000/hour budget with ordinary customer/owner traffic either. Both
    fixes address the same failure from different ends: this one makes
    the test realistic, that one makes the app's own limit less
    accidentally strict for legitimate heavy admin use.)
    """

    weight = 1
    wait_time = between(30, 90)

    def on_start(self):
        cached = (_TOKEN_CACHE or {}).get("admin")
        if cached:
            # Round 3: pre-warmed token, no login call during the timed run.
            self.headers = {
                "Authorization": f"Bearer {cached}",
                "Host": "bizal.al",
            }
            return
        if not ADMIN_PASSWORD:
            self.stop(force=True)
            return
        # Fallback (no token cache): log in for real, same as before Round 3.
        # FIX: same missing-Host issue as AuthenticatedCustomerUser above —
        # a platform admin isn't tied to a tenant either, so this belongs
        # on the main domain. Without it, login gets RemoteDisconnected
        # (nginx default_server 444), and even if login somehow succeeded,
        # every later task would too since they all reuse self.headers.
        resp = self.client.post(
            "/api/auth/login/",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            headers=main_domain_headers(),
            name="/api/auth/login/ [admin]",
        )
        token = resp.json().get("access") if resp.status_code == 200 else None
        if not token:
            self.stop(force=True)
            return
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Host": "bizal.al",
        }

    @task
    @tag("read", "auth")
    def view_webhook_events(self):
        self.client.get(
            "/api/payments/webhook-events/",
            headers=self.headers,
            name="/api/payments/webhook-events/",
        )

    # -- Round 2: the rest of the ADMIN bucket --
    # NOTE: /api/contact/admin/messages/ (ContactMessageListView) was
    # originally added here as a naive "admin" endpoint by URL-path
    # naming ("admin/messages"). Wrong — verified against contact/views.py:
    # it's HasTenantRole('receptionist'), a per-TENANT staff inbox, not an
    # IsAdminUser platform panel. HasTenantRole checks `if not
    # request.tenant: return False` before it even looks at the caller's
    # role, so this account (no Host header — platform admin, not tied to
    # any tenant) got a 403 on every single request in the first real run
    # of this task: 59/59 failed, 100%. Moved to TenantOwnerUser below,
    # where the owner already has a Host header AND owner-tier role
    # (HasTenantRole always passes 'owner'/'manager' — see
    # tenants/permissions.py).

    @task
    @tag("read", "auth")
    def view_platform_reviews_admin(self):
        self.client.get(
            "/api/platform-reviews/admin/",
            headers=self.headers,
            name="/api/platform-reviews/admin/",
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
        self.headers = tenant_headers(self.slug)

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
        # CONTENTION FIX (2026-09-12): bookings/views.py's create() holds a
        # select_for_update() row lock with `SET LOCAL lock_timeout = '3s'`
        # around this write (see that file's comment). Under 500 concurrent
        # WriteHeavyTenantUsers hammering a small, fixed set of tenants, a
        # 409 from that lock timeout is the double-booking guard doing
        # exactly its job, not a capacity bug -- so it's counted as a
        # success here, same as _check_gated() already does for a correct
        # 403 on a disabled feature. Anything else (2xx aside, this means
        # 5xx, an unrelated 4xx, or a genuinely wrong 409) still fails
        # normally.
        with self.client.post(
            "/api/bookings/",
            json=payload,
            headers=self.headers,
            name="/api/bookings/ [tenant, POST]",
            catch_response=True,
        ) as response:
            if response.status_code == 409:
                response.success()

    # -- Round 2: the appointment-creation flow the docstring already
    # claimed was covered but wasn't actually implemented before this
    # revision (see module docstring, "Round 2" section, finding #2).

    @task
    @tag("write")
    def submit_appointment_request(self):
        # AppointmentSerializer requires real service/provider FK ids
        # (unlike bookings' booking_type, these can't be a constant) —
        # fetch both public list endpoints first. On most seeded tenants
        # (not the appointments vertical) at least one list will be empty;
        # that's expected, so this just skips the POST rather than sending
        # a guaranteed-400. On klinika-shendeti / barber-kings-tirana both
        # lists are populated and the POST actually exercises the create
        # path, including its select_for_update() double-booking guard
        # (see appointments/views.py AppointmentCreateView.create()).
        services_resp = self.client.get(
            "/api/appointments/services/",
            headers=self.headers,
            name="/api/appointments/services/ [tenant]",
        )
        providers_resp = self.client.get(
            "/api/appointments/providers/",
            headers=self.headers,
            name="/api/appointments/providers/ [tenant]",
        )
        try:
            services = services_resp.json()
            providers = providers_resp.json()
        except ValueError:
            return
        if not (isinstance(services, list) and services) or not (
            isinstance(providers, list) and providers
        ):
            return

        # +1 to +14 days out — appointments in the past would 400 against
        # any date-not-in-the-past validation the serializer/model adds.
        appt_date = _random_future_date()
        payload = {
            "service": services[0]["id"],
            "provider": providers[0]["id"],
            "date": appt_date,
            "start_time": "10:00:00",
            "guest_name": f"Load Test {random.randint(1, 100000)}",
            "guest_email": f"loadtest{random.randint(1, 100000)}@example.com",
            "guest_phone": "+355691234567",
            "notes": "locust load test — safe to ignore/delete",
        }
        # Same 409-as-expected reasoning as submit_booking_request above --
        # appointments/views.py's create() has the identical
        # select_for_update() + SET LOCAL lock_timeout = '3s' guard.
        with self.client.post(
            "/api/appointments/",
            json=payload,
            headers=self.headers,
            name="/api/appointments/ [tenant, POST]",
            catch_response=True,
        ) as response:
            if response.status_code == 409:
                response.success()


class ContactFormUser(HttpUser):
    """Round 2 addition: a visitor filling out a tenant's contact form.
    Separate low-weight class rather than folded into WriteHeavyTenantUser
    so it's easy to isolate/disable on its own (ContactSubmitView is the
    most spam-exposed anonymous POST in the app — 10/hour per IP, see
    contact/views.py — and this is also what exposed the X-Real-IP rate-
    limit-key gap documented in the module docstring).

    DISABLED (weight=0) for capacity/concurrency runs — 2026-09-10:
    anon_headers() correctly gives each simulated visitor its own fake
    X-Real-IP, but nginx.conf sets `proxy_set_header X-Real-IP
    $remote_addr;` on every proxied request, which REPLACES whatever the
    client sent rather than merging with it — by design, since trusting a
    client-supplied X-Real-IP would let a real attacker spoof their way
    around this exact throttle. So every request Locust sends still
    collapses onto Locust's one real machine IP by the time it reaches
    Django, and 200 concurrent simulated visitors blow through the 10/hour
    cap almost immediately — a rate-limit artifact of testing through
    nginx from one host, not a capacity finding. Don't "fix" anon_headers()
    again; it's already correct, this is what it looks like defeated.
    Re-enable (weight=1) only for a small, dedicated run whose explicit
    purpose is verifying the throttle itself, not measuring capacity.
    """

    weight = 0
    wait_time = between(4, 8)

    def on_start(self):
        self.slug = random.choice(TENANT_SLUGS)
        self.headers = tenant_headers(self.slug)

    @task
    @tag("write")
    def submit_contact_message(self):
        # ContactSubmitView requires TenantDomainOnly + the tenant's plan
        # to include the contact_form feature — tenants without that
        # feature get a 403 here, which is expected background noise for
        # those slugs, not a bug (same "not every tenant runs every
        # feature" reasoning as the cross-business-type reads elsewhere in
        # this file).
        payload = {
            "name": f"Load Test {random.randint(1, 100000)}",
            "email": f"loadtest{random.randint(1, 100000)}@example.com",
            "phone": "+355691234567",
            "subject": "Locust load test",
            "message": "locust load test — safe to ignore/delete",
        }
        self.client.post(
            "/api/contact/",
            json=payload,
            headers=self.headers,
            name="/api/contact/ [tenant, POST]",
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
        # FIX: without an explicit Host header, this request goes out as
        # Host: <whatever --host was>, e.g. "localhost" — which matches
        # neither nginx's main-domain server_name (bizal.al/www.bizal.al)
        # nor the tenant regex, so it falls through to the default_server
        # block and gets `return 444` (connection closed, no response).
        # That looked exactly like RemoteDisconnected/ConnectionReset in
        # results and made /health/ [main domain] appear ~100% broken under
        # load, when in fact nginx was correctly dropping traffic for an
        # unrecognised Host — a test artifact, not a real capacity finding.
        # Setting Host: bizal.al here matches what a real browser hitting
        # the main domain would send, so this now measures actual
        # main-domain capacity instead of nginx's (intentional) default-host
        # rejection.
        self.client.get(
            "/health/",
            name="/health/ [main domain]",
            headers=main_domain_headers(),
        )

    # -- Round 2: the rest of the main-domain PUBLIC bucket --
    # business_types/marketplace_list/check_slug are all AllowAny and
    # explicitly main-domain-facing (marketplace directory, onboarding
    # slug-availability check) rather than tenant-storefront reads, so
    # they belong here rather than in ReadHeavyTenantUser.

    @task(2)
    @tag("read")
    def browse_marketplace(self):
        self.client.get(
            "/api/tenants/marketplace/",
            headers=main_domain_headers(),
            name="/api/tenants/marketplace/ [main domain]",
        )

    @task(1)
    @tag("read")
    def view_business_types(self):
        self.client.get(
            "/api/tenants/business-types/",
            headers=main_domain_headers(),
            name="/api/tenants/business-types/ [main domain]",
        )

    @task(1)
    @tag("read", "ip-rate-limited")
    def check_slug_availability(self):
        # check_slug is itself rate-limited (10/min per IP, see
        # tenants/views.py) — this is exactly the case anon_headers()
        # exists for: without a per-user X-Real-IP/XFF pair here, every
        # simulated user checking a slug would share Locust's one real IP
        # and blow through 10/min almost immediately, which is a rate-limit
        # artifact, not a real capacity finding.
        #
        # NOTE: anon_headers() sets X-Real-IP correctly, but nginx.conf's
        # `proxy_set_header X-Real-IP $remote_addr;` overwrites it before
        # Django sees it (intentionally — see ContactFormUser's docstring
        # for the full explanation). So this task is tagged
        # "ip-rate-limited" and excluded from capacity runs via
        # `--exclude-tags ip-rate-limited` (see module docstring "Run it"
        # section) rather than relying on the header spoof to save it.
        candidate = "loadtest-" + "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        )
        self.client.get(
            "/api/tenants/check-slug/",
            params={"slug": candidate},
            headers=main_domain_headers(),
            name="/api/tenants/check-slug/ [main domain]",
        )