"""
Gap-coverage test for bizal.ratelimit_utils.ratelimit_decorator's inner
_key_func, which is only exercised when RATELIMIT_ENABLE=True and a request
is actually run through the real django-ratelimit decorator (the existing
test in tenants/tests.py only checks that the real decorator is returned,
not that a request flows through it end-to-end).
"""
from django.test import TestCase, RequestFactory, override_settings


class RatelimitKeyFuncGapsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_key_func_uses_x_real_ip_header_when_present(self):
        from bizal.ratelimit_utils import ratelimit_decorator

        with override_settings(RATELIMIT_ENABLE=True):
            decorator = ratelimit_decorator('100/m', method='GET')

            def dummy(request):
                return 'ok'

            wrapped = decorator(dummy)
            request = self.factory.get('/', HTTP_X_REAL_IP='203.0.113.5')
            result = wrapped(request)
            self.assertEqual(result, 'ok')

    def test_key_func_falls_back_to_remote_addr_when_header_absent(self):
        from bizal.ratelimit_utils import ratelimit_decorator

        with override_settings(RATELIMIT_ENABLE=True):
            decorator = ratelimit_decorator('100/m', method='GET')

            def dummy(request):
                return 'ok'

            wrapped = decorator(dummy)
            request = self.factory.get('/', REMOTE_ADDR='198.51.100.7')
            result = wrapped(request)
            self.assertEqual(result, 'ok')
