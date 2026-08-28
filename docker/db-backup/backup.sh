#!/bin/sh
# BizAL — PostgreSQL backup script.
#
# Runs inside the `db-backup` service (see docker-compose.yml). Always writes
# a local copy to /backups (the postgres_backups volume) and, when
# BACKUP_S3_BUCKET is set, also uploads to S3 so backups survive the host
# dying — the whole point of this script existing. Local-only was the
# original gap: if the Docker host is lost, the postgres_backups volume is
# lost with it.
#
# Local copies are still kept even when S3 is configured. This is
# deliberate, not redundant: it gives you an instant restore path without
# network access or AWS credentials, while S3 (or NFS, see below) is the
# durable copy that survives the host. Local retention is short (default 7
# days) precisely because S3/NFS is the long-term store.
#
# NFS note: if you'd rather use NFS than S3, skip BACKUP_S3_BUCKET entirely
# and instead mount your NFS share over the postgres_backups volume in
# docker-compose.yml (a `driver: local` volume with NFS driver_opts, or an
# NFS-backed bind mount). This script doesn't need to know the difference —
# it only ever writes to /backups, and it's the volume definition that
# decides whether that path is local disk, NFS, or something else.

set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
FILENAME="bizal_${TIMESTAMP}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

log "Starting backup -> ${FILEPATH}"
mkdir -p "${BACKUP_DIR}"

# L-6 FIX: Abort immediately if DB_PASSWORD is unset or empty. Without this,
# pg_dump prompts for a password interactively, which hangs indefinitely inside
# a container (no tty on stdin). The hang is silent — cron fires again the next
# day and spawns another stuck process, while gzip has already opened the output
# file, so the backup volume fills with empty/partial gzip files.
if [ -z "${DB_PASSWORD:-}" ]; then
    log "ERROR: DB_PASSWORD is not set. Aborting backup to prevent silent hang."
    exit 1
fi

# L-2 FIX: previously this exported PGPASSWORD, which is visible in
# plaintext to any process on the host that can read
# /proc/<pid>/environ for this container's pg_dump process (e.g. another
# container sharing the host's PID namespace, or a host-level monitoring
# agent). Write a .pgpass file instead — pg_dump/libpq read the password
# from there with no equivalent inter-process exposure, since /proc only
# ever shows the *file path* convention (PGPASSFILE), never file contents.
# Written fresh on every run (idempotent — this script is invoked once at
# container start and once daily via cron) so a rotated DB_PASSWORD is
# always picked up without a stale file lingering.
# LOW-3 FIX (v36): Use a fixed /tmp path instead of ${HOME:-/root}. If the
# container runs as a non-root user (best practice) and HOME is unset or
# still /root, the write to /root/.pgpass fails silently — PGPASSFILE points
# to a non-existent file, pg_dump prompts for a password on stdin and hangs
# indefinitely. /tmp is always writable by any user in a container.
# The file is scoped to this PID so parallel backup runs don't clobber each other.
PGPASS_FILE="/tmp/.pgpass_$$"
# M-2 FIX: Register a trap to delete the PGPASS file on any exit (normal,
# error, or signal). Without this, every cron run leaves a /tmp/.pgpass_<PID>
# file containing the plaintext DB password, accumulating indefinitely.
trap 'rm -f "${PGPASS_FILE}"' EXIT INT TERM
echo "${DB_HOST}:${DB_PORT:-5432}:${DB_NAME}:${DB_USER}:${DB_PASSWORD}" > "${PGPASS_FILE}"
chmod 0600 "${PGPASS_FILE}"
export PGPASSFILE="${PGPASS_FILE}"

# --no-owner/--no-acl: restoring into a fresh DB shouldn't require the
# exact same role names to exist on the target server.
# MED-3 FIX: Retry pg_dump up to 3 times with a 30s gap.
# A transient DB restart at 03:00 previously caused a silent backup skip
# for the entire day (crond restarts the container, but the crontab only
# fires once at 03:00 — a fresh container after that time won't run again
# until the next day). Three attempts with 30s backoff gives the DB ~60s
# to recover before we give up.
# LOW-4 NOTE: `set -eu` is active above. The `if pg_dump ...; then` pattern
# is deliberate — POSIX sh does NOT trigger `set -e` exit for a non-zero
# exit code that is the condition of an `if` statement. This lets the retry
# loop continue on failure. Do NOT convert to bare `pg_dump | gzip > ...`
# without an explicit `|| true` or `set +e` guard, or `set -e` will kill
# the script on the first pg_dump failure before the retry fires.
DUMP_OK=0
for attempt in 1 2 3; do
    if pg_dump \
            --host="${DB_HOST}" \
            --port="${DB_PORT:-5432}" \
            --username="${DB_USER}" \
            --no-owner \
            --no-acl \
            --format=plain \
            "${DB_NAME}" | gzip > "${FILEPATH}"; then
        DUMP_OK=1
        break
    fi
    log "ERROR: pg_dump attempt ${attempt} failed"
    rm -f "${FILEPATH}"
    if [ "${attempt}" -lt 3 ]; then
        log "Retrying in 30s..."
        sleep 30
    fi
done
if [ "${DUMP_OK}" -eq 0 ]; then
    log "ERROR: All pg_dump attempts failed, no backup written"
    exit 1
fi

DUMP_SIZE="$(du -h "${FILEPATH}" | cut -f1)"
log "Backup complete: ${FILENAME} (${DUMP_SIZE})"

# LOW-6 FIX: Verify backup file is non-empty before uploading
if [ ! -s "${FILEPATH}" ]; then
    log "ERROR: Backup file is empty — aborting upload to avoid overwriting a good backup."
    exit 1
fi

# ── Off-host copy (S3) ───────────────────────────────────────────────────────
# This is the actual fix: without this block, the dump above only ever lives
# on the local postgres_backups volume, which dies with the host.
if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
    S3_PATH="s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX:-bizal-backups}/${FILENAME}"
    log "Uploading to ${S3_PATH}"
    if aws s3 cp "${FILEPATH}" "${S3_PATH}" \
            ${BACKUP_S3_ENDPOINT_URL:+--endpoint-url "${BACKUP_S3_ENDPOINT_URL}"} \
            --only-show-errors; then
        log "Upload succeeded"
    else
        # Non-fatal: the local copy still exists and cron will retry
        # tomorrow. A failed upload should not look like a failed backup —
        # the dump itself succeeded — but it must be loud, since a silent
        # failure here is exactly how someone discovers during an outage
        # that the last 30 days of "backups" never left the dead host.
        log "ERROR: S3 upload failed — local copy retained at ${FILEPATH}"
    fi
else
    log "BACKUP_S3_BUCKET not set — skipping off-host upload (local-only, dev mode)"
fi

# ── Local retention ──────────────────────────────────────────────────────────
log "Pruning local backups older than ${RETENTION_DAYS} days"
find "${BACKUP_DIR}" -name 'bizal_*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete | while read -r old; do
    log "Removed old local backup: ${old}"
done

log "Done"
