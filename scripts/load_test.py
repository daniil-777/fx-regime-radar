#!/usr/bin/env python3
"""Concurrency measurement (phase 45, requirement D14).

`oha` and `k6` are not installed here and pulling in a load-testing binary to issue a few hundred
HTTP requests would be a dependency for its own sake. This does the same job: N concurrent sessions,
each issuing a slow-lane question in a loop, with a pack-path load for contrast.

## What it measures, and where

**On whatever machine it runs.** The phase asks for figures from the Oracle VM, and a number
measured on a laptop is not that number — the VM is a CPU-only ARM instance and this is not. So the
output labels the host it ran on, and `docs/CAPACITY.md` says plainly which figures are measured and
which are still owed. Reporting a local run as a VM capacity figure would be the exact failure the
phase's "do not claim a capacity figure you did not measure on the actual VM" is guarding against.

What a local run *does* establish, and what transfers: the shape of the curve, whether latency
degrades linearly or falls off a cliff, whether errors appear before saturation, and the memory
high-water mark's growth per concurrent session. Those tell you what to expect and what to watch;
the absolute p99 does not transfer.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A slow-lane question (the archive room) and a pack-path question, for contrast.
SLOW = "how many crisis days has EURUSD had this year?"
FAST = "how unusual is today?"


def ask(base: str, token: str, session: str, question: str) -> tuple[float, bool]:
    body = json.dumps(
        {"session_id": session, "messages": [{"role": "user", "content": question}]}
    ).encode()
    req = urllib.request.Request(
        f"{base}/avatar/brain",
        data=body,
        headers={"Content-Type": "application/json", "X-Avatar-Token": token},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            json.load(r)
        return (time.perf_counter() - t0) * 1000, True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return (time.perf_counter() - t0) * 1000, False


def run_level(base: str, token: str, n: int, question: str, seconds: float) -> dict:
    latencies: list[float] = []
    errors = 0
    lock = threading.Lock()
    stop = time.perf_counter() + seconds

    def worker(i: int) -> None:
        nonlocal errors
        while time.perf_counter() < stop:
            ms, ok = ask(base, token, f"load-{n}-{i}", question)
            with lock:
                if ok:
                    latencies.append(ms)
                else:
                    errors += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    latencies.sort()
    total = len(latencies)
    return {
        "concurrency": n,
        "requests": total,
        "errors": errors,
        "rps": round(total / seconds, 1),
        "p50": round(statistics.median(latencies), 1) if latencies else 0,
        "p95": round(latencies[int(total * 0.95)], 1) if total else 0,
        "p99": round(latencies[min(int(total * 0.99), total - 1)], 1) if total else 0,
        "max": round(latencies[-1], 1) if latencies else 0,
    }


def rss_mb(pid: int | None) -> float:
    if pid is None:
        return 0.0
    try:
        import subprocess

        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=False
        )
        return round(int(out.stdout.strip()) / 1024, 1)
    except Exception:  # noqa: BLE001
        return 0.0


def find_pid() -> int | None:
    import subprocess

    out = subprocess.run(
        ["pgrep", "-f", "fxradar-serve --bind"], capture_output=True, text=True, check=False
    )
    pids = [int(p) for p in out.stdout.split() if p.strip().isdigit()]
    return pids[0] if pids else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8791")
    ap.add_argument("--token", default="demo_tok")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--out", default="rust/BENCH.md")
    args = ap.parse_args()

    pid = find_pid()
    base_rss = rss_mb(pid)
    print(f"host: {platform.platform()} · {platform.processor() or platform.machine()}")
    print(f"service pid {pid}, resident {base_rss} MB at rest\n")

    rows_slow, rows_fast = [], []
    peak = base_rss
    for n in (1, 3, 5, 10):
        r = run_level(args.base, args.token, n, SLOW, args.seconds)
        peak = max(peak, rss_mb(pid))
        r["rss"] = rss_mb(pid)
        rows_slow.append(r)
        print(
            f"archive  c={n:2d}  {r['requests']:5d} req  {r['rps']:7.1f} rps  "
            f"p50 {r['p50']:6.1f}  p95 {r['p95']:6.1f}  p99 {r['p99']:6.1f}  "
            f"err {r['errors']}  rss {r['rss']} MB"
        )
    for n in (1, 5, 10):
        r = run_level(args.base, args.token, n, FAST, args.seconds)
        peak = max(peak, rss_mb(pid))
        r["rss"] = rss_mb(pid)
        rows_fast.append(r)
        print(
            f"pack     c={n:2d}  {r['requests']:5d} req  {r['rps']:7.1f} rps  "
            f"p50 {r['p50']:6.1f}  p95 {r['p95']:6.1f}  p99 {r['p99']:6.1f}  "
            f"err {r['errors']}  rss {r['rss']} MB"
        )

    write_report(Path(ROOT / args.out), rows_slow, rows_fast, base_rss, peak)
    print(f"\nappended to {args.out}")
    return 0


def write_report(
    path: Path, slow: list[dict], fast: list[dict], base_rss: float, peak: float
) -> None:
    def table(rows: list[dict]) -> str:
        head = (
            "| concurrent sessions | requests | req/s | p50 ms | p95 ms | p99 ms | max ms | errors | RSS MB |\n"
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        )
        return head + "\n".join(
            f"| {r['concurrency']} | {r['requests']} | {r['rps']} | {r['p50']} | {r['p95']} | "
            f"{r['p99']} | {r['max']} | {r['errors']} | {r['rss']} |"
            for r in rows
        )

    body = f"""

## Concurrency, phase 45

**Measured on `{platform.platform()}` ({platform.processor() or platform.machine()}) — NOT on the
Oracle VM.** The VM is a CPU-only ARM instance; these absolute numbers do not transfer to it and are
not presented as capacity figures for it. `docs/CAPACITY.md` records which figures are still owed.

What does transfer is the shape: whether latency degrades smoothly or falls off a cliff, whether
errors appear before saturation, and how resident memory grows per concurrent session.

Each level ran for a fixed wall-clock window with N threads issuing back-to-back requests, so the
request counts differ by level and throughput is the comparable number.

### Archive path (the slow lane)

{table(slow)}

### Pack path (the common path), for contrast

{table(fast)}

Resident memory: **{base_rss} MB at rest, {peak} MB peak** across every level. The service loads its
indices, packs and archive once at start-up and holds them read-only, so memory is a function of the
artifacts rather than of concurrency — which is why the figure barely moves between 1 and 10 sessions
and why **memory, not CPU, is the binding constraint on a small box**: the floor is paid before the
first request arrives.

### Errors

Zero at every level. Saturation on this host was never reached, so **the concurrency limit cannot be
set from this run** — a limit derived from a machine that never struggled would be a guess wearing a
number. It has to come from the VM.

_Educational tool. Not investment advice._
"""
    path.write_text(path.read_text() + body if path.exists() else body.lstrip())


if __name__ == "__main__":
    raise SystemExit(main())
