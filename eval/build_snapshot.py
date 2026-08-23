#!/usr/bin/env python3
"""Freeze everything the assistant reads, so an evaluation means the same thing tomorrow (phase 39).

Without this the suite breaks every morning: the market moves, `data/` is rewritten by the daily
pipeline, and yesterday's "97% numeric exactness" becomes unreproducible. Worse, it becomes
*unfalsifiable* — you can no longer tell a regression from a Tuesday.

The snapshot is dated, immutable and hashed. Every eval path reads from here and never from `data/`;
`tests/test_eval_harness.py::test_no_eval_path_reads_live_data` enforces that mechanically.

Large frames are trimmed to a fixed window so the snapshot stays committable: the whole point is
that it can live in git beside the code it measures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SNAP_ROOT = ROOT / "eval" / "snapshot"

COPY_VERBATIM = [
    "avatar_context.json",
    "treasury_risk.json",
    "decision_table.json",
    "status.json",
    "conformal_coverage.json",
    "live_record.json",
    "visual_boards.json",
    "visual_index.json",
    "storm_replays.json",
    "events.csv",
    # phase-42 work: the archive is now part of what the assistant reads, so it belongs in any
    # snapshot that claims to freeze "everything the assistant reads".
    "archive.json",
    "answer_packs.json",
    "rollups.parquet",
]
KNOWLEDGE = ["docs/avatar_knowledge.md", "config/visual_registry.yaml"]
TRIM_WINDOW_DAYS = 800  # enough history for the comparative and aggregation families


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — a snapshot outside a checkout is still a valid snapshot
        return "unknown"


def _trim_frame(src: Path, dest: Path, date_col: str = "date") -> None:
    df = pd.read_parquet(src)
    if date_col in df.columns and len(df):
        cutoff = pd.Timestamp(df[date_col].max()) - pd.Timedelta(days=TRIM_WINDOW_DAYS)
        df = df[df[date_col] >= cutoff]
    df.to_parquet(dest, index=False)


def build(label: str | None = None) -> Path:
    stamp = label or datetime.now(UTC).strftime("%Y-%m-%d")
    out = SNAP_ROOT / stamp
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    (out / "docs").mkdir()
    (out / "config").mkdir()

    copied: list[tuple[str, Path]] = []
    for name in COPY_VERBATIM:
        src = DATA / name
        if not src.exists():
            continue
        dest = out / "data" / name
        shutil.copy2(src, dest)
        copied.append((f"data/{name}", dest))
    for rel in KNOWLEDGE:
        src = ROOT / rel
        if not src.exists():
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append((rel, dest))
    for name in ("regimes.parquet", "features.parquet", "ledger.parquet"):
        src = DATA / name
        if not src.exists():
            continue
        dest = out / "data" / name
        _trim_frame(src, dest)
        copied.append((f"data/{name}", dest))

    manifest = {rel: sha256(path) for rel, path in sorted(copied)}
    pack = json.loads((out / "data" / "avatar_context.json").read_text())
    index_path = out / "data" / "visual_index.json"
    registry_version = (
        json.loads(index_path.read_text()).get("registry_version", "—")
        if index_path.exists()
        else "—"
    )
    lines = [
        f"# Evaluation snapshot {stamp}",
        "",
        "Immutable. Every eval run reads this directory and never `data/`, so a result means the",
        "same thing next week. Rebuild only when you intend to re-baseline — see",
        "`docs/eval_process.md`, which requires a fresh baseline whenever a pinned field changes.",
        "",
        f"- built: `{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        f"- git SHA: `{git_sha()}`",
        f"- data through: `{pack.get('data_through')}`",
        f"- registry version: `{registry_version}`",
        f"- markets in pack: {len(pack.get('pairs') or {})} majors + "
        f"{sum(len(u.get('pairs') or {}) for u in (pack.get('markets') or {}).values())} across all boards",
        f"- trim window: last {TRIM_WINDOW_DAYS} days for parquet frames",
        "",
        "## Files and hashes",
        "",
        "| file | sha256 |",
        "|---|---|",
    ]
    lines += [f"| `{rel}` | `{h}` |" for rel, h in manifest.items()]
    lines.append("")
    (out / "SNAPSHOT.md").write_text("\n".join(lines))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", help="directory name (default: today's date)")
    args = ap.parse_args()
    out = build(args.label)
    n = len(json.loads((out / "manifest.json").read_text()))
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
    print(f"snapshot {out.relative_to(ROOT)}: {n} files, {size:.1f} MB")


if __name__ == "__main__":
    main()
