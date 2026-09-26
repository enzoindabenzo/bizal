# Load Testing — Performance arm of the thesis research question

This directory answers the "performance" part of the research question:

> Sa një platformë SaaS multi-tenant e konfigurueshme mund të reduktojë kohën
> dhe përpjekjen për krijimin e portaleve dixhitale për biznese të ndryshëm,
> me fokus në izolimin e të dhënave, **performancën** dhe përdorshmërinë?

## What's here

- `locustfile.py` — a [Locust](https://locust.io) load test that simulates
  concurrent traffic against multiple tenants at once: mostly anonymous
  browsing (storefront pages, tenant info, menu), plus a smaller share of
  writes (booking submissions), plus a baseline main-domain user for
  comparison. Tenant identity is set via the `Host` header — the same
  technique the existing test suite already uses (see `tenants/tests.py`,
  `HTTP_HOST=<slug>.bizal.al`) — so it needs no real wildcard DNS to run
  locally or in CI.

## How to run it

```bash
cd backend
pip install locust
python seed.py                              # if DB isn't already seeded
python manage.py runserver 0.0.0.0:8000     # terminal 1

locust -f loadtest/locustfile.py --host=http://localhost:8000   # terminal 2
```

**PowerShell** (Windows, no WSL): same commands, run `runserver` in its own
window since it blocks the terminal, then Locust in a second window —
there's nothing bash-specific about either line above, so no translation
needed for this block. The `&&`/`\` issue only shows up in the *chained*
and *multi-line* commands further below.

Then open http://localhost:8089, set number of users and spawn rate, and
start. For a scripted/CI-style run without the web UI:

```bash
locust -f loadtest/locustfile.py --host=http://localhost:8000 \
  --headless -u 50 -r 10 --run-time 60s --csv=results/run1
```

**PowerShell:**

```powershell
locust -f loadtest/locustfile.py --host=http://localhost:8000 `
  --headless -u 50 -r 10 --run-time 60s --csv=results/run1
```

(backtick `` ` `` for line continuation instead of bash's `\` — or just put
it all on one line, which sidesteps PowerShell's whitespace-after-backtick
gotcha entirely.)

This produces `run1_stats.csv` (per-endpoint p50/p95/p99, req/s, failure
rate) and `run1_stats_history.csv` (same, over time) — both directly
usable as tables/graphs in the thesis writeup.

Or, from the repo root, use the Makefile shortcut (assumes the server is
already running and seeded):

```bash
make loadtest                                    # 50 users, 60s, defaults
make loadtest USERS=200 SPAWN_RATE=20 RUN_TIME=120s
make loadtest HOST=https://staging.bizal.al       # against a real deployment
```

Results are timestamped automatically into `loadtest/results/`.

## Baseline result (2026-07-31, this environment)

A 30-user, 30-second run against `manage.py runserver` (single dev process,
SQLite, no gunicorn/nginx — i.e. the *worst-case* deployment, not
production) — raw CSV committed at
`results/baseline_devserver_20260731_stats.csv`:

| Endpoint | Requests | Failures | Median | p95 | Max |
|---|---|---|---|---|---|
| `POST /api/bookings/` | 40 | 0 | 22ms | 89ms | 160ms |
| `GET /api/menu/` | 50 | 0 | 11ms | 31ms | 45ms |
| `GET /api/reviews/` | 65 | 0 | 10ms | 42ms | 216ms |
| `GET /api/storefront/pages/` | 102 | 0 | 9ms | 38ms | 104ms |
| `GET /api/tenants/info/` | 96 | 0 | 8ms | 34ms | 59ms |
| `GET /health/` (main domain) | 29 | 0 | 4ms | 15ms | 52ms |
| **Aggregated** | **382** | **0 (0%)** | **9ms** | **44ms** | **216ms** |

**0% failure rate across ~380 requests spanning 6 tenants and both
read/write traffic**, median response time single-digit milliseconds even
on the unoptimized dev server (13 req/s throughput at this load level).
This is a *floor*, not a ceiling — the real thesis run should scale well
beyond 30 concurrent users (e.g. 100–500) against a production-like stack
(`docker-compose.prod.yml`, gunicorn, Postgres) to find the actual breaking
point.

**Note on an earlier failed run**: a prior attempt at this same test showed
a 91% failure rate — traced to `no such table: tenants_tenant`, i.e. an
empty/unmigrated local database, not an application bug. Included here as
a reminder: always confirm `python manage.py migrate && python seed.py`
ran successfully against the *current* `db.sqlite3` before trusting a load
test's failure rate — a broken test environment produces failures that
look like a performance/isolation problem but aren't one. Worth a sentence
in the thesis methodology section as a documented pitfall.

## Rate limiting at higher user counts (read before running 500+)

`bizal/throttles.py` gates anonymous traffic per client IP: `public_read`
(storefront/menu/reviews/tenant-info reads) at 3000/hour, plain `anon`
(booking POSTs) at 1000/hour. Locust runs every simulated user from one
real machine, so all of them would otherwise share a single IP's bucket —
at 500+ users that budget is gone in seconds and the run fills up with
429s that look like a capacity failure but are really just "many browsers,
one IP", not what real concurrent visitors look like.

`locustfile.py` already works around this: every simulated user gets a
unique fake `X-Forwarded-For` (see the module docstring, "A note on rate
limiting", for why this is a legitimate fix and not a bypass). No extra
flags needed — this applies at every user count, including the 30/100
runs above.

## 1000-user run

```bash
cd backend
python manage.py migrate && python seed.py     # confirm DB is seeded — see
                                                 # the "earlier failed run" note above
python manage.py runserver 0.0.0.0:8000         # terminal 1

# terminal 2 — ramp to 1000 over ~20s (50/s) rather than spawning all at
# once; a sudden step to 1000 measures Locust's own connection-open burst
# as much as the server's actual behaviour under sustained load
locust -f loadtest/locustfile.py --host=http://localhost:8000 \
  --headless -u 1000 -r 50 --run-time 3m --csv=results/run_1000users \
  --processes -1   # use all local CPU cores for the Locust workers
                    # themselves — at 1000 users a single-process Locust
                    # can itself become the bottleneck before the server
                    # does, which would misrepresent BizAL's capacity
```

Or via the Makefile shortcut:

```bash
make loadtest USERS=1000 SPAWN_RATE=50 RUN_TIME=3m
```

(the Makefile target doesn't pass `--processes`; add it directly via the
`locust` command above if a single core turns out to be the bottleneck —
watch Locust's own CPU usage during the run, not just the response-time
graph, to tell the two apart.)

`manage.py runserver` is a single-threaded dev server — it is the
*worst-case* deployment (see the 30-user baseline table below), so a
1000-user run against it will likely show real degradation that a
production Docker/gunicorn stack would not. Worth running the same command
with `--host=https://staging.bizal.al` or against `docker-compose.prod.yml`
locally, and reporting both numbers in the thesis: dev-server ceiling vs.
production-like ceiling.

## Suggested experiment for the thesis

1. **Baseline**: current 20-second smoke test above (already done).
2. **Scale test**: repeat at 50, 100, 200, 500, 1000 concurrent users against
   the production Docker stack; plot req/s and p95 latency vs. user count to
   find the point where latency or failure rate starts degrading.
3. **Isolation-under-load test**: run two Locust processes simultaneously —
   one hammering a single tenant (`WriteHeavyTenantUser` only, high user
   count), another doing light reads against a *different* tenant — and
   compare that second tenant's p95 with vs. without the first process
   running. A small delta supports the "data/resource isolation holds under
   load" claim; a large delta is itself a legitimate, honest finding worth
   discussing in the limitations section.