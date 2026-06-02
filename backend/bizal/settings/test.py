from .base import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache'
    }
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

CELERY_TASK_ALWAYS_EAGER = True
STRIPE_SECRET_KEY = 'sk_test_dummy'
STRIPE_WEBHOOK_SECRET = 'whsec_dummy'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}
