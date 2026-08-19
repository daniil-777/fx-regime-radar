"""Design tokens — the single source of truth is design/tokens.json (phase 31).

Everything that paints a pixel (the Streamlit CSS, the Plotly template, matplotlib report figures,
the regime orb presets, the e-mail report, widget.js) reads its colours from here so that
`make lint-ui` can forbid hex literals anywhere else in app/ and src/.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENS_PATH = ROOT / "design" / "tokens.json"
TOKENS: dict = json.loads(TOKENS_PATH.read_text())

# surfaces + text
BG: str = TOKENS["surface"]["nimbus"]
SURFACE: str = TOKENS["surface"]["front"]
LINE: str = TOKENS["surface"]["line"]  # rgba — for CSS borders
BORDER: str = TOKENS["surface"]["line_hex"]  # hex twin — for SVG/Plotly strokes
GRID: str = TOKENS["surface"]["grid"]
TEXT: str = TOKENS["text"]["primary"]
MUTED: str = TOKENS["text"]["secondary"]
DIM: str = TOKENS["text"]["dim"]
ACCENT: str = TOKENS["accent"]["beacon"]

# semantic: regimes + status (data and status ONLY — never decoration)
REGIME_COLORS: dict[str, str] = dict(TOKENS["regime"])
REGIME_ORDER: list[str] = ["calm", "trend", "chop", "crisis"]
OK, WATCH, BAD = TOKENS["status"]["ok"], TOKENS["status"]["watch"], TOKENS["status"]["bad"]

# light variant (e-mail report only)
LIGHT: dict[str, str] = dict(TOKENS["light"])

# type
FONT_DISPLAY: str = TOKENS["font"]["display"]
FONT_UI: str = TOKENS["font"]["ui"]
FONT_MONO: str = TOKENS["font"]["mono"]
FONT_IMPORT: str = TOKENS["font"]["google_import"]


def with_alpha(hex_color: str, alpha: float) -> str:
    """'#RRGGBB' + alpha in [0, 1] -> 'rgba(r,g,b,a)' (for translucent fills without new hex)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha:g})"


def css_variables() -> str:
    """The token set as CSS custom properties (used by ui.py and any static HTML we emit)."""
    t = TOKENS
    return (
        ":root{"
        f"--nimbus:{t['surface']['nimbus']};--front:{t['surface']['front']};--line:{t['surface']['line']};"
        f"--grid:{t['surface']['grid']};--tx1:{t['text']['primary']};--tx2:{t['text']['secondary']};"
        f"--tx3:{t['text']['dim']};--calm:{t['regime']['calm']};--trend:{t['regime']['trend']};"
        f"--chop:{t['regime']['chop']};--crisis:{t['regime']['crisis']};--beacon:{t['accent']['beacon']};"
        f"--sans:{t['font']['ui']};--mono:{t['font']['mono']};--disp:{t['font']['display']};"
        "}"
    )
