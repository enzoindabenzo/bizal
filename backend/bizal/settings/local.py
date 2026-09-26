from .base import *

# ── SQLite — no PostgreSQL needed locally ────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        # 'timeout' (seconds) controls how long SQLite waits for the
        # write lock before raising "database is locked", not Django's
        # own DB-level query timeout. Default is 5s; raised here because
        # load testing at 200+ concurrent users produced occasional
        # "database is locked" errors on POST /api/bookings/ and
        # /api/auth/login/ — SQLite only allows one writer at a time, so
        # under concurrent write load some requests were waiting longer
        # than 5s for their turn. This trades "fail fast" for "wait
        # longer, then usually succeed" — appropriate for a load-testing
        # / dev environment; production uses Postgres, which handles
        # concurrent writers properly and doesn't need this.
        'OPTIONS': {'timeout': 30},
    }
}

# ── No Redis needed locally ──────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# ── Silence django-ratelimit (no shared cache in dev) ────────
RATELIMIT_ENABLE = False
SILENCED_SYSTEM_CHECKS = ['django_ratelimit.E003', 'django_ratelimit.W001']

# ── Celery runs synchronously ────────────────────────────────
CELERY_TASK_ALWAYS_EAGER = True
# EAGER_PROPAGATES=False: a failed eager task (e.g. the owner-notification
# task hitting SQLite's write lock under concurrent load) now logs and
# moves on instead of raising up into the HTTP request that triggered it.
# Was True — good for catching genuinely broken tasks during normal dev
# work, but under a Locust load test it turned an internal, retryable
# notification-write failure into a 500 on the booking/login request
# itself, which isn't what production's real async worker would do.
CELERY_TASK_EAGER_PROPAGATES = False

# ── Email — print to console instead of SMTP in local dev ───
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ── Stripe dummy keys ────────────────────────────────────────
STRIPE_SECRET_KEY    = 'sk_test_dummy_local'
STRIPE_WEBHOOK_SECRET = 'whsec_dummy_local'

# ── Demo links — same convention as dev.py: rewrite the marketing site's
# hardcoded *.bizal.al demo links to the local spa on port 8001, using
# ?tenant=<slug> tenant resolution (see README.md).
DEMO_BASE_URL = 'http://localhost:8001'

# ── Dev settings ─────────────────────────────────────────────
DEBUG      = True
SECRET_KEY = 'local-dev-secret-key-not-for-production'
ALLOWED_HOSTS = ['*']

# ── CORS — allow all origins in local dev ───────────────────
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
]
# CORS_ALLOW_CREDENTIALS is set in base.py (inherited here) — no override needed.

# ── CSRF — base.py's default CSRF_TRUSTED_ORIGINS is https://bizal.al /
# https://*.bizal.al, which is correct for production but matches nothing
# in local dev (plain HTTP on localhost). Without this override, any POST
# to /django-admin/, /admin/, /onboarding/, etc. run via `manage.py
# runserver` locally fails CSRF's Referer check exactly like this ticket's
# "CSRF token from POST incorrect" error.
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# ── Faster static files in dev ──────────────────────────────
# Removed dead globals().pop('STATICFILES_STORAGE', None) — base.py
# sets STORAGES (the Django 4.2+ dict API), not the legacy STATICFILES_STORAGE
# string, so the pop was a no-op and its comment was factually wrong.
# Override STORAGES directly to use plain filesystem storage in local dev
# (no manifest hashing needed — avoids collectstatic requirements locally).
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}