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

# ── Email prints to console ──────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ── Stripe dummy keys ────────────────────────────────────────
STRIPE_SECRET_KEY    = 'sk_test_dummy_local'
STRIPE_WEBHOOK_SECRET = 'whsec_dummy_local'

# ── Dev settings ─────────────────────────────────────────────
DEBUG      = True
SECRET_KEY = 'local-dev-secret-key-not-for-production'
ALLOWED_HOSTS = ['*']

# ── Allow slug.localhost subdomains ──────────────────────────
# No special Django setting needed — wildcard ALLOWED_HOSTS covers it

# ── Faster static files in dev ──────────────────────────────
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
