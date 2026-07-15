from .base import *

# ── SQLite — no PostgreSQL needed locally ────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
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
CELERY_TASK_EAGER_PROPAGATES = True

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
# MED-2 FIX: Removed dead globals().pop('STATICFILES_STORAGE', None) — base.py
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
