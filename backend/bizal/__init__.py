try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except ImportError:  # pragma: no cover - Celery is always installed in this environment
    pass  # Celery not needed for runserver — only for background workers
