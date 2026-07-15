"""
BizAL — production settings.

Loaded via DJANGO_SETTINGS_MODULE=bizal.settings.production (see
docker-compose.yml). Everything here builds on top of base.py and adds the
hardening that only makes sense once the app is sitting behind real traffic:
forced HTTPS, secure cookies, HSTS, persistent DB connections, and a
LOGGING config so errors are visible instead of disappearing into gunicorn
stdout.
"""
import os
from urllib.parse import urlparse
from django.core.exceptions import ImproperlyConfigured
from .base import *  # noqa: F401,F403

# ── Startup guard: reject the default placeholder SECRET_KEY ─────────────────
# base.py falls back to 'change-me-in-production' when SECRET_KEY is not set.
# Using that value in production is a critical security misconfiguration that
# allows session forgery and signature bypass. Reject it at startup instead of
# silently running with a known-weak key.
_secret = os.environ.get('SECRET_KEY', '')
# LOW-1 FIX: also reject the docker-compose dev placeholder so operators who
# accidentally run docker-compose.yml in production without an .env override
# get a clear error instead of running with a known-public key.
_dev_placeholders = {'change-me-in-production', 'dev-secret-key-change-in-production'}
if not _secret or _secret in _dev_placeholders:
    raise ImproperlyConfigured(
        "SECRET_KEY is not set or is still a development placeholder. "
        "Set a strong random SECRET_KEY in your environment before deploying."
    )

# ── Startup guard: reject DEBUG=True in production ───────────────────────────
# A forgotten DEBUG=True exposes stack traces, settings values, and disables
# security checks. Fail fast at startup rather than silently running unsafe.
if os.environ.get('DEBUG', 'False').lower() in ('1', 'true', 'yes'):
    raise ImproperlyConfigured(
        "DEBUG must be False in production. "
        "Remove DEBUG=True (or set DEBUG=False) from your environment."
    )

# ── HTTPS / cookie security ──────────────────────────────────────────────
# nginx terminates TLS and proxies to gunicorn over plain HTTP, so Django
# needs to trust the X-Forwarded-Proto header nginx sets to know a request
# was originally HTTPS (otherwise SECURE_SSL_REDIRECT loops forever).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# MED-3 FIX: Allow SECURE_SSL_REDIRECT to be disabled via env var until TLS is
# provisioned on nginx. nginx/nginx.conf currently serves HTTP only; deploying
# with SECURE_SSL_REDIRECT=True before TLS is configured causes an infinite
# redirect loop (Django redirects to https://, nginx serves http:// only).
# Set SECURE_SSL_REDIRECT=true in the environment only after obtaining a
# wildcard cert and enabling the HTTPS server blocks in nginx/nginx.conf.
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False').lower() in ('1', 'true', 'yes')
# MED-2 FIX: only emit HSTS headers (and submit to preload lists) when TLS is
# actually active. Sending HSTS before HTTPS is provisioned locks browsers out
# of all *.bizal.al subdomains over HTTP for a year.
if SECURE_SSL_REDIRECT:
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# ── Database — persistent connections ────────────────────────────────────
# base.py already sets CONN_MAX_AGE from DB_CONN_MAX_AGE (default 60s);
# this just makes the production default explicit even if that env var
# isn't set.
DATABASES['default']['CONN_MAX_AGE'] = int(os.environ.get('DB_CONN_MAX_AGE', 60))

# Celery workers fork N child processes from one parent (--concurrency=N).
# A persistent connection opened before that fork is shared (the same
# underlying socket) across every child, corrupting all of them — see the
# long comment in settings/dev.py for the full mechanism. Set
# CELERY_WORKER_RUNNING=true in the Celery worker/beat service environment
# (not web/gunicorn) to force connections closed between tasks instead.
# bizal/celery.py also calls close_old_connections() on every worker fork
# as defense-in-depth, in case this env var is ever missing from a deploy.
if os.environ.get('CELERY_WORKER_RUNNING') == 'true':
    DATABASES['default']['CONN_MAX_AGE'] = 0

# ── Admins — required for the 'mail_admins' LOGGING handler below ───────
# AdminEmailHandler silently does nothing if ADMINS is empty, so without
# this, django.request errors (500s) were logged to console only and
# never reached anyone's inbox in production.
ADMINS = [('BizAL Admin', os.environ.get('ADMIN_EMAIL', 'admin@bizal.al'))]

# AdminEmailHandler sends from SERVER_EMAIL, not DEFAULT_FROM_EMAIL — Django
# defaults this to 'root@localhost', which most SMTP providers reject outright,
# so error alert emails would fail to send without ever raising in app code.
SERVER_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@bizal.al')

# ── Logging — surface errors instead of losing them in gunicorn stdout ──
# Builds on base.py's LOGGING rather than fully redefining it, so the
# mail_admins handler and per-app loggers (accounts, analytics,
# notifications, celery) defined there aren't silently dropped here.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
            'filters': ['require_debug_false'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
        # App loggers — INFO so things like trial expiry / referral credit
        # application are visible without cranking the whole app to DEBUG.
        'tenants': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'billing': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'accounts': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'analytics': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'notifications': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


# ── Startup guard: reject wildcard ALLOWED_HOSTS syntax ──────────────────────
# Django does NOT support *.domain.com — only .domain.com (leading dot).
# If someone copies .env.example and uses *.bizal.al, Django boots fine but
# every request from a tenant subdomain raises DisallowedHost (HTTP 400)
# with no useful error message. Fail loudly at startup instead.
# LOW-4 FIX: use top-level ImproperlyConfigured import (already imported at top of file)
for _host in os.environ.get('ALLOWED_HOSTS', '').split(','):
    _host = _host.strip()
    if _host.startswith('*.'):
        raise ImproperlyConfigured(
            f"ALLOWED_HOSTS contains '{_host}' which uses glob syntax (*.domain) "
            "that Django does not support. Use '.domain.com' (leading dot) to allow "
            "all subdomains. Tenant subdomain requests will be rejected until fixed."
        )

# ── Startup guard: Docker health checks require localhost/127.0.0.1 ────────────
# CRIT-1 FIX: docker-compose.prod.yml health checks hit
# http://localhost:PORT/health/ from inside the container, which sends
# "Host: localhost". Django's ALLOWED_HOSTS check runs before the view, so
# if localhost/127.0.0.1 aren't allowed, every health check returns 400 and
# Docker marks the container unhealthy forever, deadlocking every service
# that waits on `condition: service_healthy` (celery, celery-beat, nginx).
# Fail fast with a clear message instead of a silent stack-wide deadlock.
_allowed_hosts_list = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
_missing_health_hosts = {'localhost', '127.0.0.1'} - set(_allowed_hosts_list)
if _missing_health_hosts:
    raise ImproperlyConfigured(
        f"ALLOWED_HOSTS is missing {sorted(_missing_health_hosts)}. Docker health "
        "checks use 'curl http://localhost:PORT/health/' which requires these "
        "entries to be present. Without them, all health-gated services (celery, "
        "celery-beat, nginx) will never start. Add 'localhost,127.0.0.1' to "
        "ALLOWED_HOSTS in your production environment."
    )

# ── Startup guard: catch localhost URLs in production emails ───────────────────
# If FRONTEND_BASE_URL was never set in the environment, it defaults to
# 'http://localhost:8000' (see base.py).  In production that means every
# trial-expiry and warning email contains a localhost link — useless to
# the recipient and embarrassing.  Fail fast at startup rather than
# silently sending broken emails to real users.

# (ImproperlyConfigured already imported above)

_frontend_url = os.environ.get('FRONTEND_BASE_URL', '')
if not _frontend_url or 'localhost' in _frontend_url or '127.0.0.1' in _frontend_url:
    raise ImproperlyConfigured(
        'FRONTEND_BASE_URL is not set or still points to localhost in production. '
        'Trial-expiry emails will contain broken links. '
        'Set FRONTEND_BASE_URL=https://bizal.al in your environment.'
    )
# MEDIUM-2 FIX: strip any trailing slash so URL construction never produces
# double-slash paths (e.g. https://bizal.al//verify-email/...).
_frontend_url = _frontend_url.rstrip('/')
# HIGH-1 FIX: assign the stripped value back to the Django setting so that
# every view and task reading settings.FRONTEND_BASE_URL gets the
# normalised (no trailing slash) value. Previously only the local variable
# _frontend_url was updated; settings.FRONTEND_BASE_URL (set from env in
# base.py) was never overwritten, so operators who set
# FRONTEND_BASE_URL=https://bizal.al/ still got double-slash URLs in all
# generated emails and Stripe redirect URLs.
FRONTEND_BASE_URL = _frontend_url

# L-3 FIX: FRONTEND_BASE_URL must be the main domain (bizal.al), never a
# tenant subdomain (e.g. https://hertz.bizal.al). bizal/views.py's
# admin_panel() redirects main-domain traffic to '/django-admin/', the
# single platform-admin surface. If FRONTEND_BASE_URL were itself a tenant
# subdomain, links built from it (e.g. in emails) would land on a subdomain
# where TenantMiddleware's main-domain-only check 404s /django-admin/.
# Parse the hostname rather than substring-matching '.bizal.al' (which
# would also flag the correct value 'https://bizal.al' itself).
_frontend_host = (urlparse(_frontend_url).hostname or '').lower()
# M-1 FIX: The original check (`_frontend_host != 'bizal.al'`) was too strict —
# it rejected staging.bizal.al, demo.bizal.al, and any white-label domain, making
# production.py unusable for staging/UAT environments. The actual risk is only a
# *tenant* subdomain (e.g. hertz.bizal.al) being set as FRONTEND_BASE_URL, which
# would make /django-admin/ links resolve to a 404 on that subdomain. Reject only those.
_is_tenant_subdomain = (
    _frontend_host.endswith('.bizal.al')
    and not _frontend_host.startswith('www.')
    and _frontend_host not in ('staging.bizal.al', 'demo.bizal.al', 'app.bizal.al')
)
if _is_tenant_subdomain:
    raise ImproperlyConfigured(
        f"FRONTEND_BASE_URL is set to '{_frontend_url}', which resolves to host "
        f"'{_frontend_host}'. This looks like a tenant subdomain — set it to the "
        "main platform domain instead (e.g. https://bizal.al or https://staging.bizal.al)."
    )


# ── Sentry — error tracking ───────────────────────────────────────────────────
# Set SENTRY_DSN in .env to enable. Safe to leave unset (Sentry SDK skips
# init if DSN is empty, so no crashes in environments without it).
_sentry_dsn = os.environ.get('SENTRY_DSN', '')
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[
            DjangoIntegration(
                transaction_style='url',
                middleware_spans=True,
            ),
            CeleryIntegration(monitor_beat_tasks=True),
            RedisIntegration(),
        ],
        # Dërgo 10% të transaksioneve për performance monitoring.
        # Nis me 0.1 dhe rregulloje sipas volumit.
        traces_sample_rate=0.1,
        # Mos dërgo PII (email, IP) te Sentry.
        send_default_pii=False,
        environment='production',
        release=os.environ.get('APP_VERSION', 'unknown'),
    )

# HIGH-2 FIX (v36): Override CORS_ALLOWED_ORIGIN_REGEXES to drop the http://
# variant for production. base.py uses r'^https?://.*\.bizal\.al$' which
# permits unencrypted http:// origins — with CORS_ALLOW_CREDENTIALS=True a
# network attacker could intercept credentialed cross-origin responses.
# The localhost entry (http://localhost:\d+) remains in dev.py / local.py only.
# LOW-1: This also serves as the explicit CORS documentation for production.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^https://([a-zA-Z0-9-]+\.)?bizal\.al$',
]
