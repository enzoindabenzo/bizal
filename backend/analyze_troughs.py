#!/usr/bin/env python3
"""
Analizon spa access log rreth momenteve specifike të trough-eve (500u run).
Përdorim: python3 analyze_troughs.py /tmp/spa_access_500u.log
"""
import re, sys
from datetime import datetime, timezone
from collections import defaultdict, Counter

LOG_RE = re.compile(
    r'^spa-1\s*\|\s*(?P<iso>\S+)Z\s*\[[^\]]+\]\s*(?P<ip>\S+)\s*"(?P<method>\S+)\s+(?P<path>\S+)\s+HTTP[^"]*"\s*(?P<status>\d+)\s+(?P<size>\S+)\s+(?P<dur>\d+)us'
)

# Trough centers (seconds from run start) — nga analiza e mëparshme e 500u
TROUGHS = [116, 256, 386, 507, 638, 767]
WINDOW = 20  # sekonda para/pas qendrës për të parë

def parse(path):
    rows = []
    with open(path, 'r', errors='replace') as f:
        for line in f:
            m = LOG_RE.match(line)
            if not m:
                continue
            iso = m.group('iso')
            iso_fixed = iso[:26] if len(iso) > 26 else iso
            try:
                ts = datetime.strptime(iso_fixed, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            rows.append({
                'ts': ts, 'ip': m.group('ip'), 'path': m.group('path'),
                'status': int(m.group('status')), 'dur_us': int(m.group('dur')),
            })
    return rows

def main():
    logpath = sys.argv[1]
    rows = parse(logpath)
    if not rows:
        print("Asnjë rresht i përpunuar."); return
    rows.sort(key=lambda r: r['ts'])
    t0 = rows[0]['ts']
    for r in rows:
        r['sec'] = (r['ts'] - t0).total_seconds()

    # 1) Global per-second throughput (compact, 10s buckets)
    per_bucket = defaultdict(list)
    for r in rows:
        per_bucket[int(r['sec']//10)*10].append(r)
    max_b = max(per_bucket.keys())
    print("=== THROUGHPUT PËR 10s (kontroll i përgjithshëm) ===")
    print("sec_start\treq_count\treq/s_avg")
    for b in range(0, max_b+10, 10):
        items = per_bucket.get(b, [])
        print(f"{b}\t{len(items)}\t{len(items)/10:.1f}")

    # 2) Zoom on each trough window
    print("\n=== ZOOM NË TROUGHS ===")
    for center in TROUGHS:
        lo, hi = center - WINDOW, center + WINDOW
        window_rows = [r for r in rows if lo <= r['sec'] <= hi]
        print(f"\n--- Trough @t={center}s (dritare {lo}-{hi}s), {len(window_rows)} kërkesa ---")
        if not window_rows:
            print("  (asnjë kërkesë në këtë dritare — vetë boshllëku është gjetja)")
            continue
        errs = [r for r in window_rows if r['status'] >= 400]
        slow = sorted(window_rows, key=lambda r: -r['dur_us'])[:8]
        status_counts = Counter(r['status'] for r in window_rows)
        path_counts = Counter(r['path'] for r in window_rows)
        print(f"  Status codes: {dict(status_counts)}")
        print(f"  Gabime (4xx/5xx): {len(errs)}")
        if errs:
            for e in errs[:5]:
                print(f"    t={e['sec']:.1f}s status={e['status']} path={e['path']} dur={e['dur_us']/1000:.0f}ms")
        print(f"  Top 8 kërkesat më të ngadalta në dritare:")
        for r in slow:
            print(f"    t={r['sec']:.1f}s status={r['status']} dur={r['dur_us']/1000:.0f}ms path={r['path']}")
        print(f"  Top 5 endpoints (nga freq) në dritare: {path_counts.most_common(5)}")

if __name__ == '__main__':
    main()