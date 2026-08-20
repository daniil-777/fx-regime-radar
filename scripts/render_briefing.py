#!/usr/bin/env python3
"""The async sibling (phase 35): a ~90-second presenter MP4 of the Monday briefing.

Independent flag from the live concierge. Drafts the script from the same deterministic
`template_narrate` path as the weekly report (so it is lint-clean by construction), then:
  * with HEYGEN_API_KEY set and FXRADAR_BRIEFING_MP4=on — submits a video-generation job to the
    HeyGen video API and prints the job id (the finished MP4 is HUMAN-REVIEWED before publish,
    always; nothing is auto-published);
  * otherwise — writes the reviewed-script text beside the weekly report and stops, honestly.
Usage: .venv/bin/python scripts/render_briefing.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fxradar import avatar_context, narrate  # noqa: E402

OUT_DIR = ROOT / "docs" / "weekly"


def build_script() -> str:
    pack = json.loads(avatar_context.CONTEXT_PATH.read_text())
    lines = [
        pack["disclosure"],
        f"This is the radar briefing for the week of {pack['data_through']}.",
    ]
    for blk in pack["pairs"].values():
        band = (
            f", band {blk['risk_lo']:.2f} to {blk['risk_hi']:.2f}"
            if blk.get("risk_lo") is not None
            else ""
        )
        lines.append(
            f"{blk['label']} is {blk['regime']} — change risk {blk['change_risk_5d']:.2f}{band}, "
            f"siren {blk['anomaly_pct']:.0f} of 100."
        )
    ev = pack.get("events") or []
    if ev:
        nxt = ev[0]
        lines.append(f"Next on the calendar: {nxt['type']} in {nxt['days']} days.")
    led = pack["ledger"]
    lines.append(
        f"The forward test is on day {led['days_live']}; every forecast is hash-chained before its "
        "outcome, and you can verify the chain yourself from the proof page."
    )
    lines.append("Risk information, not investment advice.")
    script = " ".join(lines)
    narrate.check_narration(script)  # the same rule-5 gate as everything spoken
    return script


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    script = build_script()
    stamp = args.date or json.loads(avatar_context.CONTEXT_PATH.read_text())["data_through"]
    out = OUT_DIR / f"briefing_script_{stamp}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(script + "\n")
    print(f"script ({len(script.split())} words, lint-clean) -> {out}")
    if os.environ.get("FXRADAR_BRIEFING_MP4") != "on":
        print("FXRADAR_BRIEFING_MP4 is not 'on' — stopping at the reviewed script (by design).")
        return
    key = os.environ.get("HEYGEN_API_KEY")
    if not key:
        print("HEYGEN_API_KEY not set — cannot render; the script above is the deliverable.")
        return
    import requests

    resp = requests.post(
        "https://api.heygen.com/v2/video/generate",
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
        json={
            "video_inputs": [
                {
                    "character": {
                        "type": "avatar",
                        "avatar_id": os.environ.get("HEYGEN_AVATAR_ID", ""),
                    },
                    "voice": {"type": "text", "input_text": script},
                }
            ],
            "dimension": {"width": 1280, "height": 720},
        },
        timeout=30,
    )
    resp.raise_for_status()
    print("HeyGen job submitted:", resp.json())
    print("REVIEW THE MP4 BEFORE PUBLISHING — nothing is auto-published.")


if __name__ == "__main__":
    main()
