from unittest import mock
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status
from tenants.models import Tenant
from .models import HeroSlide
from bizal.throttles import PublicReadThrottle


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class ThrottleActuallyWorksTest(TestCase):
    """
    Sanity check: does PublicReadThrottle (used on the public storefront
    hero/pages endpoints) actually enforce a rate limit?

    TWO test-infrastructure traps had to be worked around to test this at
    all, on top of the actual application bug:

    1. `@override_settings(REST_FRAMEWORK={'DEFAULT_THROTTLE_RATES': ...})`
       does NOT work for SimpleRateThrottle-based classes:
       `SimpleRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES`
       is evaluated ONCE at import time and cached as a plain dict class
       attribute. override_settings does update the live `api_settings`
       object (confirmed directly via a one-off script), but never touches
       that already-materialized dict — the throttle keeps reading the real
       project rate. Fixed by patching `PublicReadThrottle.THROTTLE_RATES`
       directly instead, which the throttle actually reads from.

    2. `bizal.settings.test.CACHES` uses Django's DummyCache, which never
       stores anything (`.get()` always misses, `.set()` is a no-op) — a
       sensible default for most tests, but it means a throttle's request
       history can never accumulate, so it can NEVER fire regardless of
       whether the scope-lookup bug is fixed. Fixed by overriding CACHES to
       a real LocMemCache for this test class specifically.

    Both traps made an earlier version of this test meaningless in either
    direction — it couldn't have distinguished a working throttle from a
    broken one either way.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Throttle Biz', slug='throttlebiz', business_type='restaurant',
            plan='pro', is_active=True,
        )
        self.client.defaults['HTTP_HOST'] = 'throttlebiz.bizal.al'
        HeroSlide.objects.create(
            tenant=self.tenant, title='X', is_active=True, order=0,
        )

    def test_throttle_actually_fires_past_the_configured_rate(self):
        with mock.patch.object(PublicReadThrottle, 'THROTTLE_RATES', {'public_read': '3/min'}):
            statuses = []
            for i in range(6):
                resp = self.client.get('/api/storefront/hero/')
                statuses.append(resp.status_code)
        print(f"\n[THROTTLE CHECK] statuses for 6 requests against public_read=3/min: {statuses}")
        self.assertEqual(statuses[:3], [200, 200, 200], "first 3 requests (within the limit) should succeed")
        self.assertTrue(
            all(s == status.HTTP_429_TOO_MANY_REQUESTS for s in statuses[3:]),
            f"requests 4-6 (past the 3/min limit) should be throttled with 429, got {statuses[3:]}",
        )
