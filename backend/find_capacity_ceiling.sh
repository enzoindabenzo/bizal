#!/usr/bin/env bash
# Finds the practical concurrency ceiling for BizAL's spa service by
# bisecting between a known-clean user count (LOW) and a known-failing
# one (HIGH). Each candidate gets a short 5-minute run; if its failure
# rate is at/under THRESHOLD it's treated as "clean" and becomes the new
# LOW, otherwise it becomes the new HIGH. Stops once the gap between
# LOW and HIGH is small enough (STEP) to call it a result.
#
# Usage: ./find_capacity_ceiling.sh
# Run from the backend/ directory (same place you run locust from).

set -euo pipefail

LOW=200          # known clean from earlier runs
HIGH=500         # known failing from earlier runs
STEP=25          # stop once LOW/HIGH are within this many users of each other
THRESHOLD=0.1    # max acceptable failure rate, in percent, to call a run "clean"
RUN_MINUTES=5    # shorter run per candidate -- enough to see the pattern (per earlier runs)
HOST="http://127.0.0.1:80"
RESULTS_DIR="results/ceiling_search"

mkdir -p "$RESULTS_DIR"
SUMMARY="$RESULTS_DIR/summary.txt"
: > "$SUMMARY"

run_one() {
    local users=$1
    local tag="u${users}_$(date -u +%H%M%S)"
    local csv="$RESULTS_DIR/run_${tag}"

    echo "=== Testing ${users} users (${RUN_MINUTES}m) ==="

    python3 loadtest/warmup_login.py --host "$HOST"

    locust -f loadtest/locustfile.py --host="$HOST" \
        --headless -u "$users" -r 10 --run-time "${RUN_MINUTES}m" \
        --exclude-tags ip-rate-limited \
        --csv="$csv" > "${csv}_console.log" 2>&1

    # Pull the Aggregated row from the stats csv: fields are
    # Type,Name,# reqs,# fails,... (see locust's own header)
    local agg
    agg=$(grep ',Aggregated,' "${csv}_stats.csv" | tail -1)
    local reqs fails
    reqs=$(echo "$agg" | awk -F',' '{print $3}')
    fails=$(echo "$agg" | awk -F',' '{print $4}')

    local pct
    if [ "$reqs" -eq 0 ]; then
        pct=100
    else
        pct=$(awk -v f="$fails" -v r="$reqs" 'BEGIN{printf "%.3f", (f/r)*100}')
    fi

    echo "${users} users -> ${fails}/${reqs} failed (${pct}%)" | tee -a "$SUMMARY"
    echo "$pct"
}

echo "Bisecting between LOW=$LOW (assumed clean) and HIGH=$HIGH (assumed failing)"
echo "Stopping when the gap is <= $STEP users, or a run is within ${THRESHOLD}% failures"
echo

while [ $((HIGH - LOW)) -gt "$STEP" ]; do
    MID=$(( (LOW + HIGH) / 2 ))
    pct=$(run_one "$MID")

    if awk -v p="$pct" -v t="$THRESHOLD" 'BEGIN{exit !(p<=t)}'; then
        echo "-> ${MID} users is clean (<= ${THRESHOLD}%), raising floor"
        LOW=$MID
    else
        echo "-> ${MID} users failed (> ${THRESHOLD}%), lowering ceiling"
        HIGH=$MID
    fi
    echo
done

echo "======================================"
echo "Result: last clean level ~${LOW} users, first failing level ~${HIGH} users"
echo "Full log: $SUMMARY"
echo "======================================"