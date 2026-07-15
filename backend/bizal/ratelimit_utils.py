from django.conf import settings as django_settings


def ratelimit_decorator(rate, method='POST'):
    """
    Returns a real django-ratelimit decorator in production
    (RATELIMIT_ENABLE=True), or a no-op passthrough in local dev where
    there's no shared cache backend for it to use.

    Usage:
        @method_decorator(ratelimit_decorator('5/m'))
        def post(self, request):
            ...
    """
    if getattr(django_settings, 'RATELIMIT_ENABLE', True):
        from django_ratelimit.decorators import ratelimit

        def _key_func(group, request):
            # LOW-1 FIX: Fall back to REMOTE_ADDR when X-Real-IP is absent
            # (e.g. direct connections in dev/staging without nginx in front).
            # The old 'header:x-real-ip' key collapsed to '' when the header
            # was missing, causing all headerless requests to share one bucket
            # and triggering false-positive rate-limit blocks under load.
            ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')
            return ip

        return ratelimit(key=_key_func, rate=rate, method=method, block=True)
    return lambda f: f
