#!/bin/sh
# BizAL db-backup entrypoint
# LOW-3 FIX: Run an immediate backup on container start so a fresh deploy
# is never left without a backup until 03:00 the next day (up to 17h gap).
# After the initial run, exec crond as PID 1 to handle the daily schedule.
#
# NOTE on backgrounding + wait: The initial backup runs in the background
# (&) so that we can use the `wait $PID || BACKUP_EXIT=$?` pattern to
# capture a non-zero exit code without triggering `set -e`. Running
# synchronously under `set -e` would exit the entrypoint immediately on
# backup failure, before crond starts — leaving the container with no
# scheduled backups. The background+wait pattern lets us log the failure
# and still start crond for subsequent daily runs.
#
# Signal semantics note: this script (PID 1 in the container's PID
# namespace) is already immune to SIGTERM at the kernel level regardless
# of foreground/background child arrangement — PID 1 does not receive
# SIGTERM unless it explicitly installs a handler. crond only becomes PID 1
# after `exec crond` below, which runs after `wait` completes. The
# backgrounding does not change when crond becomes PID 1; it only changes
# how we handle the backup's exit code.
set -e

echo "[db-backup] Running initial backup in background..."
/usr/local/bin/backup.sh &
BACKUP_PID=$!

echo "[db-backup] Starting crond as PID 1 (initial backup running as PID $BACKUP_PID)..."
# Wait for the background backup to complete before handing over to crond.
# This ensures the initial backup finishes before crond takes over. If the
# backup fails (non-zero exit), we log the error but still start crond so
# the scheduled daily backups can continue.
# HIGH-1 FIX: Under set -e, `wait $BACKUP_PID` exits the shell immediately if
# the backup exits non-zero — before the `if [ $? -ne 0 ]` block is ever
# evaluated. Use `|| true` to capture the exit code without triggering set -e,
# then inspect it manually so the CRITICAL log and crond startup are guaranteed.
BACKUP_EXIT=0
wait $BACKUP_PID || BACKUP_EXIT=$?
if [ "$BACKUP_EXIT" -ne 0 ]; then
    echo "[db-backup] CRITICAL: Initial backup exited with non-zero status ($BACKUP_EXIT). Check backup.sh logs above." >&2
else
    echo "[db-backup] Initial backup completed successfully."
fi

echo "[db-backup] Initial backup done. Handing over to crond."
exec crond -f -d 8 -l 2
