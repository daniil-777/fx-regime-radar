"""Load check for the Rust service: build a real /api/score request from data/prices.parquet and
fire N sequential requests; report p50/p99 client-side latency and the server-side counters.

Usage: .venv/bin/python tools/load_check.py [http://127.0.0.1:8080] [1000]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

from fxradar import config

WINDOW = 600


def build_request(pair: str = "USDCHF") -> dict:
    prices = pd.read_parquet(config.PRICES_PATH)
    windows = []
    for p in config.PAIRS:
        g = prices[prices["pair"] == p].sort_values("date").tail(WINDOW)
        windows.append(
            {
                "pair": p,
                "dates": (g["date"].to_numpy().astype("datetime64[D]").astype("int64")).tolist(),
                "close": g["close"].tolist(),
                "high": g["high"].tolist(),
                "low": g["low"].tolist(),
            }
        )
    return {"pair": pair, "windows": windows}


def post(url: str, body: bytes) -> dict:
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    body = json.dumps(build_request()).encode()
    first = post(f"{base}/api/score", body)
    print(
        "first response:",
        {
            k: first[k]
            for k in [
                "date",
                "pair",
                "regime",
                "regime_prob",
                "change_risk_5d",
                "anomaly_pct",
                "served_by",
                "latency_us",
            ]
        },
    )
    lat = []
    t0 = time.perf_counter()
    for _ in range(n):
        t = time.perf_counter()
        post(f"{base}/api/score", body)
        lat.append((time.perf_counter() - t) * 1e3)
    total = time.perf_counter() - t0
    lat = np.array(lat)
    print(
        f"{n} requests in {total:.1f}s ({n / total:.0f} req/s sequential); client latency ms: p50 {np.percentile(lat, 50):.2f}, p99 {np.percentile(lat, 99):.2f}, max {lat.max():.2f}"
    )
    with urllib.request.urlopen(f"{base}/api/health", timeout=10) as r:
        h = json.loads(r.read())
    print("server-side score_latency_us:", h["score_latency_us"], "requests:", h["score_requests"])


if __name__ == "__main__":
    main()
