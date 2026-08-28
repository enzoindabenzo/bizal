"""
BizAL ASGI config.

Exposes the ASGI callable as ``application``.
Currently uses Django's standard ASGI adapter (HTTP only).
When real-time features (WebSocket notifications, live analytics) are
added, replace this with a Channels ``ProtocolTypeRouter``.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bizal.settings.production')

application = get_asgi_application()
