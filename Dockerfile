FROM python:3.12-slim

WORKDIR /app

# L-4 FIX: Set timezone so datetime.date.today() and Django's timezone.localdate()
# return Albanian time in development, matching the production image. Without this,
# running the dev image directly with `docker run` (outside docker-compose, which
# injects TZ=Europe/Tirane) would silently use UTC, causing date-logic bugs in
# appointment overlap checks and send_appointment_reminders for times 00:00–02:00.
ENV TZ=Europe/Tirane

# LOW-3 FIX: create the /etc/localtime symlink and write /etc/timezone to
# mirror what the production Dockerfile does. Without this, system-level
# tools (cron, shell scripts, `date` command, postgres log timestamps) use
# UTC inside the dev container while TZ=Europe/Tirane is only respected by
# Python/glibc — creating a confusing discrepancy that can mask
# timezone-related bugs that only surface after deployment.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*
# AUDIT FIX: requirements-dev.txt's first line is `-r requirements.txt`, so pip
# needs requirements.txt present in the build context when this RUN executes.
# Only requirements-dev.txt was being COPYed here — pip install then failed with
# "Could not open requirements file: ... requirements.txt" on every single dev
# build (web, spa, celery, celery-beat all share this Dockerfile), making
# `docker compose build` unusable out of the box. COPY both files, in the same
# dependency order Dockerfile (prod) uses, before installing.
COPY requirements.txt .
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000 8001
