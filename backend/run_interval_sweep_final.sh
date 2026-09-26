#!/usr/bin/env bash
set -euo pipefail

LEVELS=(330 350 400)
RUN_MINUTES=15
HOST="http://127.0.0.1:80"
RESULTS_DIR="results/interval_sweep"
SUMMARY="$RESULTS_DIR/summary.csv"

mkdir -p "$RESULTS_DIR"
if [ ! -f "$SUMMARY" ]; then
    echo "users,requests,failures,failure_pct,median_ms,p95_ms,max_ms,req_per_s" > "$SUMMARY"
fi

wait_for_health() {
    echo "Waiting for $HOST/health/ to respond..."
    for i in $(seq 1 24); do
        if curl -sf -o /dev/null "$HOST/health/"; then
            echo "Healthy after $((i*5))s"
            return 0
        fi
        sleep 5
    done
    echo "WARNING: still not healthy after 120s, proceeding anyway"
}

for users in "${LEVELS[@]}"; do
    tag="u${users}_$(date -u +%H%M%S)"
    csv="$RESULTS_DIR/run_${tag}"

    echo "=== Restarting spa/db to clear accumulated memory before ${users}u ==="
    docker compose -f ../docker-compose.prod.yml restart spa db
    wait_for_health

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

echo "Done. Full summary so far:"
column -s, -t "$SUMMARY"
