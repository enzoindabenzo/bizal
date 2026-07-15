import os
from django.core.wsgi import get_wsgi_application

# HIGH-2 FIX: Fall back to production settings, not base.py. base.py is not a
# standalone runnable module — it lacks ADMINS, hardened LOGGING, and the
# SECRET_KEY / DEBUG startup guards that only exist in production.py. Any
# production container that starts without DJANGO_SETTINGS_MODULE set in its
# environment should fail loudly (production.py's startup guards will reject
# a missing SECRET_KEY) rather than silently serve traffic with no security
# hardening. For local dev, set DJANGO_SETTINGS_MODULE=bizal.settings.local
# explicitly via activate.ps1 or your IDE run config — don't rely on this default.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bizal.settings.production')
application = get_wsgi_application()
