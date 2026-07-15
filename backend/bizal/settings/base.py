import os
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _t

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # bizal/backend/
FRONTEND_DIR = BASE_DIR.parent / 'frontend'               # bizal/frontend/

# Load backend/.env into os.environ for local (no-Docker) runs, so
# `manage.py runserver` picks up the same GROQ_API_KEY_*/OPENROUTER_API_KEY_*
# etc. that docker-compose would otherwise inject as real container env vars.
# override=False (the default) means any variable ALREADY set in the real
# environment — e.g. by docker-compose, systemd, or CI — always wins; the
# .env file only fills in gaps. Safe to leave in place across all settings
# modules (local/dev/production): if backend/.env doesn't exist (e.g. in a
# production container that doesn't ship one), this is a silent no-op.
# NOTE: .env lives at the REPO ROOT (BASE_DIR.parent), not inside backend/.
# docker-compose.yml sits at the repo root and resolves its ${VAR}
# substitutions from a .env file in its own directory by default — so
# that's already where the real .env has lived all along. BASE_DIR here is
# backend/ (see above), so BASE_DIR / '.env' would silently look in the
# wrong place: load_dotenv() does NOT raise or warn when the file is
# missing, it just loads nothing, which is why GROQ_API_KEY_1 etc. kept
# reading back as '' even after keys were added and the server restarted.
load_dotenv(BASE_DIR.parent / '.env')


def _env_int(key, default):
    """int(os.environ.get(key, default)) that also treats a blank string as
    "use default" rather than crashing.

    A line like `STAFF_REPLY_TTL=` in .env is NOT the same as the var being
    unset: python-dotenv loads it as os.environ['STAFF_REPLY_TTL'] = '', so
    os.environ.get(key, default) returns '' (the key exists), not `default`,
    and int('') raises ValueError. This bit everyone who left an optional
    numeric slot blank in .env for local (no-Docker) dev — makemigrations/
    migrate/collectstatic all pass (they don't touch this code path), but
    the crash surfaces later, non-obviously, in seed.py / manage.py runserver
    the moment Django imports settings and evaluates this line.
    """
    val = os.environ.get(key, '')
    return int(val) if val.strip() else default


SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

# NOTE: Django's wildcard-subdomain syntax uses a LEADING DOT, not an
# asterisk. '.bizal.al' matches both 'bizal.al' itself AND any subdomain
# (hertz.bizal.al, klinika.bizal.al, ...). '*.bizal.al' is NOT valid and
# would silently match nothing, causing every tenant-subdomain request to
# be rejected with DisallowedHost in production.
# LOW-3 FIX (v52): Strip whitespace from each entry. str.split(',') does not strip
# spaces, so 'bizal.al, .bizal.al' (natural human formatting) produces ' .bizal.al'
# which does NOT start with '.' and therefore fails Django's subdomain wildcard check.
# Every tenant-subdomain request would return HTTP 400 DisallowedHost.
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get(
        'ALLOWED_HOSTS', 'localhost,127.0.0.1,.localhost,bizal.al,.bizal.al'
    ).split(',')
    if h.strip()
]

# ── CSRF_TRUSTED_ORIGINS ──────────────────────────────────────────────────
# This was missing entirely, which is why POSTs to /django-admin/ (and any
# other Django-rendered POST form — tenant login, onboarding, etc.) fail
# with "CSRF token from POST incorrect / Referer checking failed". Since
# Django 4.0, CsrfViewMiddleware requires the request's Referer header to
# match either (a) the request's own scheme+host, computed from
# request.is_secure() + request.get_host(), or (b) an entry in
# CSRF_TRUSTED_ORIGINS. For plain same-origin requests (b) shouldn't be
# needed — but this app is multi-tenant over subdomains behind an nginx
# proxy, and any mismatch between the scheme Django *thinks* it's on (see
# SECURE_PROXY_SSL_HEADER in production.py) and the scheme in the
# browser's Referer header — e.g. hitting the bare domain without https://,
# a stale tab, a reverse-proxy hop that drops X-Forwarded-Proto — makes the
# same-origin check (a) fail. Listing every real origin explicitly here
# removes that fragility.
#
# NOTE the syntax difference from ALLOWED_HOSTS: CSRF_TRUSTED_ORIGINS needs
# a full scheme://host entry per origin, and Django's wildcard form is
# 'https://*.bizal.al' (leading '*', not a leading '.' like ALLOWED_HOSTS).
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        'CSRF_TRUSTED_ORIGINS', 'https://bizal.al,https://*.bizal.al'
    ).split(',')
    if o.strip()
]

# django-unfold must be listed BEFORE 'django.contrib.admin'. Its AppConfig.ready()
# swaps the default admin.site singleton for an UnfoldAdminSite; if it loaded after
# django.contrib.admin, admin's own autodiscover_modules('admin') would already be
# registering every app's @admin.register(...) models against the plain AdminSite,
# and the swap would come too late to reskin them.
DJANGO_APPS = [
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'bizal',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_ratelimit',
    'storages',
    'django_filters',
    'django_celery_beat',
]

LOCAL_APPS = [
    'tenants',
    'accounts',
    'activity',
    'billing',
    'analytics',
    'reviews',
    'notifications',
    'bookings',
    'inventory',
    'storefront',
    'appointments',
    'menu',
    'hotels',
    'rentals',
    'crm',
    'blog',
    'payments',
    'contact',
    'staff',
    'subscriptions',
    'chatbot',
    'orders',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'tenants.middleware.TenantMiddleware',
]

ROOT_URLCONF = 'bizal.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [FRONTEND_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'tenants.context_processors.tenant_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'bizal.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'bizal'),
        'USER': os.environ.get('DB_USER', 'bizal'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'bizal'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        # Persistent connections — without this every request opens a new
        # PostgreSQL connection. Override to 0 in settings/test.py if a
        # given environment needs a connection per request instead.
        'CONN_MAX_AGE': _env_int('DB_CONN_MAX_AGE', 60),
        # FIX #12: Validate stale connections before reuse. Without this,
        # CONN_MAX_AGE=60 can hand out a dead connection from the pool
        # after a DB restart or firewall timeout, causing OperationalError
        # on the first query of a new request. Django 4.1+ silently heals
        # the connection when this is True.
        'CONN_HEALTH_CHECKS': True,
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        # Separate Redis DB for cache (db/1) vs Celery broker (db/0)
        'LOCATION': os.environ.get('REDIS_CACHE_URL', 'redis://127.0.0.1:6379/1'),
        'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
    }
}

AUTH_USER_MODEL = 'accounts.User'

# Email is unique per-tenant, not globally (see accounts.models.User), so
# the default ModelBackend's plain email lookup can no longer be trusted to
# resolve to a single account. Scope authentication to request.tenant.
AUTHENTICATION_BACKENDS = [
    'accounts.auth_backends.TenantAwareModelBackend',
]


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'sq'
TIME_ZONE = 'Europe/Tirane'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [FRONTEND_DIR / 'static']
# LOW-2 FIX: use the modern STORAGES dict (Django 4.2+) instead of the legacy
# STATICFILES_STORAGE string. Django 4.2 raises ImproperlyConfigured if both
# are set simultaneously; using STORAGES here avoids that footgun if any child
# settings file ever adds a STORAGES override for cloud storage.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        # JWT only — SessionAuthentication është hequr qëllimisht.
        # SessionAuthentication kërkon CSRF token për çdo POST request,
        # gjë që shkakton 403 Forbidden në API calls nga JavaScript.
        # JWT nuk kërkon CSRF — tokens dërgohen në Authorization header.
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # NOTE: a single tenant storefront page load fires ~5 anonymous reads
        # (tenants/info, reviews, storefront/pages, appointments/services,
        # analytics/track). At 60/hour that budget is gone in ~12 page loads
        # for one visitor, after which every anon endpoint 429s — including
        # tenants/info, which is render-blocking, so the storefront is stuck
        # on the loading skeleton and even /admin/ login starts failing.
        # 'anon' stays as the catch-all default; sensitive/abuse-prone
        # endpoints (auth, contact, orders, registration) opt into the
        # stricter 'anon_sensitive' scope explicitly via throttle_classes.
        'anon': '1000/hour',
        'anon_sensitive': '60/hour',
        'public_read': '3000/hour',
        'admin_write': '5000/hour',
        'user': '1000/hour',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'PAGE_SIZE_QUERY_PARAM': 'page_size',
    'MAX_PAGE_SIZE': 100,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# FIX: Password reset tokens expire in 1 hour (Django default is 3 days).
# default_token_generator uses this setting; setting it here ensures it
# is enforced regardless of deployment environment.
PASSWORD_RESET_TIMEOUT = 3600  # 1 hour in seconds

# Stripe
# Upstream exchange-rate API used by tenants.tasks.refresh_fx_rates to keep
# the EUR/USD -> ALL rates in tenants/fx.py current. Expected response shape:
# {"rates": {"EUR": 0.0095, "USD": 0.0103, ...}} (i.e. "1 ALL = X <currency>").
# Configurable so an operator can swap providers without a code change if
# the free default endpoint changes terms or goes away; falls back to a
# hardcoded default in the task itself if unset.
FX_RATE_API_URL = os.environ.get('FX_RATE_API_URL', '')

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRICE_STARTER = os.environ.get('STRIPE_PRICE_STARTER', '')
STRIPE_PRICE_PRO = os.environ.get('STRIPE_PRICE_PRO', '')
STRIPE_PRICE_ENTERPRISE = os.environ.get('STRIPE_PRICE_ENTERPRISE', '')

# ── AI Chatbot providers ───────────────────────────────────────────────────────
# Three Groq keys + three OpenRouter keys; rotation handled in chatbot/views.py.
# Set at least one key to enable the chatbot.  Keys are tried in least-used
# order; a key is soft-rotated at 80 % usage and hard-skipped at 100 %.
GROQ_API_KEY_1        = os.environ.get('GROQ_API_KEY_1', '')
GROQ_API_KEY_2        = os.environ.get('GROQ_API_KEY_2', '')
GROQ_API_KEY_3        = os.environ.get('GROQ_API_KEY_3', '')
OPENROUTER_API_KEY_1  = os.environ.get('OPENROUTER_API_KEY_1', '')
OPENROUTER_API_KEY_2  = os.environ.get('OPENROUTER_API_KEY_2', '')
OPENROUTER_API_KEY_3  = os.environ.get('OPENROUTER_API_KEY_3', '')
# Staff reply TTL: queued staff replies expire after STAFF_REPLY_TTL seconds
# (default 600 = 10 minutes). Read in chatbot/views.py via django.conf.settings.
STAFF_REPLY_TTL = _env_int('STAFF_REPLY_TTL', 600)

# Celery — broker uses db/0; cache uses db/1 (see REDIS_CACHE_URL above);
# result backend uses db/2 (HIGH-4 FIX v36: previously shared db/0 with
# broker — FLUSHDB for cache debugging would wipe task queues, and the
# result backend's expiry-based SCAN/DEL added latency to broker keyspace).
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')
REDIS_RESULT_URL = os.environ.get('REDIS_RESULT_URL', 'redis://127.0.0.1:6379/2')
CELERY_RESULT_BACKEND = REDIS_RESULT_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

try:
    from celery.schedules import crontab  # HIGH-1 FIX: no-op callable so CELERY_BEAT_SCHEDULE
except ImportError:                        # constructs without TypeError on a Celery-less image
    def crontab(*args, **kwargs):          # type: ignore[misc]
        return None

# Periodic tasks (celery-beat)
# MED-1 NOTE: celery-beat uses DatabaseScheduler (see docker-compose.yml).
# On FIRST run Celery seeds these entries into the django_celery_beat_periodictask
# DB table. On SUBSEQUENT runs DatabaseScheduler reads from the DB, NOT from
# this dict — so changes made here after first-run will be silently ignored.
# To apply schedule changes after first deploy, either:
#   (a) Update the rows directly via Django admin → Periodic Tasks, or
#   (b) Run: python manage.py shell -c "from django_celery_beat.models import PeriodicTask; PeriodicTask.objects.all().delete()"
#       then restart celery-beat to re-seed from these settings.
#
# LOW-6 NOTE: sync_celery_schedule runs via the `web` container's entrypoint.sh
# ONLY. If you restart only the `spa` container (e.g. to pick up a static file
# change), sync_celery_schedule will NOT re-run. If you have changed the
# CELERY_BEAT_SCHEDULE dict below, you MUST also restart the `web` container
# (not just `spa`) to trigger sync_celery_schedule. Alternatively, extract
# sync_celery_schedule into a dedicated one-off init container that both
# `web` and `spa` depend on.
CELERY_BEAT_SCHEDULE = {
    # LOW-7 FIX: all hours below are UTC (stored as timezone='UTC' in
    # CrontabSchedule by sync_celery_schedule — see that command for details).
    # Albanian local time is UTC+1 (UTC+2 during DST), so operators scheduling
    # maintenance windows should account for the offset, e.g. 01:00 UTC below
    # is ~02:00-03:00 Albanian time depending on DST.
    #
    # Mark overdue invoices every day at 01:00 UTC (~02:00-03:00 Albanian time)
    'mark-overdue-invoices': {
        'task': 'billing.tasks.mark_overdue_invoices',
        'schedule': crontab(hour=1, minute=0),
    },
    # Send 24h appointment reminders — runs every hour
    'send-appointment-reminders': {
        'task': 'notifications.tasks.send_appointment_reminders',
        'schedule': crontab(minute=0),
    },
    # Trial lifecycle tasks (all times UTC)
    'expire-trials': {
        'task': 'tenants.tasks.expire_trials',
        'schedule': crontab(hour=2, minute=0),  # 02:00 UTC (~03:00-04:00 Albanian time)
    },
    'send-trial-warnings': {
        'task': 'tenants.tasks.send_trial_warning_emails',
        'schedule': crontab(hour=9, minute=0),  # 09:00 UTC (~10:00-11:00 Albanian time)
    },
    'apply-referral-credits': {
        'task': 'tenants.tasks.apply_referral_credits_for_active_tenants',
        'schedule': crontab(hour=3, minute=0),  # 03:00 UTC (~04:00-05:00 Albanian time)
    },
    # Refresh cached EUR/USD -> ALL exchange rates used by tenants/fx.py at
    # booking-checkout time (see payments.views.create_booking_checkout).
    # Hourly: there's no hardcoded fallback rate any more (see
    # tenants/fx.py), so EUR/USD payment stops being offered as soon as the
    # cached rate expires (fx._CACHE_TTL_SECONDS) — this needs to run often
    # enough that a currency doesn't flicker unavailable between runs under
    # normal conditions. A missed/failed run just leaves the last cached
    # rate in place until it expires or the next run succeeds; see
    # tenants.tasks.refresh_fx_rates.
    'refresh-fx-rates': {
        'task': 'tenants.tasks.refresh_fx_rates',
        'schedule': crontab(minute=0),
    },
    # Send 24h booking reminders — runs every hour, staggered 30 min from appointment reminders
    'send-booking-reminders': {
        'task': 'notifications.tasks.send_booking_reminders',
        'schedule': crontab(minute=30),
    },
    # Purge analytics events older than 90 days — runs weekly at 04:00 UTC Sunday
    # (~05:00-06:00 Albanian time). Without this, a busy tenant accumulates
    # 3M+ rows/year and query times degrade.
    'purge-old-analytics-events': {
        'task': 'analytics.tasks.purge_old_events',
        'schedule': crontab(hour=4, minute=0, day_of_week=0),
    },
}

# Email
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
# LOW-8 FIX: Wrap the EMAIL_PORT int cast in a try/except so a misconfigured
# env value (e.g. EMAIL_PORT=587/tcp from a Docker-style env) raises a clear
# ImproperlyConfigured message at startup instead of a raw ValueError traceback
# with no actionable guidance — consistent with every other startup guard in
# this settings module.
try:
    EMAIL_PORT = _env_int('EMAIL_PORT', 587)
except ValueError:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        f"EMAIL_PORT must be an integer (e.g. 587, 465, 25). "
        f"Got: {os.environ.get('EMAIL_PORT')!r}"
    )
# MEDIUM-1 FIX: read TLS/SSL mode from environment so operators using port 465
# (implicit TLS) can set EMAIL_USE_SSL=True, EMAIL_USE_TLS=False. Previously
# EMAIL_USE_TLS was hardcoded to True, making it impossible to configure
# port-465 SMTP without editing base.py directly. Django enforces mutual
# exclusion — both cannot be True simultaneously.
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() in ('true', '1', 'yes')
# LOW-4 FIX (v52): Fail fast at startup if both TLS and SSL are True.
# Django's SMTPEmailBackend raises ImproperlyConfigured on *first use* (not at
# startup), so containers start successfully and health checks pass — but the first
# real email send crashes. This guard moves the failure to startup so operators see
# a clear error immediately rather than mysterious task failures later.
# Port 587 -> EMAIL_USE_TLS=True, EMAIL_USE_SSL=False (default)
# Port 465 -> EMAIL_USE_TLS=False, EMAIL_USE_SSL=True
# Port 25  -> EMAIL_USE_TLS=False, EMAIL_USE_SSL=False
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        'EMAIL_USE_TLS and EMAIL_USE_SSL are mutually exclusive. '
        'Port 587 -> set EMAIL_USE_TLS=True (default); '
        'Port 465 -> set EMAIL_USE_SSL=True, EMAIL_USE_TLS=False; '
        'Port 25  -> set both to False.'
    )
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@bizal.al')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@bizal.al')

FRONTEND_BASE_URL = os.environ.get('FRONTEND_BASE_URL', 'http://localhost:8000')

# Base URL used to rewrite the marketing site's hardcoded "Demo Live"
# subdomain links (e.g. https://hertz-albania.bizal.al) into a locally
# reachable form. Empty by default (production keeps the real subdomain
# links); dev/local settings override this to http://localhost:8001, and
# main.html's JS appends ?tenant=<slug> per the query-param tenant
# resolution convention documented in README.md.
DEMO_BASE_URL = os.environ.get('DEMO_BASE_URL', '')


# ── Sentry error tracking ──────────────────────────────────────────────────────
# CRIT-1 FIX: Do NOT call sentry_sdk.init() here. Initialising Sentry in
# base.py causes a double-init in production because production.py imports
# base.py via `from .base import *`, runs base.py's init first, then calls
# its own init with different options (RedisIntegration, environment label,
# release). Calling sentry_sdk.init() twice replaces the first Hub, which
# can silently drop buffered events and registers DjangoIntegration twice.
# Sentry is initialised once, correctly, in production.py (and optionally
# in dev.py / staging.py for those environments).
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
# M-1 FIX: the previous pattern r'^https?://.*\.bizal\.al$' required a literal
# "." immediately before "bizal.al", so it matched subdomains (hertz.bizal.al)
# but never matched the bare apex domain (https://bizal.al) — there's no dot
# in that string positioned right before "bizal.al". Made the subdomain
# segment optional so both forms match.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^https?://([a-zA-Z0-9-]+\.)?bizal\.al$',
    r'^http://localhost:\d+$',
]
# H-1 FIX (v43): CORS_ALLOW_CREDENTIALS must be set in base.py so it is
# active in production (production.py imports base.py via `from .base import *`).
# It was previously only set in dev.py and local.py, meaning production never
# emitted `Access-Control-Allow-Credentials: true`. Without this header,
# browsers refuse to send `Authorization: Bearer …` on cross-origin requests —
# the tenant SPA (hertz.bizal.al) calling any API endpoint would silently fail
# with a CORS error on every authenticated call.
# Setting this in base.py is safe because production.py narrows
# CORS_ALLOWED_ORIGIN_REGEXES to `https://*.bizal.al` only, so credentials
# are never exposed to arbitrary third-party origins.
CORS_ALLOW_CREDENTIALS = True

RATELIMIT_USE_CACHE = 'default'

# FIX #10: Structured logging with tenant context.
# Every log line includes levelname, logger name, and message.
# In production, swap 'verbose' formatter for a JSON formatter
# (e.g. python-json-logger) so log aggregators can query by tenant_slug.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} — {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
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
        'level': os.environ.get('LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
        # App-level loggers — use getLogger(__name__) in each module
        'tenants': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'accounts': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'billing': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'analytics': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'notifications': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'celery': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}

# ── django-unfold (modern Django admin theme) ──────────────────────────────
# Reskins /django-admin/ only — tenant_admin.html (the per-tenant owner/
# manager panel at /admin/ on a tenant subdomain) is a separate hand-built
# page and is untouched by this. COLORS below mirror brand.css's parchment/
# ink neutrals and #F59E0B amber accent so the two admin surfaces feel like
# the same product instead of two unrelated tools.
UNFOLD = {
    'SITE_TITLE': 'BizAL Admin',
    'SITE_HEADER': 'BizAL',
    'SITE_SUBHEADER': 'Platform administration',
    'SITE_SYMBOL': 'storefront',
    'SHOW_HISTORY': True,
    'SHOW_VIEW_ON_SITE': True,
    'SHOW_BACK_BUTTON': True,
    # Powers the KPI + analytics dashboard on /django-admin/'s index page
    # (see bizal/dashboard.py + frontend/templates/admin/index.html).
    # /django-admin/ is the single platform-admin surface, restricted to
    # the main domain by TenantMiddleware.
    'DASHBOARD_CALLBACK': 'bizal.dashboard.dashboard_callback',
    'COLORS': {
        'base': {
            '50': '#fafaf9', '100': '#f5f5f4', '200': '#e7e5e4', '300': '#d6d3d1',
            '400': '#a8a29e', '500': '#78716c', '600': '#57534e', '700': '#44403c',
            '800': '#292524', '900': '#1c1917', '950': '#0c0a09',
        },
        'primary': {
            '50': '#fffbeb', '100': '#fef3c7', '200': '#fde68a', '300': '#fcd34d',
            '400': '#fbbf24', '500': '#f59e0b', '600': '#d97706', '700': '#b45309',
            '800': '#92400e', '900': '#78350f', '950': '#451a03',
        },
    },
    'COMMAND': {
        'search_models': True,
        'show_history': True,
    },
    'SIDEBAR': {
        'show_search': True,
        'command_search': True,
        # 'show_all_applications' keeps Unfold's default Django-app-grouped
        # list available from the command search, but the explicit
        # 'navigation' below is what actually renders in the sidebar —
        # models grouped by what an operator is doing (platform ops,
        # billing, bookings, catalog, content, CRM, activity) rather than
        # by which Django app they happen to live in. Two apps
        # (appointments, hotels) contribute models to more than one group
        # because their models serve different concerns.
        'show_all_applications': True,
        'navigation': [
            {
                'title': _t('Platform'),
                'separator': True,
                'collapsible': False,
                'items': [
                    {'title': _t('Tenants'), 'icon': 'store', 'link': reverse_lazy('admin:tenants_tenant_changelist')},
                    {'title': _t('Tenant locations'), 'icon': 'location_on', 'link': reverse_lazy('admin:tenants_tenantlocation_changelist')},
                    {'title': _t('Trial tenants'), 'icon': 'hourglass_top', 'link': reverse_lazy('admin:tenants_trialtenant_changelist')},
                    {'title': _t('Tenant referrals'), 'icon': 'share', 'link': reverse_lazy('admin:tenants_tenantreferral_changelist')},
                    {'title': _t('Users'), 'icon': 'group', 'link': reverse_lazy('admin:accounts_user_changelist')},
                    {'title': _t('Staff members'), 'icon': 'badge', 'link': reverse_lazy('admin:staff_staffmember_changelist')},
                ],
            },
            {
                'title': _t('Billing & payments'),
                'separator': True,
                'collapsible': True,
                'items': [
                    {'title': _t('Invoices'), 'icon': 'receipt_long', 'link': reverse_lazy('admin:billing_invoice_changelist')},
                    {'title': _t('Loyalty accounts'), 'icon': 'card_giftcard', 'link': reverse_lazy('admin:billing_loyaltyaccount_changelist')},
                    {'title': _t('Subscriptions'), 'icon': 'autorenew', 'link': reverse_lazy('admin:subscriptions_customersubscription_changelist')},
                    {'title': _t('Webhook events'), 'icon': 'webhook', 'link': reverse_lazy('admin:payments_webhookevent_changelist')},
                ],
            },
            {
                'title': _t('Bookings & orders'),
                'separator': True,
                'collapsible': True,
                'items': [
                    {'title': _t('Bookings'), 'icon': 'event_available', 'link': reverse_lazy('admin:bookings_booking_changelist')},
                    {'title': _t('Appointments'), 'icon': 'event', 'link': reverse_lazy('admin:appointments_appointment_changelist')},
                    {'title': _t('Service providers'), 'icon': 'engineering', 'link': reverse_lazy('admin:appointments_serviceprovider_changelist')},
                    {'title': _t('Services'), 'icon': 'design_services', 'link': reverse_lazy('admin:appointments_service_changelist')},
                    {'title': _t('Orders'), 'icon': 'shopping_cart', 'link': reverse_lazy('admin:orders_order_changelist')},
                ],
            },
            {
                'title': _t('Catalog & inventory'),
                'separator': True,
                'collapsible': True,
                'items': [
                    {'title': _t('Products'), 'icon': 'inventory_2', 'link': reverse_lazy('admin:inventory_product_changelist')},
                    {'title': _t('Product categories'), 'icon': 'category', 'link': reverse_lazy('admin:inventory_productcategory_changelist')},
                    {'title': _t('Menu items'), 'icon': 'restaurant_menu', 'link': reverse_lazy('admin:menu_menuitem_changelist')},
                    {'title': _t('Menu categories'), 'icon': 'list_alt', 'link': reverse_lazy('admin:menu_menucategory_changelist')},
                    {'title': _t('Room types'), 'icon': 'king_bed', 'link': reverse_lazy('admin:hotels_roomtype_changelist')},
                    {'title': _t('Rooms'), 'icon': 'hotel', 'link': reverse_lazy('admin:hotels_room_changelist')},
                    {'title': _t('Seasonal prices'), 'icon': 'calendar_month', 'link': reverse_lazy('admin:hotels_seasonalprice_changelist')},
                    {'title': _t('Rental items'), 'icon': 'directions_car', 'link': reverse_lazy('admin:rentals_rentalitem_changelist')},
                ],
            },
            {
                'title': _t('Content & marketing'),
                'separator': True,
                'collapsible': True,
                'items': [
                    {'title': _t('Storefront pages'), 'icon': 'web', 'link': reverse_lazy('admin:storefront_storefrontpage_changelist')},
                    {'title': _t('Hero slides'), 'icon': 'image', 'link': reverse_lazy('admin:storefront_heroslide_changelist')},
                    {'title': _t('Blog posts'), 'icon': 'article', 'link': reverse_lazy('admin:blog_blogpost_changelist')},
                    {'title': _t('Blog tags'), 'icon': 'sell', 'link': reverse_lazy('admin:blog_blogtag_changelist')},
                    {'title': _t('Reviews'), 'icon': 'star', 'link': reverse_lazy('admin:reviews_review_changelist')},
                    {'title': _t('Platform reviews'), 'icon': 'reviews', 'link': reverse_lazy('admin:reviews_platformreview_changelist')},
                ],
            },
            {
                'title': _t('CRM & support'),
                'separator': True,
                'collapsible': True,
                'items': [
                    {'title': _t('Leads'), 'icon': 'contacts', 'link': reverse_lazy('admin:crm_lead_changelist')},
                    {'title': _t('Contact messages'), 'icon': 'mail', 'link': reverse_lazy('admin:contact_contactmessage_changelist')},
                    {'title': _t('Notifications'), 'icon': 'notifications', 'link': reverse_lazy('admin:notifications_notification_changelist')},
                ],
            },
            {
                'title': _t('Activity & analytics'),
                'separator': True,
                'collapsible': True,
                'items': [
                    {'title': _t('Activity log'), 'icon': 'history', 'link': reverse_lazy('admin:activity_activitylog_changelist')},
                    {'title': _t('Analytics events'), 'icon': 'insights', 'link': reverse_lazy('admin:analytics_analyticsevent_changelist')},
                ],
            },
            {
                'title': _t('System'),
                'separator': True,
                'collapsible': True,
                'items': [
                    {'title': _t('Groups'), 'icon': 'shield', 'link': reverse_lazy('admin:auth_group_changelist')},
                ],
            },
        ],
    },
}