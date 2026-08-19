#!/usr/bin/env python3
"""Styleframe kit for the launch film (docs/film/REFS.md) — text-free reference stills for
Veo 3.1 "ingredients" / first-frame conditioning, derived from the real design tokens so the
generated footage inherits the product's exact palette. Run: .venv/bin/python docs/film/make_refs.py
(orb + chain frames additionally need tools/screenshot.py, called below)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from fxradar import tokens as tk  # noqa: E402

OUT = ROOT / "docs" / "film" / "refs"
OUT.mkdir(parents=True, exist_ok=True)


def hx(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


NIMBUS, FRONT = hx(tk.BG), hx(tk.SURFACE)
CALM, TREND, CHOP, CRISIS = (hx(tk.REGIME_COLORS[r]) for r in ("calm", "trend", "chop", "crisis"))
BEACON, TEXT = hx(tk.ACCENT), hx(tk.TEXT)


def canvas(w: int, h: int, top=None, bottom=None) -> Image.Image:
    top, bottom = top or NIMBUS, bottom or (8, 12, 20)
    g = np.linspace(0, 1, h)[:, None, None]
    arr = (np.array(top) * (1 - g) + np.array(bottom) * g).astype(np.uint8)
    return Image.fromarray(np.tile(arr, (1, w, 1)))


def vignette(im: Image.Image, strength: float = 0.55) -> Image.Image:
    w, h = im.size
    y, x = np.mgrid[0:h, 0:w]
    d = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2)
    mask = np.clip(1 - strength * np.clip(d - 0.55, 0, None) ** 1.5, 0, 1)
    return Image.fromarray((np.asarray(im, dtype=float) * mask[..., None]).astype(np.uint8))


def glow(draw_target: Image.Image, xy, radius: int, color, alpha: float):
    """Additive radial glow blended onto the image."""
    w, h = draw_target.size
    y, x = np.mgrid[0:h, 0:w]
    d2 = ((x - xy[0]) ** 2 + (y - xy[1]) ** 2) / radius**2
    g = np.exp(-d2)[..., None] * np.array(color) * alpha
    arr = np.clip(np.asarray(draw_target, dtype=float) + g, 0, 255).astype(np.uint8)
    draw_target.paste(Image.fromarray(arr))


# ---- 1. grade card: cinematic colour script, text-free ---------------------------------------
def grade_card():
    im = canvas(1920, 1080)
    glow(im, (960, -250), 900, TEXT, 0.10)  # cool sky sheen
    glow(im, (480, 780), 700, BEACON, 0.14)  # teal water shimmer
    glow(im, (1560, 900), 420, CHOP, 0.18)  # warm amber lamp corner
    glow(im, (1770, 240), 300, CRISIS, 0.10)  # far storm hint
    im = im.filter(ImageFilter.GaussianBlur(6))
    vignette(im).save(OUT / "ref_grade_card.png")


# ---- 2. radar sweep plate --------------------------------------------------------------------
def radar_sweep():
    w, h = 1920, 1080
    rng = np.random.default_rng(7)
    base = np.tile(np.asarray(canvas(w, h), dtype=float), (1, 1, 1))
    y, x = np.mgrid[0:h, 0:w]
    cx, cy = w / 2, h / 2 + 40
    r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    theta = np.arctan2(y - cy, x - cx)
    # topographic contours from a smooth random field
    field = rng.normal(size=(h // 8, w // 8))
    field_im = Image.fromarray((field - field.min()) / (np.ptp(field) + 1e-9) * 255).convert("L")
    field = (
        np.asarray(field_im.resize((w, h)).filter(ImageFilter.GaussianBlur(60)), dtype=float)
        / 255.0
    )
    contours = (np.abs((field * 14) % 1 - 0.5) < 0.03).astype(float)
    base += contours[..., None] * np.array(TEXT) * 0.05
    # range rings + spokes at 7% white
    rings = (np.abs((r % 130) - 0) < 1.1) & (r < 540)
    spokes = (np.abs((theta + np.pi) % (np.pi / 4)) < 0.004) & (r < 540)
    base += (rings | spokes)[..., None] * np.array(TEXT) * 0.07
    # the sweep beam with decaying trail (classic radar)
    sweep_at = 0.8
    ang = (sweep_at - theta) % (2 * np.pi)
    trail = np.exp(-ang / 0.55) * (r < 540) * np.exp(-r / 750)
    base += trail[..., None] * np.array(TREND) * 0.7
    edge = (ang < 0.015) * (r < 540)  # the bright leading edge of the beam
    base += edge[..., None] * np.array(TEXT) * 0.55
    # anomaly bloom in amber, just behind the beam
    bx, by = cx + 300, cy - 150
    bloom = np.exp(-((x - bx) ** 2 + (y - by) ** 2) / 70**2)
    base += bloom[..., None] * np.array(CHOP) * 1.0
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    # particles clustering toward the hotspot
    d = ImageDraw.Draw(im)
    for _ in range(260):
        px, py = rng.normal(bx, 150), rng.normal(by, 110)
        if (px - cx) ** 2 + (py - cy) ** 2 < 540**2:
            d.ellipse([px - 1.5, py - 1.5, px + 1.5, py + 1.5], fill=(*CHOP, 255))
    for _ in range(300):
        a, rr = rng.uniform(0, 2 * np.pi), rng.uniform(0, 520)
        px, py = cx + rr * np.cos(a), cy + rr * np.sin(a)
        d.ellipse([px - 1, py - 1, px + 1, py + 1], fill=(*BEACON, 255))
    vignette(im.filter(ImageFilter.GaussianBlur(0.6)), 0.65).save(OUT / "ref_radar_sweep.png")


# ---- 3. monitor in a dark room (blurred REAL dashboard — no legible text) --------------------
def monitor_room(src: str, out: str, size=(1920, 1080), screen_w=1150):
    w, h = size
    im = canvas(w, h, bottom=(6, 9, 15))
    shot = Image.open(ROOT / "docs" / "screenshots" / src).convert("RGB")
    sw = screen_w
    sh = int(sw * 9 / 16)
    screen = shot.crop((300, 0, shot.width, int((shot.width - 300) * 9 / 16))).resize((sw, sh))
    screen = screen.resize((sw // 6, sh // 6)).resize((sw, sh))
    screen = screen.filter(ImageFilter.GaussianBlur(22))  # abstract: every word truly illegible
    x0, y0 = (w - sw) // 2, int(h * 0.16)
    glow(im, (w // 2, y0 + sh // 2), int(sw * 0.75), CALM, 0.10)  # spill behind the monitor
    bezel = ImageDraw.Draw(im)
    bezel.rounded_rectangle([x0 - 14, y0 - 14, x0 + sw + 14, y0 + sh + 14], 18, fill=(10, 14, 22))
    im.paste(screen, (x0, y0))
    # desk band + screen reflection smear + amber lamp accent
    desk = ImageDraw.Draw(im)
    desk.rectangle([0, y0 + sh + 14, w, h], fill=(9, 12, 19))
    refl = (
        screen.resize((sw, 140))
        .transpose(Image.FLIP_TOP_BOTTOM)
        .filter(ImageFilter.GaussianBlur(24))
    )
    refl = Image.fromarray((np.asarray(refl, dtype=float) * 0.25).astype(np.uint8))
    im.paste(refl, (x0, y0 + sh + 15))
    glow(im, (int(w * 0.12), int(h * 0.86)), 260, CHOP, 0.22)
    vignette(im, 0.7).save(OUT / out)


# ---- 4. phone alert glow ---------------------------------------------------------------------
def phone_alert():
    w, h = 1920, 1080
    im = canvas(w, h, bottom=(6, 9, 15))
    pw, ph = 340, 700
    x0, y0 = (w - pw) // 2, (h - ph) // 2 + 60
    glow(im, (w // 2, h // 2 + 40), 520, CRISIS, 0.16)  # coral wash on the desk
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0 - 10, y0 - 10, x0 + pw + 10, y0 + ph + 10], 46, fill=(12, 16, 25))
    d.rounded_rectangle(
        [x0 - 10, y0 - 10, x0 + pw + 10, y0 + ph + 10], 46, outline=(40, 52, 74), width=2
    )
    scr = canvas(pw, ph, top=CRISIS, bottom=TREND).filter(ImageFilter.GaussianBlur(40))
    scr = Image.fromarray((np.asarray(scr, dtype=float) * 0.55).astype(np.uint8))
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw, ph], 38, fill=255)
    im.paste(scr, (x0, y0), mask)
    glow(im, (w // 2, y0 + 120), 240, CRISIS, 0.28)
    glow(im, (int(w * 0.15), int(h * 0.84)), 260, CHOP, 0.16)
    vignette(im, 0.72).save(OUT / "ref_phone_alert.png")


# ---- 5. orb + chain frames come from HTML renders (WebGL / CSS) via tools/screenshot.py -------
ORB_PAGE = """<html><body style="margin:0;background:{bg};display:flex;align-items:center;justify-content:center;height:100vh">
<div style="transform:translateY({dy}px)">{orb}</div></body></html>"""

CHAIN_PAGE = """<html><body style="margin:0;background:{bg};height:100vh;overflow:hidden;position:relative">
<div style="position:absolute;left:50%;top:0;width:60vw;height:70vh;transform:translateX(-50%);
  background:radial-gradient(ellipse 45% 90% at 50% 0%,rgba(232,236,244,0.07),transparent 70%)"></div>
<div style="position:absolute;left:0;right:0;top:74%;bottom:0;background:linear-gradient(rgba(21,29,46,0.9),rgba(6,9,15,1))"></div>
<div style="position:absolute;left:50%;top:{top}%;transform:translate(-50%,-50%);display:flex;align-items:center;gap:26px">
{blocks}
</div>
<div style="position:absolute;left:50%;top:{rtop}%;transform:translate(-50%,0) scaleY(-1);display:flex;align-items:center;gap:26px;
  opacity:0.18;filter:blur(6px);-webkit-mask-image:linear-gradient(rgba(0,0,0,1),transparent 70%)">
{blocks}
</div></body></html>"""

BLOCK = """<div style="width:{w}px;height:{w}px;border-radius:22px;border:1.5px solid rgba(127,209,201,{ba});
  background:linear-gradient(160deg,rgba(127,209,201,0.10),rgba(21,29,46,0.85));
  box-shadow:0 0 {g}px rgba(127,209,201,{ga}){seal}"></div>"""
LINK = """<div style="width:44px;height:6px;border-radius:3px;background:rgba(127,209,201,0.55);
  box-shadow:0 0 18px rgba(127,209,201,0.5)"></div>"""


def chain_html(seal_index: int = 2, n: int = 5, w: int = 150) -> str:
    parts = []
    for i in range(n):
        seal = (
            ",0 0 90px rgba(232,236,244,0.95),inset 0 0 40px rgba(232,236,244,0.5)"
            if i == seal_index
            else ""
        )
        ba, ga, g = (0.95, 0.75, 70) if i == seal_index else (0.55, 0.35, 34)
        parts.append(BLOCK.format(w=w, ba=ba, g=g, ga=ga, seal=seal))
        if i < n - 1:
            parts.append(LINK)
    return "".join(parts)


def shoot(html: str, out: str, w: int, h: int):
    tmp = OUT / "_tmp.html"
    tmp.write_text(html)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "screenshot.py"),
            f"file://{tmp}",
            str(OUT / out),
            "--wait",
            "6",
            "--width",
            str(w),
            "--height",
            str(h),
        ],
        check=True,
    )
    tmp.unlink()


def orb_frames():
    sys.path.insert(0, str(ROOT / "app"))
    import orb as orb_mod

    for name, regime, risk, pct, size, dy, w, h in [
        ("ref_orb_calm.png", "calm", 0.04, 20, 640, -30, 1920, 1080),
        ("ref_orb_amber.png", "chop", 0.35, 80, 640, -30, 1920, 1080),
        ("ref_orb_crisis.png", "crisis", 0.75, 99, 640, -30, 1920, 1080),
        ("ref_endcard_plate.png", "calm", 0.04, 15, 280, 240, 1920, 1080),
        ("ref_v1_orb_916.png", "crisis", 0.75, 99, 620, -40, 1080, 1920),
    ]:
        html = ORB_PAGE.format(bg=tk.BG, dy=dy, orb=orb_mod.orb_html(regime, risk, pct, size=size))
        shoot(html, name, w, h)
        # volumetric bloom pass: find the orb's centroid from its own pixels, add a soft glow
        im = Image.open(OUT / name).convert("RGB")
        arr = np.asarray(im, dtype=float)
        bright = arr.sum(axis=2) > 90
        if bright.any():
            ys, xs = np.nonzero(bright)
            cx, cy = float(xs.mean()), float(ys.mean())
            color = {"calm": CALM, "chop": CHOP, "crisis": CRISIS}[regime]
            glow(im, (cx, cy), int(size * 0.62), color, 0.22)
            glow(im, (cx, cy), int(size * 0.30), color, 0.18)
        vignette(im, 0.5).save(OUT / name)


def chain_frames():
    shoot(
        CHAIN_PAGE.format(bg=tk.BG, top=52, rtop=64, blocks=chain_html()),
        "ref_chain_seal.png",
        1920,
        1080,
    )
    shoot(
        CHAIN_PAGE.format(bg=tk.BG, top=44, rtop=56, blocks=chain_html(n=3, w=170)),
        "ref_v3_chain_916.png",
        1080,
        1920,
    )


if __name__ == "__main__":
    grade_card()
    radar_sweep()
    monitor_room("overview_v3.png", "ref_monitor_room.png")
    monitor_room("proof.png", "ref_monitor_room_alt.png")
    monitor_room("overview_v3.png", "ref_v2_monitor_916.png", size=(1080, 1920), screen_w=900)
    phone_alert()
    orb_frames()
    chain_frames()
    print("styleframes ->", OUT)
