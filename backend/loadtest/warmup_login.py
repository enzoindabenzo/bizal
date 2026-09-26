r"""
BizAL — Load-test warm-up login (Round 3)
===========================================

Purpose
-------
Pre-authenticates every account locustfile.py's login-based user classes
(AuthenticatedCustomerUser, TenantOwnerUser, AdminPlatformUser) need, ONE
AT A TIME with enough delay between requests to stay under the login
endpoint's throttle, and caches the resulting JWTs to .token_cache.json
next to this file. locustfile.py reads that cache at import time so none
of those user classes have to call /api/auth/login/ during the timed
soak itself.

Why this exists
----------------
CustomTokenObtainPairView is rate-limited 5/min PER IP (see
accounts/views.py, keyed via bizal/ratelimit_utils.py off X-Real-IP), and
nginx.conf's unconditional `proxy_set_header X-Real-IP $remote_addr;`
collapses every request — no matter what headers the client sends — onto
whatever machine is actually running the load generator. Spawning 500
simulated users that each try to log in within the same few seconds blows
through 5/min almost instantly (this is exactly what produced the 1,369
login 403s in run_500u_soak_expanded). That's a login-TIMING problem, not
a capacity problem, and it can't be fixed by spoofing headers the way the
anonymous-traffic throttles in locustfile.py are — timing is the only
fix: do the logins slowly, before the timed window starts, then reuse the
tokens.

Access tokens last 60 minutes (SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'],
settings/base.py) — comfortably longer than this warm-up (12 logins x 13s
delay =~ 2.5 min) plus even a 15-minute soak, so run this once immediately
before each locust run.

Usage
-----
    cd backend
    pip install requests
    python loadtest/warmup_login.py --host http://localhost:8000

Same SEED_* environment variables as locustfile.py/seed.py control which
accounts actually get logged in — an account whose password env var isn't
set is skipped (not an error), same "no wall of 401s" philosophy as
locustfile.py's own on_start() skip-if-unset checks.
"""

import argparse
import datetime
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print(
        "This script needs the 'requests' package (separate from Locust's own "
        "HTTP client): pip install requests",
        file=sys.stderr,
    )
    raise

CUSTOMER_EMAIL = "customer@demo.al"
CUSTOMER_PASSWORD = os.environ.get("SEED_CUSTOMER_PASSWORD")

ADMIN_EMAIL = "admin@bizal.al"
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD")

# Same slug/email/password-env-var triples as locustfile.py's ALL_OWNERS
# and seed.py's own OWNER_PASSWORD_* variables — keep these two lists in
# sync if seed.py ever adds/removes a tenant owner.
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

TOKEN_CACHE_PATH = os.path.join(os.path.dirname(__file__), ".token_cache.json")

# 5/min per IP = 12s minimum between logins to stay under the limit. 13s
# leaves a small margin (clock drift between this script's sleep() and
# django-ratelimit's own window boundaries).
DEFAULT_DELAY_SECONDS = 13.0


def _login(host: str, email: str, password: str, host_header: str, label: str):
    """One login attempt. Returns the access token on success, None on any
    failure (bad credentials, throttled, network error, unexpected shape)
    — the caller decides whether that's fatal; this function never raises
    for an ordinary failed-login response."""
    try:
        resp = requests.post(
            f"{host}/api/auth/login/",
            json={"email": email, "password": password},
            headers={"Host": host_header},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"  ✗ {label}: request failed ({exc})")
        return None
    if resp.status_code != 200:
        print(f"  ✗ {label}: HTTP {resp.status_code} — {resp.text[:200]}")
        return None
    try:
        token = resp.json().get("access")
    except ValueError:
        token = None
    if not token:
        print(f"  ✗ {label}: 200 response but no 'access' token in body")
        return None
    print(f"  ✓ {label}")
    return token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=os.environ.get("LOCUST_HOST", "http://localhost"),
        help="Base URL of the running backend, e.g. http://localhost:8000 "
        "(default: $LOCUST_HOST or http://localhost)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds between login attempts (default: {DEFAULT_DELAY_SECONDS}, "
        "stays under the 5/min per-IP login throttle)",
    )
    parser.add_argument(
        "--out",
        default=TOKEN_CACHE_PATH,
        help=f"Where to write the token cache (default: {TOKEN_CACHE_PATH})",
    )
    args = parser.parse_args()

    # Build the full job list up front so we know how many *actual* login
    # attempts there are (skipped/unconfigured accounts don't consume a
    # delay slot).
    jobs = []
    if CUSTOMER_PASSWORD:
        jobs.append(("customer", CUSTOMER_EMAIL, CUSTOMER_PASSWORD, "bizal.al", "customer@demo.al"))
    else:
        print("- SEED_CUSTOMER_PASSWORD not set, skipping customer login")
    for owner in ALL_OWNERS:
        if owner["password"]:
            jobs.append(("owner", owner["email"], owner["password"],
                         f"{owner['slug']}.bizal.al", f"{owner['email']} ({owner['slug']})"))
        else:
            print(f"- password env var not set for {owner['slug']}, skipping")
    if ADMIN_PASSWORD:
        jobs.append(("admin", ADMIN_EMAIL, ADMIN_PASSWORD, "bizal.al", "admin@bizal.al"))
    else:
        print("- SEED_ADMIN_PASSWORD not set, skipping admin login")

    if not jobs:
        print(
            "\nNo SEED_* password env vars are set at all — nothing to log in. "
            "Set the same env vars seed.py uses (SEED_CUSTOMER_PASSWORD, "
            "SEED_OWNER_PASSWORD_*, SEED_ADMIN_PASSWORD) and re-run."
        )
        sys.exit(1)

    print(f"Logging in {len(jobs)} account(s) against {args.host}, "
          f"{args.delay:.0f}s apart (~{len(jobs) * args.delay / 60:.1f} min total)...\n")

    cache = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
        "host": args.host,
        "customer": None,
        "admin": None,
        "owners": [],
    }

    for i, (kind, email, password, host_header, label) in enumerate(jobs):
        token = _login(args.host, email, password, host_header, label)
        if kind == "customer":
            cache["customer"] = token
        elif kind == "admin":
            cache["admin"] = token
        elif kind == "owner" and token:
            slug = host_header.rsplit(".bizal.al", 1)[0]
            cache["owners"].append({"slug": slug, "token": token})
        if i < len(jobs) - 1:
            time.sleep(args.delay)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

    n_owners = len(cache["owners"])
    print(
        f"\nWrote {args.out}\n"
        f"  customer: {'ok' if cache['customer'] else 'missing/failed'}\n"
        f"  owners:   {n_owners}/{sum(1 for o in ALL_OWNERS if o['password'])} configured owners logged in\n"
        f"  admin:    {'ok' if cache['admin'] else 'missing/failed'}\n"
    )
    if n_owners == 0 and not cache["customer"] and not cache["admin"]:
        print("Every login failed — check credentials/host before running locust.")
        sys.exit(1)


if __name__ == "__main__":
    main()