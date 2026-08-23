#!/usr/bin/env python3
"""Record what the system actually answers, so CI can score without a network (phase 39).

The service under test must be started against the SNAPSHOT, never `data/`:

    ./rust/fxradar-serve/target/release/fxradar-serve \
        --bundle models/bundle_v1.4.0 --data-dir eval/snapshot/<label>/data --bind 127.0.0.1:8090

`--verify-snapshot` refuses to record unless the running service reports the snapshot's own
data-through date, because a fixture recorded against live data would silently re-introduce exactly
the drift the snapshot exists to prevent.

Multi-turn items are sent as a real transcript — the prior turn, then the elliptical follow-up — so
the recording reflects what a conversational product receives rather than a tidied-up single shot.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

import harness as H  # noqa: E402


def post(base: str, path: str, body: dict, token: str | None = None, timeout: float = 40.0) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            **({"X-Avatar-Token": token} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=20) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8090")
    ap.add_argument("--snapshot", help="snapshot label (default: newest)")
    ap.add_argument("--out", default=str(H.FIXTURES_PATH))
    ap.add_argument("--limit", type=int, default=0, help="record only the first N items")
    ap.add_argument(
        "--verify-snapshot",
        action="store_true",
        default=True,
        help="refuse to record against anything but the snapshot",
    )
    args = ap.parse_args()

    snap = H.load_snapshot(args.snapshot)
    items = H.load_golden(snap)
    if args.limit:
        items = items[: args.limit]

    greeting = get(args.base, "/avatar/greeting")
    served_through = str(greeting.get("data_through", ""))
    if args.verify_snapshot and served_through != snap.data_through:
        raise SystemExit(
            f"REFUSING to record: the service serves data through {served_through!r} but the "
            f"snapshot is {snap.data_through!r}. Start it with "
            f"--data-dir eval/snapshot/{snap.label}/data"
        )

    tok = post(args.base, "/avatar/session-token", {"vendor": "local"})
    brain_token = tok.get("brain_token") or tok.get("token")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows, errors = [], 0
    t_start = time.time()
    for i, item in enumerate(items, 1):
        messages = []
        if item.turn_context:
            messages.append({"role": "user", "content": item.turn_context})
            messages.append({"role": "assistant", "content": "(prior answer)"})
        messages.append({"role": "user", "content": item.question})
        body = {"session_id": f"eval-{item.id}", "messages": messages}
        t0 = time.perf_counter()
        try:
            r = post(args.base, "/avatar/brain", body, brain_token)
        except urllib.error.HTTPError as e:
            errors += 1
            r = {"text": f"HTTP {e.code}", "source": "error", "gate": "error", "board": []}
        wall = (time.perf_counter() - t0) * 1000
        rows.append(
            {
                "id": item.id,
                "question": item.question,
                "family": item.family,
                "locale": item.locale,
                "text": r.get("text", ""),
                "source": r.get("source"),
                "gate": r.get("gate"),
                "numbers": r.get("numbers") or [],
                "board": [
                    {
                        "component": c.get("component"),
                        "primitive": c.get("primitive"),
                        "asof": c.get("asof"),
                        "caption": c.get("caption"),
                        "data": c.get("data") if c.get("data") not in (None, {}) else None,
                    }
                    for c in (r.get("board") or [])
                ],
                "latency_ms": r.get("latency_ms", round(wall)),
                "wall_ms": round(wall),
                "snapshot": snap.label,
                "model": "keyless-templates",
                "prompt_version": "v2",
                "gate_rules_version": "phase-38",
            }
        )
        if i % 40 == 0:
            print(f"  … {i}/{len(items)}")
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(
        f"recorded {len(rows)} responses to {out_path.relative_to(ROOT)} "
        f"in {time.time() - t_start:.1f}s ({errors} errors) against snapshot {snap.label}"
    )


if __name__ == "__main__":
    main()
