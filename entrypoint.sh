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
    # RAILWAY FIX: Railway (and most PaaS hosts) assign the listen port
    # dynamically via $PORT and route external traffic to whatever port the
    # process actually binds — a hardcoded 8000 means Railway's edge can
    # never reach the container. Falling back to 8000 when $PORT is unset
    # keeps docker-compose/local `docker run` behavior unchanged.
    # CAPACITY FIX: bumped from 4 workers x 2 threads (8 slots) to 8 workers x
    # 4 threads (32 slots) after load testing showed the 8-slot config
    # saturating around ~90 req/s / ~500 concurrent users, then producing a
    # clustered wave of 504s at 1000 concurrent users once queued requests'
    # wait times crossed the 60s timeout. Workload is I/O-bound (waiting on
    # Postgres), so threads scale cheaply relative to full worker processes;
    # gunicorn auto-upgrades sync workers to gthread whenever --threads > 1.
    # Re-check this against the actual Railway service's allocated vCPU/RAM
    # (Railway dashboard -> service -> Metrics) before trusting it blindly —
    # 8 workers is only a good number if there are cores to back it.
    # CONFIG-DRIFT NOTE: this comment previously documented 8x4=32 slots as
    # tested-safe, but the flags below had drifted to 12x2=24 slots. A
    # 200-user local Docker Desktop load test briefly tried "restoring" to
    # 8x4, which made things WORSE (higher latency across every endpoint,
    # including a trivial health check) — Docker Desktop's local VM has far
    # fewer cores than Railway's actual production hosts, so more
    # workers/threads than the local VM has cores just adds context-switch
    # overhead. Reverted back to 12x2, which measured cleanly (0.057% error
    # rate) on this hardware. The 8x4 config may still be correct for the
    # real Railway deployment (more cores available there) — don't copy this
    # 12x2 number back to production without checking Railway's actual
    # vCPU allocation first; local Docker Desktop numbers aren't
    # representative of it.
    # LOGGING FIX: previously no --access-logfile/--error-logfile/--log-level
    # was set, so gunicorn wrote almost nothing to stdout — a worker getting
    # SIGKILL'd (OOM) could pass silently, and there was no per-request
    # access log to correlate failures with timing. `-` for both log files
    # means "write to stdout/stderr", which is what `docker compose logs`
    # already captures. --capture-output redirects any raw print()/stdout
    # output from application code into gunicorn's error log instead of
    # being lost. Access log format adds %(D)s (request duration in
    # microseconds) so slow/failed requests are visible with timing, not
    # just a bare hit count.
    # PRELOAD FIX (see load-test findings): without --preload, every worker
    # respawn (timeout, OOM, rolling restart) re-imports the full app —
    # including the xhtml2pdf/pyhanko/cryptography import chain in
    # billing/views.py — while holding the GIL, stalling the whole process.
    # --preload imports once in the master before fork; workers inherit via
    # copy-on-write, so a respawn is cheap instead of a multi-second freeze.
    # WORKER COUNT FIX: hardcoding 12 drifted out of sync with actual
    # deployment hardware more than once (see history above). Compute from
    # real CPU count instead: 2×cores+1 is the standard gunicorn rule of
    # thumb for a mixed I/O+CPU workload. Override with GUNICORN_WORKERS if
    # you've measured a better number for your actual Railway plan.
    WORKERS=${GUNICORN_WORKERS:-$(( $(nproc) * 2 + 1 ))}
    # 2026-09-14 CAPACITY FIX: the 300-user test's slow-query log showed even
    # trivial Postgres queries (PK lookups, "SELECT 1") taking 700-2800ms —
    # the signature of CPU starvation from oversubscription, not a query
    # problem. GUNICORN_WORKERS had drifted to 6 in .env and this file's own
    # --threads was hardcoded to 8 regardless of env, giving 6x8=48 web slots
    # alone (before counting spa's 24x4=96) on hardware this repo's own prior
    # notes describe as "far fewer cores than Railway's production hosts."
    # --threads is now overridable via GUNICORN_WEB_THREADS so the whole
    # worker x thread shape can be tuned from .env without editing this file.
    # Re-derive both numbers from the real host's core count
    # (docker compose exec web nproc) rather than trusting any number carried
    # over from a previous session — that's the mistake that produced this
    # drift in the first place.
    THREADS=${GUNICORN_WEB_THREADS:-4}
    exec gunicorn bizal.wsgi:application --preload --bind 0.0.0.0:${PORT:-8000} --workers "$WORKERS" --threads "$THREADS" --timeout 120 --keep-alive 75 \
      --access-logfile - --error-logfile - --capture-output --log-level info \
      --access-logformat '%(t)s %(h)s "%(r)s" %(s)s %(b)s %(D)sus'
fi
exec "$@"