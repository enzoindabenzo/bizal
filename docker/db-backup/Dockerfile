# BizAL — db-backup image.
#
# Based on postgres:16-alpine (matches the `db` service's major version —
# pg_dump should be the same major version as the server it's dumping)
# so pg_dump is already present. Alpine images already ship a working
# crond as part of busybox, so the only thing this image needs to add is
# the AWS CLI for the S3 upload step in backup.sh, plus tzdata for the
# timezone fix below.
FROM postgres:16-alpine

RUN apk add --no-cache aws-cli tzdata

# Django's TIME_ZONE is Europe/Tirane (see backend/bizal/settings/base.py)
# — match it here so "03:00" in the crontab below means the same
# wall-clock time admins would expect from the rest of the app, not a
# silent UTC offset.
#
# Symlinking /etc/localtime (rather than relying on the TZ env var alone)
# because busybox's crond reads system local time via /etc/localtime, not
# every tool consistently honors TZ — the symlink is the reliable fix for
# daemons specifically, vs. just date/log timestamps.
ENV TZ=Europe/Tirane
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# Daily at 03:00 (Europe/Tirane, see TZ above) inside the container. Logs
# go to stdout/stderr so they show up in `docker compose logs db-backup`
# like every other service.
RUN echo "0 3 * * * /usr/local/bin/backup.sh >> /proc/1/fd/1 2>> /proc/1/fd/2" > /etc/crontabs/root

# LOW-3 FIX: -d 8 sends crond's own startup/error messages to stderr so
# they appear in `docker compose logs db-backup`. Without it, crond logs to
# syslog only and startup errors are invisible via docker logs.
#
# LOW-3 FIX (extended): run an immediate backup on container start so a fresh
# deploy is not left without a backup until 03:00 the following day (up to 17h
# window on a midday deploy). The wrapper script runs backup.sh once, then
# execs crond so crond remains PID 1 (receives SIGTERM on `docker stop`).
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
