#!/usr/bin/env python3
"""Generate widget-tokens.css — the ONLY stylesheet the fifty cards may use (phase 38).

Every colour comes from design/tokens.json, so `make lint-ui` stays green and a token change
repaints all fifty cards at once. Written to two places: docs/ (the phase-36 widget's home, per
the brief) and the Rust static dir (what the service actually serves). Run via `make tokens`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fxradar import tokens as tk  # noqa: E402

# Fixed height bands, mirrored from cards.js HEIGHT_BAND — a board must never reflow.
BANDS = {
    "stat_block": 132,
    "bar_row": 184,
    "trace_band": 200,
    "ribbon": 96,
    "table": 224,
    "dot_row": 88,
    "media_frame": 240,
    "diagram_frame": 200,
}

COMPONENTS = """
/* ---- the card frame ------------------------------------------------------------------------- */
.fxc{background:var(--fx-front);border:1px solid var(--fx-line);border-radius:var(--fx-radius-card);
  padding:12px 14px;margin:0;display:flex;flex-direction:column;gap:8px;position:relative;
  color:var(--fx-text);font-family:var(--fx-ui);overflow:hidden}
.fxc-num{font-family:var(--fx-mono);font-variant-numeric:tabular-nums}
.fxc-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.fxc-title{font-family:var(--fx-display);font-weight:500;font-size:13px;letter-spacing:.02em;
  text-transform:lowercase}
.fxc-meta{display:flex;align-items:center;gap:6px}
.fxc-asof{font-size:10.5px;color:var(--fx-text-dim)}
.fxc-stale{font-family:var(--fx-mono);font-size:10px;color:var(--fx-chop);
  border:1px solid var(--fx-line);border-radius:4px;padding:0 4px}
.fxc-body{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;justify-content:center;gap:6px}
.fxc-caption{font-size:11.5px;color:var(--fx-text-secondary);line-height:1.45}
.fxc-subline{font-size:11px;color:var(--fx-text-dim)}
.fxc-export{position:absolute;top:8px;right:8px;opacity:0;background:var(--fx-nimbus);
  border:1px solid var(--fx-line);border-radius:var(--fx-radius-pill);color:var(--fx-text-secondary);
  font-family:var(--fx-ui);font-size:10.5px;padding:2px 8px;cursor:pointer}
.fxc:hover .fxc-export,.fxc-export:focus-visible{opacity:1}
.fxc-export:focus-visible{outline:2px solid var(--fx-beacon);outline-offset:2px}
/* skeleton: a still placeholder — the motion budget forbids a shimmer */
.fxc-skeleton .fxc-skel-block{flex:1 1 auto;border-radius:8px;background:var(--fx-nimbus);
  border:1px dashed var(--fx-line)}
/* ---- P1 stat_block -------------------------------------------------------------------------- */
.fxc-stats{display:flex;gap:18px;flex-wrap:wrap}
.fxc-stat-value{font-family:var(--fx-display);font-size:26px;font-weight:500;line-height:1.1}
.fxc-stat-label{font-size:10.5px;color:var(--fx-text-dim);text-transform:uppercase;letter-spacing:.06em}
/* ---- P2 bar_row ----------------------------------------------------------------------------- */
.fxc-bars{gap:7px}
.fxc-bar-row{display:grid;grid-template-columns:minmax(64px,34%) 1fr auto;align-items:center;gap:8px}
.fxc-bar-label{font-size:11.5px;color:var(--fx-text-secondary);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.fxc-bar-track{height:8px;background:var(--fx-nimbus);border:1px solid var(--fx-line);border-radius:5px;
  overflow:hidden}
.fxc-bar-fill{height:100%;background:var(--fx-text-dim)}
.fxc-bar-fill.is-primary{background:var(--fx-beacon)}
.fxc-bar-value{font-size:11.5px;color:var(--fx-text)}
/* ---- P3 trace_band -------------------------------------------------------------------------- */
.fxc-trace{width:100%;height:128px;display:block}
.fxc-trace-band{fill:var(--fx-beacon);opacity:.16}
.fxc-trace-line{stroke:var(--fx-text);stroke-width:1.4;vector-effect:non-scaling-stroke}
.fxc-trace-end{fill:var(--fx-beacon)}
/* ---- P4 ribbon ------------------------------------------------------------------------------ */
.fxc-ribbon{display:flex;height:22px;border-radius:6px;overflow:hidden;border:1px solid var(--fx-line)}
.fxc-ribbon-seg{height:100%;background:var(--fx-text-dim)}
.fxc-legend{display:flex;gap:12px;flex-wrap:wrap;font-size:10.5px;color:var(--fx-text-dim)}
.fxc-legend-item{display:inline-flex;align-items:center;gap:5px}
/* ---- P5 table ------------------------------------------------------------------------------- */
.fxc-tablewrap{overflow:auto}
.fxc-table{width:100%;border-collapse:collapse;font-size:11.5px}
.fxc-table th{text-align:left;font-weight:500;color:var(--fx-text-dim);font-size:10px;
  text-transform:uppercase;letter-spacing:.05em;padding:0 0 4px}
.fxc-table td{padding:3px 0;border-top:1px solid var(--fx-line);color:var(--fx-text-secondary)}
.fxc-right{text-align:right}
/* ---- P6 dot_row ----------------------------------------------------------------------------- */
.fxc-dots{flex-direction:row;gap:18px;align-items:center}
.fxc-dotcell{display:flex;flex-direction:column;align-items:center;gap:4px}
.fxc-dot{width:8px;height:8px;border-radius:50%;background:var(--fx-text-dim);display:inline-block}
.fxc-dot-lg{width:12px;height:12px}
.fxc-dot.is-empty{background:transparent;border:1px solid var(--fx-line)}
.fxc-dot-label{font-size:10.5px;color:var(--fx-text-secondary)}
.fxc-dot-sub{font-size:10px;color:var(--fx-text-dim)}
/* ---- P7 media_frame ------------------------------------------------------------------------- */
.fxc-media-el{width:100%;height:100%;object-fit:cover;border-radius:8px;background:var(--fx-nimbus);
  max-height:170px}
.fxc-media-empty{color:var(--fx-text-dim);font-size:11.5px;text-align:center;padding:20px 0}
/* ---- P8 diagram_frame ----------------------------------------------------------------------- */
.fxc-diagram-holder{display:flex;align-items:center;justify-content:center;flex:1 1 auto}
.fxc-diagram-holder svg{max-width:100%;max-height:150px}
/* ---- boards --------------------------------------------------------------------------------- */
.fxc-board{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
@media (max-width:420px){.fxc-board{grid-template-columns:1fr}.fxc-stat-value{font-size:22px}}
"""


def build() -> str:
    t = tk.TOKENS
    lines = [
        "/* GENERATED by scripts/gen_widget_css.py from design/tokens.json — edit the tokens. */",
        f"@import url('{tk.FONT_IMPORT}');",
        ":root{",
        f"  --fx-nimbus:{t['surface']['nimbus']};",
        f"  --fx-front:{t['surface']['front']};",
        f"  --fx-line:{t['surface']['line']};",
        f"  --fx-grid:{t['surface']['grid']};",
        f"  --fx-text:{t['text']['primary']};",
        f"  --fx-text-secondary:{t['text']['secondary']};",
        f"  --fx-text-dim:{t['text']['dim']};",
        f"  --fx-beacon:{t['accent']['beacon']};",
    ]
    for name, value in t["regime"].items():
        lines.append(f"  --fx-{name}:{value};")
    lines += [
        f"  --fx-display:{t['font']['display']};",
        f"  --fx-ui:{t['font']['ui']};",
        f"  --fx-mono:{t['font']['mono']};",
        f"  --fx-radius-card:{t['radius']['card']};",
        f"  --fx-radius-pill:{t['radius']['pill']};",
        "}",
    ]
    for regime in t["regime"]:
        lines.append(
            f".fxc-regime-{regime}{{color:var(--fx-{regime})}}"
            f".fxc-bar-fill.fxc-regime-{regime},.fxc-dot.fxc-regime-{regime},"
            f".fxc-ribbon-seg.fxc-regime-{regime}{{background:var(--fx-{regime});color:var(--fx-{regime})}}"
        )
    lines.append("".join(f".fxc-h-{p}{{min-height:{h}px}}" for p, h in BANDS.items()))
    return "\n".join(lines) + "\n" + COMPONENTS


def main() -> None:
    css = build()
    for out in (
        ROOT / "docs" / "widget-tokens.css",
        ROOT / "rust" / "fxradar-serve" / "static" / "widget-tokens.css",
    ):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(css)
        print(f"wrote {out.relative_to(ROOT)} ({len(css)} bytes)")


if __name__ == "__main__":
    main()
