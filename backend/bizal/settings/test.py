from .base import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}

RATELIMIT_USE_CACHE = 'default'

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

CELERY_TASK_ALWAYS_EAGER = True
STRIPE_SECRET_KEY = 'sk_test_dummy'
STRIPE_WEBHOOK_SECRET = 'whsec_dummy'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}
