#!/bin/sh
set -e

# L-4 FIX: migrate runs before collectstatic. The previous order (collectstatic
# first) is safe today because no AppConfig.ready() performs DB queries, but it's
# a latent footgun: if any app ever adds a DB query in ready(), collectstatic on
# a fresh deploy (no schema yet) would raise ProgrammingError. Running migrate
# first eliminates this ordering risk entirely. collectstatic is still idempotent
# and safe to run before gunicorn starts traffic.
if [ "${MIGRATE_ON_STARTUP:-true}" = "true" ]; then
    python manage.py migrate --noinput
    # M-1 FIX: Sync CELERY_BEAT_SCHEDULE → django_celery_beat DB tables.
    # DatabaseScheduler silently ignores changes to CELERY_BEAT_SCHEDULE after the
    # first deploy unless the DB rows are explicitly synced. The command's own
    # docstring says "Add to entrypoint.sh" — it was missing. Without this, any
    # new or changed beat tasks (e.g. purge_old_events) never fire in production.
    # Must run after migrate so the django_celery_beat tables exist.
    # MEDIUM-1 FIX: Demote failure to a warning so gunicorn always starts.
    # sync_celery_schedule is idempotent; a transient DB blip at deploy time
    # (common under rolling deploys) would otherwise kill the web container under
    # set -e, deadlocking every service that depends_on web: service_healthy.
    python manage.py sync_celery_schedule || echo "WARNING: sync_celery_schedule failed — beat schedule may be stale. Check logs." >&2
fi

# collectstatic runs after migrate: static files must be ready before gunicorn
# accepts traffic. It is idempotent and safe to run concurrently across
# rolling-deploy containers.
# LOW-5 FIX (v52): Mirror the spa service's collectstatic failure tolerance.
# Under set -e, a collectstatic failure (missing STATICFILES_DIRS entry, volume
# permissions error, transient DB blip) immediately kills the web container.
# spa, celery, and celery-beat all depend_on web: service_healthy, so they stall
# indefinitely with no obvious error. Demoting the failure to a warning keeps
# gunicorn starting while surfacing the problem in the container log.
# MEDIUM-1 FIX (v53): The previous pattern used a plain semicolon after
# collectstatic, so set -e exited the shell before STATIC_EXIT=$? was ever
# reached. The || operator bypasses set -e on the left-hand side and only
# evaluates the right-hand side when collectstatic exits non-zero, making the
# exit-code capture structurally correct under set -e.
# LOW-5 FIX: Unconditionally reset STATIC_EXIT to 0 before the || assignment.
# If STATIC_EXIT were already set in the container environment (e.g. via a
# Compose `environment:` block typo) and collectstatic succeeds (exit 0),
# `STATIC_EXIT=${STATIC_EXIT:-0}` would resolve to the pre-existing value
# rather than 0, falsely triggering the WARNING on every startup. Setting it
# to 0 first makes the pattern immune to any inherited environment value.
STATIC_EXIT=0
python manage.py collectstatic --noinput || STATIC_EXIT=$?
if [ "$STATIC_EXIT" -ne 0 ]; then
    echo "WARNING: collectstatic exited with code $STATIC_EXIT -- static files may be stale. Continuing startup." >&2
fi

# v65 FIX (LOW-1): Guard against empty $@. If entrypoint.sh is invoked with no
# CMD (e.g. `docker run bizal` with no arguments), `exec "$@"` is a shell no-op
# that exits 0 — the container appears to start, may briefly pass health checks,
# and then exits silently. Defaulting to gunicorn makes the failure visible and
# keeps the container running in the expected state.
if [ $# -eq 0 ]; then
    echo "entrypoint.sh: no command specified — defaulting to gunicorn" >&2
    exec gunicorn bizal.wsgi:application --bind 0.0.0.0:8000 --workers 4 --threads 2 --timeout 120
fi
exec "$@"
