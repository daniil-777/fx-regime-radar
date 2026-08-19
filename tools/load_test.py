"""Load test for the Rust service (phase 24): concurrent keep-alive clients, p50/p95/p99 + rps.

Usage: .venv/bin/python tools/load_test.py [base_url] [api_key] [--n 2000] [--c 8]
Routes: POST /api/score (needs a pro/partner key; real 600-day windows from data/prices.parquet),
GET /api/regimes/EURUSD (public), GET /api/health (public). Honest caveat: laptop + localhost,
Python client overhead included in the client-side numbers; start the service with a high
--rate-limit-per-min (the default 60/min is a product setting, not a throughput limit).
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_check import build_request  # noqa: E402


def run(
    base: str, method: str, path: str, body: bytes | None, headers: dict, n: int, c: int
) -> dict:
    u = urlparse(base)
    lat: list[float] = []
    codes: dict[int, int] = {}
    lock = threading.Lock()
    per = n // c

    def worker() -> None:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=30)
        local = []
        local_codes: dict[int, int] = {}
        for _ in range(per):
            t = time.perf_counter()
            conn.request(method, path, body=body, headers=headers)
            r = conn.getresponse()
            r.read()
            local.append((time.perf_counter() - t) * 1e3)
            local_codes[r.status] = local_codes.get(r.status, 0) + 1
        with lock:
            lat.extend(local)
            for k, v in local_codes.items():
                codes[k] = codes.get(k, 0) + v

    threads = [threading.Thread(target=worker) for _ in range(c)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.perf_counter() - t0
    a = np.array(lat)
    return {
        "route": f"{method} {path}",
        "n": len(a),
        "concurrency": c,
        "rps": len(a) / total,
        "p50_ms": float(np.percentile(a, 50)),
        "p95_ms": float(np.percentile(a, 95)),
        "p99_ms": float(np.percentile(a, 99)),
        "max_ms": float(a.max()),
        "status": codes,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8080")
    ap.add_argument("key", nargs="?", default="")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--c", type=int, default=8)
    args = ap.parse_args()
    results = []
    results.append(run(args.base, "GET", "/api/regimes/EURUSD", None, {}, args.n, args.c))
    results.append(run(args.base, "GET", "/api/health", None, {}, args.n, args.c))
    if args.key:
        body = json.dumps(build_request()).encode()
        hdr = {"Content-Type": "application/json", "X-API-Key": args.key}
        results.append(run(args.base, "POST", "/api/score", body, hdr, args.n, args.c))
    for r in results:
        print(
            f"{r['route']:<28} n={r['n']} c={r['concurrency']}  {r['rps']:7.0f} req/s  "
            f"p50 {r['p50_ms']:.2f} ms  p95 {r['p95_ms']:.2f} ms  p99 {r['p99_ms']:.2f} ms  max {r['max_ms']:.1f} ms  status={r['status']}"
        )


if __name__ == "__main__":
    main()
