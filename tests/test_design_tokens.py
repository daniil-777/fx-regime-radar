"""Phase 31: the design system is enforced, not hoped for — one token file, no stray hex, AA
contrast for every text/surface pair, the widget and the generated config agree with the tokens,
and the motion budget is two animations (orb + live dot), both disabled under reduced motion."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from fxradar import tokens as tk

ROOT = Path(__file__).resolve().parents[1]
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def _lum(h: str) -> float:
    h = h.lstrip("#")
    c = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_no_hex_literals_outside_tokens() -> None:
    offenders = []
    for folder in ("app", "src", "scripts", "pipelines"):
        for f in (ROOT / folder).rglob("*.py"):
            for i, line in enumerate(f.read_text().splitlines(), 1):
                if HEX.search(line):
                    offenders.append(f"{f.relative_to(ROOT)}:{i}")
    assert not offenders, offenders


@pytest.mark.parametrize("surface", [tk.BG, tk.SURFACE])
def test_text_and_regime_colours_meet_aa_on_both_surfaces(surface: str) -> None:
    for name, color in {
        "text": tk.TEXT,
        "muted": tk.MUTED,
        "dim": tk.DIM,
        "accent": tk.ACCENT,
        **tk.REGIME_COLORS,
    }.items():
        assert contrast(color, surface) >= 4.5, (name, color, surface, contrast(color, surface))


def test_generated_config_and_widget_agree_with_tokens() -> None:
    cfg = (ROOT / ".streamlit" / "config.toml").read_text()
    assert tk.BG in cfg and tk.SURFACE in cfg and tk.TEXT in cfg and tk.ACCENT in cfg
    widget = ROOT / "rust" / "fxradar-serve" / "static" / "widget.js"
    if widget.exists():
        used = set(HEX.findall(widget.read_text()))
        allowed = set(tk.REGIME_COLORS.values()) | {
            tk.BG,
            tk.SURFACE,
            tk.TEXT,
            tk.MUTED,
            tk.DIM,
            tk.ACCENT,
        }
        assert used <= allowed, used - allowed


def test_orb_presets_use_token_regime_colours() -> None:
    sys.path.insert(0, str(ROOT / "app"))
    import orb  # noqa: PLC0415

    assert orb.REGIME_COLORS == tk.REGIME_COLORS


def test_motion_budget_two_animations_both_reduced_motion_safe() -> None:
    sys.path.insert(0, str(ROOT / "app"))
    import ui  # noqa: PLC0415

    css = ui.CSS
    assert css.count("@keyframes") == 1  # the live dot — the orb animates in its own iframe
    assert "prefers-reduced-motion" in css and "animation: none" in css
    orb_src = (ROOT / "app" / "orb.py").read_text()
    assert "prefers-reduced-motion" in orb_src


def test_fonts_and_weights() -> None:
    sys.path.insert(0, str(ROOT / "app"))
    import ui  # noqa: PLC0415

    assert (
        "Space Grotesk" in ui.FONT_DISPLAY
        and "IBM Plex Sans" in ui.FONT_UI
        and "IBM Plex Mono" in ui.FONT_MONO
    )
    assert (
        "wght@600" not in tk.FONT_IMPORT and "wght@700" not in tk.FONT_IMPORT
    )  # no weights above 500
    assert "font-weight: 600" not in ui.CSS and "font-weight: 700" not in ui.CSS


def test_make_lint_ui_passes() -> None:
    proc = subprocess.run(["make", "-s", "lint-ui"], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
