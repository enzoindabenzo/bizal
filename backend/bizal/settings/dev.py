"""
BizAL — Docker dev settings.

Loaded via DJANGO_SETTINGS_MODULE=bizal.settings.dev, set by docker-compose.yml
for the web, spa, celery, and celery-beat services. This module previously
didn't exist at all — docker-compose referenced it but the file was never
created, so `docker compose up` failed immediately with
`ModuleNotFoundError: No module named 'bizal.settings.dev'` on every service.

This is distinct from settings/local.py, which is for running Django
directly on the host (via manage.py / activate.ps1) against SQLite with no
Docker, no Redis, and Celery in eager mode. This module is for the
Dockerized stack: real Postgres, real Redis, real (non-eager) Celery
workers — close to production, but with relaxed security so HTTP-only
localhost access works without HTTPS.

L-2 FIX WARNING: Do NOT use this settings module directly on the host
(e.g. `DJANGO_SETTINGS_MODULE=bizal.settings.dev python manage.py runserver`).
It inherits CompressedManifestStaticFilesStorage from base.py, which raises
`ValueError: Missing staticfiles.json manifest` unless `collectstatic` has
been run first. For host-side development without Docker, use
`bizal.settings.local` instead (SQLite, eager Celery, no manifest storage).
"""
import os
from .base import *  # noqa: F401,F403

DEBUG = True

# ── Static files — inherited from base.py, Docker-stack assumption ──────
# This module does not override STATICFILES_STORAGE, so it inherits
# base.py's 'whitenoise.storage.CompressedManifestStaticFilesStorage',
# which requires a prior `collectstatic --noinput` run to generate
# staticfiles.json. docker-compose.yml's `web` service command runs
# collectstatic before runserver, writing staticfiles.json to the shared
# ./backend:/app bind-mount volume. The `spa` service does NOT run
# collectstatic at all — it simply reads the manifest that `web` already
# wrote to the shared volume.
# LOW-1 FIX: updated comment; old wording implied spa still ran collectstatic
# but relied on the shared volume to avoid duplication, which was misleading.
#
# NOTE (LOW-2 FIX): This dev-stack behaviour (spa reads web's manifest via
# the shared bind-mount) intentionally differs from docker-compose.prod.yml,
# where web and spa do NOT share a staticfiles volume and each container runs
# its own collectstatic independently (same image → identical content).  The
# prod design avoids a shared volume dependency; the dev design avoids the
# extra collectstatic run during development where startup speed matters more.
#
# If you instead run `manage.py runserver` directly on the host with
# DJANGO_SETTINGS_MODULE=bizal.settings.dev (skipping Docker and
# collectstatic), you will hit `ValueError: Missing staticfiles.json
# manifest`. Use settings/local.py for that workflow instead — it
# overrides STATICFILES_STORAGE to the plain StaticFilesStorage that
# doesn't need a manifest.

# ── Database — Celery worker connection lifecycle ────────────────────────
# base.py sets CONN_MAX_AGE from DB_CONN_MAX_AGE (default 60s), which is the
# right call for the web/spa services: gunicorn/runserver handles one
# request per thread inside one long-lived process, so reusing a
# connection across requests for up to 60s is a meaningful speedup.
#
# Celery workers are a different lifecycle. The `celery worker` command
# forks N child processes (--concurrency=N) from one parent at startup.
# If the parent process ever opens a DB connection before forking — and
# Django's connection handling means it's easy to do this by accident,
# e.g. via an app-ready signal or an eagerly-evaluated queryset at import
# time — every forked child inherits the *same* underlying socket/file
# descriptor for that connection. Two processes then read and write the
# same TCP stream, which corrupts both connections in ways that surface as
# confusing, intermittent errors (`SSL SYSCALL error`, `server closed the
# connection unexpectedly`, results from worker A appearing in worker B's
# query) — and CONN_MAX_AGE makes this worse, not better, because it's the
# setting that keeps a connection alive long enough to be inherited across
# a fork in the first place, rather than being closed before the next one
# happens.
#
# Forcing CONN_MAX_AGE=0 for Celery removes persistent connections only
# for the worker process — each task opens a fresh connection and Django
# closes it when the task's request/response cycle equivalent ends. This
# is the standard, idiomatic Celery+Django fix (see Celery's "Django"
# docs section on database connections). The web/spa services are
# unaffected since they load this same dev.py but are not Celery —
# CELERY_WORKER_RUNNING below only applies the override under `celery`.
#
# This is set via an env var read at process start (CELERY_WORKER_RUNNING),
# rather than detected from sys.argv, so it works the same way regardless
# of how the worker is invoked (bare `celery -A bizal worker`, supervisord,
# a custom entrypoint, etc.) — docker-compose.yml sets this explicitly for
# the celery and celery-beat services only.
if os.environ.get('CELERY_WORKER_RUNNING') == 'true':
    DATABASES['default']['CONN_MAX_AGE'] = 0

# ── CORS — local dev only ────────────────────────────────────────────────
# web (8000) and spa (8001) run as separate origins in the Docker stack;
# the SPA's fetch() calls to the main API need this to not be blocked.
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://localhost:8001',
    'http://127.0.0.1:8000',
    'http://127.0.0.1:8001',
]
# CORS_ALLOW_CREDENTIALS is set in base.py (inherited here) — no override needed.

# ── CSRF — same issue as local.py: base.py's default CSRF_TRUSTED_ORIGINS
# is https://bizal.al / https://*.bizal.al (production domains), which
# doesn't match the Docker dev stack's plain-HTTP localhost origins. This
# is what produces "CSRF token from POST incorrect" when POSTing to
# /django-admin/ against the Docker stack.
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://localhost:8001',
    'http://127.0.0.1:8000',
    'http://127.0.0.1:8001',
]

# ── Email — print to console instead of SMTP in dev ──────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ── Stripe dummy keys — overridden by real test keys via .env if needed ──
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', 'sk_test_dummy_dev')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', 'whsec_dummy_dev')

# ── Demo links — rewrite marketing site's subdomain links to the local spa ──
# The Docker dev stack's spa service is published to the host at 8001
# (docker-compose.yml), and tenant resolution there uses ?tenant=<slug>
# rather than subdomains, so the *.bizal.al demo links in main.html are
# unreachable as-is without this.
DEMO_BASE_URL = os.environ.get('DEMO_BASE_URL', 'http://localhost:8001')
