import os
from celery import Celery
# MED-4 FIX: removed unused `from celery.schedules import crontab` (dead import; crontab
# is imported in settings/base.py where it is actually used for CELERY_BEAT_SCHEDULE)
from celery.signals import worker_process_init

# Respect whatever DJANGO_SETTINGS_MODULE is already set in the environment.
# In production (Docker) this comes from docker-compose env:.
# In local dev it's set by activate.ps1 / dev.py.
# Only fall back to base if nothing is set at all.
# HIGH-2 FIX: Fall back to production settings, not local.py. local.py has
# DEBUG=True, ALLOWED_HOSTS=['*'], and CELERY_TASK_ALWAYS_EAGER=True — running
# a Celery worker with those settings in production would execute tasks inline
# (defeating concurrency) and expose the app to host-header injection.
# Production containers must set DJANGO_SETTINGS_MODULE explicitly (via
# docker-compose env: or .env). This default is a last-resort safety net that
# ensures a misconfigured deploy fails loudly (production.py's startup guards
# will reject missing SECRET_KEY) rather than running with dev settings.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bizal.settings.production')

app = Celery('bizal')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@worker_process_init.connect
def _close_stale_db_connections_on_fork(**kwargs):
    """
    Defense-in-depth for the Celery-forked-connection problem (see the long
    comment in settings/dev.py and settings/production.py for the full
    mechanism). Setting CELERY_WORKER_RUNNING=true in the worker's
    environment, which forces CONN_MAX_AGE=0 for that process, is the
    primary fix and should be the actual line of defense in normal
    operation.

    This signal handler is the backstop for the case where that env var is
    missing — a misconfigured deploy, someone running `celery -A bizal
    worker` directly without going through docker-compose, etc. It fires
    once per forked child process, immediately after the fork, before that
    child picks up any tasks.

    Deliberately calls connection.close() on every connection rather than
    close_old_connections() (which only closes connections it considers
    unusable or past CONN_MAX_AGE). A connection inherited at fork time is
    neither — it's a perfectly healthy, recently-opened socket from the
    parent's point of view — which is exactly the problem: it's healthy
    *and shared*, and close_old_connections() would leave it open and
    shared in that case. Closing unconditionally forces each forked child
    to open its own fresh connection on first use, with no exceptions.
    """
    from django.db import connections
    for conn in connections.all():
        conn.close()
