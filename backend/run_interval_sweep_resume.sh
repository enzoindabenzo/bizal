#!/usr/bin/env bash
# Resumes the interval sweep from 150 users onward (50 and 100 already
# completed and are preserved in results/interval_sweep/summary.csv).
# Appends new rows instead of overwriting the file.
#
# Usage: ./run_interval_sweep_resume.sh
# Run from the backend/ directory, after `wsl --shutdown` + bringing
# docker compose back up to clear accumulated memory.

set -euo pipefail

LEVELS=(330 350 400)
RUN_MINUTES=15
HOST="http://127.0.0.1:80"
RESULTS_DIR="results/interval_sweep"
SUMMARY="$RESULTS_DIR/summary.csv"

mkdir -p "$RESULTS_DIR"
# Don't overwrite -- 50 and 100 are already in there. Add the header only
# if the file doesn't exist yet (e.g. run standalone on a fresh machine).
if [ ! -f "$SUMMARY" ]; then
    echo "users,requests,failures,failure_pct,median_ms,p95_ms,max_ms,req_per_s" > "$SUMMARY"
fi

for users in "${LEVELS[@]}"; do
    tag="u${users}_$(date -u +%H%M%S)"
    csv="$RESULTS_DIR/run_${tag}"

    echo "=== Testing ${users} users (${RUN_MINUTES}m) ==="

    python3 loadtest/warmup_login.py --host "$HOST"

    locust -f loadtest/locustfile.py --host="$HOST" \
        --headless -u "$users" -r 10 --run-time "${RUN_MINUTES}m" \
        --exclude-tags ip-rate-limited \
        --csv="$csv" > "${csv}_console.log" 2>&1

    agg=$(grep ',Aggregated,' "${csv}_stats.csv" | tail -1)
    reqs=$(echo "$agg" | awk -F',' '{print $3}')
    fails=$(echo "$agg" | awk -F',' '{print $4}')
    median=$(echo "$agg" | awk -F',' '{print $5}')
    reqps=$(echo "$agg" | awk -F',' '{print $9}')
    p95=$(echo "$agg" | awk -F',' '{print $16}')
    maxms=$(echo "$agg" | awk -F',' '{print $8}')

    pct=$(awk -v f="$fails" -v r="$reqs" 'BEGIN{ if (r==0) print 100; else printf "%.4f", (f/r)*100 }')

    echo "${users},${reqs},${fails},${pct},${median},${p95},${maxms},${reqps}" >> "$SUMMARY"
    echo "-> ${users} users: ${fails}/${reqs} failed (${pct}%), median ${median}ms, p95 ${p95}ms"
    echo
done

echo "======================================"
echo "Done. Full summary so far:"
column -s, -t "$SUMMARY"
echo "======================================"