#!/usr/bin/env python3
"""Three questions against LIVE artifacts, asserting structure only (phase 39).

The one deliberate exception to "never evaluate against `data/`". The snapshot cannot tell you that
this morning's pipeline wrote something unreadable — by design, it is frozen. This does, and it
checks only shape: a board rendered, gates ran, nothing threw. It asserts no value, because a value
assertion against live data is the drift trap the snapshot exists to avoid.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

QUESTIONS = ["how does EURUSD look today", "why should I trust you", "will EURUSD rise tomorrow"]


def post(base: str, path: str, body: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            **({"X-Avatar-Token": token} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    args = ap.parse_args()

    tok = post(args.base, "/avatar/session-token", {"vendor": "local"})
    brain = tok.get("brain_token") or tok.get("token")
    problems: list[str] = []
    for q in QUESTIONS:
        r = post(
            args.base,
            "/avatar/brain",
            {"session_id": "smoke", "messages": [{"role": "user", "content": q}]},
            brain,
        )
        if not r.get("text", "").strip():
            problems.append(f"{q!r}: empty answer")
        if not r.get("gate"):
            problems.append(f"{q!r}: no gate decision recorded")
        for card in r.get("board") or []:
            if card.get("data") in (None, {}, []):
                problems.append(f"{q!r}: card {card.get('component')} carried no data")
            if not card.get("asof"):
                problems.append(f"{q!r}: card {card.get('component')} carried no as-of stamp")
        print(f"  ok  {q[:38]:40} gate={r.get('gate'):18} cards={len(r.get('board') or [])}")
    if problems:
        print("\nSTRUCTURAL PROBLEMS in today's artifacts:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(
        "\nlive artifacts are structurally sound (no values asserted — that is the snapshot's job)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
