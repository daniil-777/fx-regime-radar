"""Render the regime tetrahedron for the flagship pair as an orbiting GIF for the README header.

Usage: .venv/bin/python scripts/make_gif.py [--frames 72] [--width 600] [--out assets/tetrahedron.gif]
72 frames at 5° steps, fixed elevation, per-frame PNG via kaleido (`fig.write_image`), stitched with
imageio. Target < 5 MB: if the file is larger, frames and then width are reduced until it fits.
kaleido and imageio are DEV-ONLY dependencies (requirements-dev.txt); the app never needs them.
Display layer only — reads artifacts + the frozen bundle, changes nothing.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
from pathlib import Path

import imageio.v3 as iio
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxradar import config, viz3d  # noqa: E402
from fxradar import tokens as tk  # noqa: E402

MAX_BYTES = 5 * 1024 * 1024
ELEVATION_Z = 0.9  # camera height (fixed elevation); radius chosen to frame the whole tetrahedron
RADIUS = 2.1


def flagship_pair() -> str:
    return "EURUSD" if "EURUSD" in config.PAIRS else config.PAIRS[0]


def render_frames(fig, n_frames: int, width: int) -> list[np.ndarray]:
    """One PNG per camera angle: 360°/n_frames steps around the z-axis at fixed elevation."""
    frames = []
    for i in range(n_frames):
        theta = 2 * math.pi * i / n_frames
        fig.update_layout(
            scene_camera=dict(
                eye=dict(x=RADIUS * math.cos(theta), y=RADIUS * math.sin(theta), z=ELEVATION_Z)
            ),
            width=width,
            height=width,
            margin=dict(l=0, r=0, t=0, b=0),
            title=None,
            paper_bgcolor=tk.BG,
        )
        png = fig.to_image(format="png", width=width, height=width, scale=1)
        frames.append(iio.imread(io.BytesIO(png)))
    return frames


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=72)
    ap.add_argument("--width", type=int, default=600)
    ap.add_argument("--out", default=str(ROOT / "assets" / "tetrahedron.gif"))
    a = ap.parse_args()
    pair = flagship_pair()
    features, regimes, bundles = viz3d.load_inputs()
    frame = viz3d.probability_frame(pair, features, regimes, bundles[pair])
    fig = viz3d.tetrahedron_figure(frame, pair, "time")
    fig.update_layout(font=dict(color=tk.TEXT))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_frames, width = a.frames, a.width
    while True:
        frames = render_frames(fig, n_frames, width)
        iio.imwrite(out, frames, duration=60, loop=0)  # 60 ms/frame ≈ 4.3 s per orbit
        size = out.stat().st_size
        print(f"{out}: {n_frames} frames × {width}px -> {size / 1e6:.2f} MB")
        if size <= MAX_BYTES:
            break
        if n_frames > 36:  # reduce frames first (coarser rotation), then width
            n_frames //= 2
        elif width > 300:
            width = int(width * 0.8)
        else:
            raise SystemExit("could not get the GIF under 5 MB")
    print(f"done: {pair}, {n_frames} frames, {width}px, {size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
