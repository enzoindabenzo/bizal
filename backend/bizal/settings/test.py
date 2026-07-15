from .base import *

import os

# CI provisions a real PostgreSQL service and sets DB_HOST/DB_NAME/etc. in
# the environment so the test suite exercises Postgres-only behaviour
# (select_for_update() actually locking, NULLS LAST ordering, JSONField
# query semantics, CheckConstraint enforcement). Local `manage.py test`
# runs with no DB_* env vars set and falls back to in-memory SQLite, which
# needs no local Postgres install. See test.py's select_for_update() note
# below for why this distinction matters.
if os.environ.get('DB_HOST'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'bizal_test'),
            'USER': os.environ.get('DB_USER', 'bizal'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            # LOW-3 FIX: Explicitly set connection management settings so CI
            # tests run with CONN_HEALTH_CHECKS=True. Without this, a flaky DB
            # connection in CI surfaces as a generic OperationalError rather than
            # a healed connection. CONN_MAX_AGE=0 disables pooling (tests do not
            # benefit from persistent connections and it can cause transaction
            # isolation issues between test cases).
            'CONN_MAX_AGE': 0,
            'CONN_HEALTH_CHECKS': True,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }

# tenants.middleware.TenantMiddleware caches resolved Tenant objects by slug
# for 5 minutes. Django's TestCase rolls back the DB between tests but does
# NOT clear the process-wide cache, so a tenant created with a reused slug
# (e.g. 'hertz', 'test', 'testbiz') in one test class can come back from
# _get_tenant() as a *different test's* stale Tenant instance (same slug,
# different pk) — request.tenant then points at a row that doesn't exist in
# the current test's transaction, breaking every queryset filtered by
# request.tenant. DummyCache makes every get() a miss, forcing a fresh DB
# lookup every time, which is exactly what we want for tests.
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

CELERY_TASK_ALWAYS_EAGER = True
# MEDIUM-1 FIX: Without this, exceptions raised inside a Celery task body
# are swallowed when CELERY_TASK_ALWAYS_EAGER=True — the task returns SUCCESS
# and stores the exception in its result attribute. Tests that call .delay()
# and then assert side effects (DB rows, emails sent) can pass even if the
# task raised an exception. local.py already sets this correctly.
CELERY_TASK_EAGER_PROPAGATES = True
STRIPE_SECRET_KEY = 'sk_test_dummy'
STRIPE_WEBHOOK_SECRET = 'whsec_dummy'
STRIPE_PRICE_STARTER = 'price_test_starter'
STRIPE_PRICE_PRO = 'price_test_pro'
STRIPE_PRICE_ENTERPRISE = 'price_test_enterprise'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# base.py now uses the modern STORAGES dict (LOW-2 FIX). test.py overrides
# both backends to use non-manifest variants appropriate for tests.
# H-1 FIX: 'django.core.files.storage.InMemoryStorage' does not exist in
# Django (core ships only Storage/FileSystemStorage) — referencing it here
# raised ImportError the moment anything resolved default_storage (saving,
# validating, or deleting any model with an ImageField/FileField — accounts,
# tenants, appointments, hotels, rentals, blog, menu, inventory, storefront
# all have one). Use FileSystemStorage pointed at a throwaway tmp directory
# instead: writes go to disk for the duration of the test run and are not
# committed anywhere meaningful, which is the right tradeoff for tests that
# never assert on storage internals.
import tempfile as _tempfile
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
        'OPTIONS': {'location': _tempfile.mkdtemp(prefix='bizal-test-media-')},
    },
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# django_ratelimit's system checks (E003/W001) require a "shared" cache
# backend (e.g. memcached/redis) and complain about LocMemCache. That's the
# correct warning for production, but for tests LocMemCache-per-process is
# fine and rate limiting itself is irrelevant — silence the checks rather
# than spinning up Redis just to run the test suite.
RATELIMIT_ENABLE = False
SILENCED_SYSTEM_CHECKS = ['django_ratelimit.E003', 'django_ratelimit.W001']
# select_for_update() is a no-op on SQLite (it acquires no lock and raises
# TransactionManagementError if called outside a transaction in some Django
# versions). Locally (no DB_HOST set, SQLite in-memory), tests that exercise
# the staff-invite race-condition guard rely on TestCase.assertRaises or
# simply verify the count-check logic is called correctly; they do NOT rely
# on the lock actually preventing concurrent writes. In CI, DB_HOST is set
# and the DATABASES block above switches to the real PostgreSQL service, so
# the same tests there do exercise the actual row lock end-to-end.
