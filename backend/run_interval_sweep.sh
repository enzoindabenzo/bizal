#!/usr/bin/env bash
# Runs a fixed, evenly-spaced set of concurrency levels between 0 and 330
# users, 5 minutes each, and writes one clean summary line per level to
# results/interval_sweep/summary.csv. Meant for a chart/table in the thesis
# showing a smooth progression, not for finding a boundary (we already have
# that from the bisection: clean at 330, collapse at 340).
#
# Usage: ./run_interval_sweep.sh
# Run from the backend/ directory (same place you run locust from).

set -euo pipefail

LEVELS=(50 100 150 200 250 300 330 350 400)   # even steps, then past the ceiling to show the collapse curve
RUN_MINUTES=15
HOST="http://127.0.0.1:80"
RESULTS_DIR="results/interval_sweep"

mkdir -p "$RESULTS_DIR"
SUMMARY="$RESULTS_DIR/summary.csv"
echo "users,requests,failures,failure_pct,median_ms,p95_ms,max_ms,req_per_s" > "$SUMMARY"

for users in "${LEVELS[@]}"; do
    tag="u${users}_$(date -u +%H%M%S)"
    csv="$RESULTS_DIR/run_${tag}"

    echo "=== Testing ${users} users (${RUN_MINUTES}m) ==="

    python3 loadtest/warmup_login.py --host "$HOST"

    locust -f loadtest/locustfile.py --host="$HOST" \
        --headless -u "$users" -r 10 --run-time "${RUN_MINUTES}m" \
        --exclude-tags ip-rate-limited \
        --csv="$csv" > "${csv}_console.log" 2>&1

    # Aggregated row: Type,Name,# reqs,# fails,Median,Average,Min,Max,req/s,
    # failures/s,50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%
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
echo "Done. Summary table:"
column -s, -t "$SUMMARY"
echo "Full file: $SUMMARY"
echo "======================================"