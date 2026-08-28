# BizAL — production image.
#
# Build context is the REPO ROOT (see docker-compose.prod.yml's
# `context: .` and railway.toml's dockerfilePath = "Dockerfile") — all
# COPY paths below are relative to the repo root, not backend/.
#
# Used by:
#   - docker-compose.prod.yml (web/spa services), which overrides
#     `entrypoint: ["/entrypoint.sh"]` explicitly for web and disables it
#     for spa — either way it expects /entrypoint.sh to exist in the image.
#   - Railway (railway.toml), which does NOT override the entrypoint for the
#     `web` service, so this file's own ENTRYPOINT is what actually runs.
#     Set a custom Start Command in the Railway dashboard for the
#     celery-worker / celery-beat services instead — see railway.toml.
#
# BUG FIX (this session): this file had been overwritten with a copy of
# backend/Dockerfile.dev. That version installed requirements-dev.txt
# (baking pytest/coverage/locust into the production image), assumed a
# `context: ./backend` build context that doesn't match what compose/
# Railway actually use here, and had no COPY of entrypoint.sh, no
# ENTRYPOINT, and no CMD — a container built from it would start, run
# nothing, and exit immediately. On Railway that means: build succeeds,
# deploy "succeeds", the healthcheck never passes, and it crash-loops
# forever with no error in the logs to point at.

FROM python:3.12-slim

WORKDIR /app

# Match Django's TIME_ZONE (Europe/Tirane) at the OS level too, so cron,
# shell scripts, and log timestamps agree with what Python/glibc report.
ENV TZ=Europe/Tirane

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Production image installs ONLY backend/requirements.txt — never
# requirements-dev.txt (pytest/coverage/locust have no business in the
# deployed image).
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as a non-root user rather than root inside the container.
#
# /app/media is excluded by .dockerignore and gets mounted as a volume
# (docker-compose.prod.yml's media_data volume, or a Railway Volume per
# .env.railway.example) — MEDIA_ROOT uses local FileSystemStorage by
# default (settings/base.py), so it's actively written to at runtime.
# Pre-creating it here, owned by appuser, before the volume is ever
# mounted means Docker/Railway inherit that ownership onto the volume's
# root instead of defaulting to root:root, which would make every upload
# fail with a permission error under the non-root user below.
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/media /app/staticfiles \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]