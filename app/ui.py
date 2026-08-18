"""Shared UI for the Streamlit app: CSS (fonts, cards, pills), the single Plotly dark template,
and small HTML helpers. Everything visual lives here so pages stay thin (CLAUDE.md design system).
"""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---- design tokens ---------------------------------------------------------------------
BG = "#0B0F17"
SURFACE = "#131A26"
BORDER = "#232D3F"
TEXT = "#E7ECF4"
MUTED = "#8A94A6"
REGIME_COLORS = {"calm": "#34D399", "trend": "#60A5FA", "chop": "#FBBF24", "crisis": "#F87171"}
REGIME_BLURB = {
    "calm": "low volatility, quiet drift",
    "trend": "moderate volatility, persistent direction",
    "chop": "moderate volatility, no direction",
    "crisis": "high volatility, storm conditions",
}
FONT_UI = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
FONT_MONO = "'JetBrains Mono', 'SF Mono', Menlo, monospace"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
#MainMenu, footer, header, [data-testid="stToolbar"], [data-testid="stDecoration"], .stDeployButton {{ display: none !important; visibility: hidden !important; }}
html, body, [data-testid="stAppViewContainer"], .stApp {{ background: {BG} !important; color: {TEXT}; font-family: {FONT_UI}; }}
[data-testid="stSidebar"] {{ background: {SURFACE} !important; border-right: 1px solid {BORDER}; }}
[data-testid="stSidebar"] * {{ font-family: {FONT_UI}; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1280px; }}
h1, h2, h3, h4 {{ font-family: {FONT_UI}; color: {TEXT}; letter-spacing: -0.01em; }}
p, li, label, .stMarkdown {{ color: {TEXT}; }}
.fx-num {{ font-family: {FONT_MONO}; font-variant-numeric: tabular-nums; }}
.fx-muted {{ color: {MUTED}; }}
.fx-card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; padding: 20px; margin-bottom: 14px; }}
.fx-card h3 {{ margin: 0 0 8px 0; font-size: 1.05rem; font-weight: 600; }}
.fx-header {{ display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; }}
.fx-wordmark {{ font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; }}
.fx-sub {{ color: {MUTED}; margin-left: 12px; font-size: 0.95rem; }}
.fx-right {{ color: {MUTED}; font-size: 0.85rem; text-align: right; }}
.fx-pill {{ display: inline-block; padding: 4px 12px; border-radius: 999px; font-weight: 600; font-size: 0.85rem; letter-spacing: 0.02em; text-transform: uppercase; }}
.fx-pill-lg {{ padding: 8px 18px; font-size: 1.15rem; }}
.fx-bar {{ height: 8px; border-radius: 4px; background: {BORDER}; overflow: hidden; margin: 8px 0 4px 0; }}
.fx-bar > div {{ height: 100%; border-radius: 4px; }}
.fx-kv {{ display: flex; justify-content: space-between; font-size: 0.85rem; color: {MUTED}; }}
.fx-table {{ width: 100%; border-collapse: collapse; font-size: 0.86rem; }}
.fx-table th {{ text-align: left; color: {MUTED}; font-weight: 500; padding: 8px 10px; border-bottom: 1px solid {BORDER}; }}
.fx-table td {{ padding: 8px 10px; border-bottom: 1px solid {BORDER}; font-family: {FONT_MONO}; font-variant-numeric: tabular-nums; }}
.fx-table td:first-child {{ font-family: {FONT_UI}; }}
.fx-footer {{ color: {MUTED}; font-size: 0.8rem; margin-top: 28px; padding-top: 12px; border-top: 1px solid {BORDER}; }}
div[data-testid="stSelectbox"] label {{ color: {MUTED}; }}
</style>
"""


def inject_css() -> None:
    """Inject the design system once per page run."""
    st.markdown(CSS, unsafe_allow_html=True)


# ---- Plotly template (defined once, reused everywhere) ---------------------------------
def _register_template() -> None:
    if "fxradar_dark" in pio.templates:
        return
    tpl = go.layout.Template()
    tpl.layout = go.Layout(
        paper_bgcolor=BG,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT_UI, color=TEXT, size=12),
        xaxis=dict(
            gridcolor=BORDER, zeroline=False, linecolor=BORDER, tickfont=dict(family=FONT_MONO)
        ),
        yaxis=dict(
            gridcolor=BORDER, zeroline=False, linecolor=BORDER, tickfont=dict(family=FONT_MONO)
        ),
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=1.05, x=0),
        hoverlabel=dict(
            bgcolor=SURFACE, bordercolor=BORDER, font=dict(family=FONT_MONO, color=TEXT)
        ),
        colorway=[
            TEXT,
            REGIME_COLORS["trend"],
            REGIME_COLORS["calm"],
            REGIME_COLORS["chop"],
            REGIME_COLORS["crisis"],
        ],
    )
    pio.templates["fxradar_dark"] = tpl


_register_template()
PLOTLY_TEMPLATE = "fxradar_dark"


# ---- HTML helpers ----------------------------------------------------------------------
def regime_pill(name: str, large: bool = False) -> str:
    """Coloured pill for a regime name."""
    color = REGIME_COLORS.get(name, MUTED)
    cls = "fx-pill fx-pill-lg" if large else "fx-pill"
    return f'<span class="{cls}" style="background:{color}22;color:{color};border:1px solid {color}55">{html.escape(name)}</span>'


def confidence_bar(p: float, color: str = TEXT, label: str = "confidence") -> str:
    """Horizontal bar for a probability in [0, 1] with a mono-font readout."""
    pct = max(0.0, min(1.0, float(p))) * 100
    return (
        f'<div class="fx-kv"><span>{html.escape(label)}</span><span class="fx-num">{pct:.0f}%</span></div>'
        f'<div class="fx-bar"><div style="width:{pct:.1f}%;background:{color}"></div></div>'
    )


def risk_color(p: float) -> str:
    """Band colour for a change-risk probability: <20 % muted, 20–40 % amber, >40 % crisis red."""
    pct = float(p) * 100
    return MUTED if pct < 20 else (REGIME_COLORS["chop"] if pct <= 40 else REGIME_COLORS["crisis"])


def risk_gauge(p: float, drivers: list[str] | None = None) -> str:
    """Horizontal change-risk gauge with band colour and the top drivers beneath."""
    pct = max(0.0, min(1.0, float(p))) * 100
    color = risk_color(p)
    ticks = "".join(
        f'<div style="position:absolute;left:{t}%;top:-2px;width:1px;height:12px;background:{BORDER}"></div>'
        for t in (20, 40)
    )
    drv = ""
    if drivers:
        drv = f'<div class="fx-muted" style="font-size:0.75rem;margin-top:4px">drivers: {html.escape(", ".join(str(d) for d in drivers))}</div>'
    return (
        f'<div class="fx-kv" style="margin-top:10px"><span>5-day change risk</span><span class="fx-num" style="color:{color}">{pct:.0f}%</span></div>'
        f'<div class="fx-bar" style="position:relative;overflow:visible"><div style="width:{pct:.1f}%;background:{color}"></div>{ticks}</div>'
        f"{drv}"
    )


def siren_color(pct: float) -> str:
    """Anomaly percentile band: muted <90, amber 90–98, crisis red >98."""
    return MUTED if pct < 90 else (REGIME_COLORS["chop"] if pct <= 98 else REGIME_COLORS["crisis"])


def siren_dial(pct: float, label: str) -> str:
    """Compact dial: a ring whose filled arc is the anomaly percentile, coloured by band."""
    pct = max(0.0, min(100.0, float(pct)))
    color = siren_color(pct)
    r, c = 26, 2 * 3.14159 * 26
    dash = c * pct / 100
    return (
        f'<div style="display:flex;align-items:center;gap:14px">'
        f'<svg width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="{r}" fill="none" stroke="{BORDER}" stroke-width="6"/>'
        f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="{color}" stroke-width="6" stroke-linecap="round" stroke-dasharray="{dash:.1f} {c:.1f}" transform="rotate(-90 32 32)"/>'
        f'<text x="32" y="37" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="14" fill="{TEXT}">{pct:.0f}</text></svg>'
        f'<div><div style="font-weight:600">{html.escape(label)}</div><div class="fx-muted" style="font-size:0.8rem">anomaly percentile</div></div></div>'
    )


def narration(entry: dict | None) -> str:
    """Quote-style narration paragraph with a tiny source badge (AI / auto) and its timestamp."""
    if not entry or not entry.get("text"):
        return ""
    ai = entry.get("source") == "llm"
    badge_color = REGIME_COLORS["trend"] if ai else MUTED
    badge = f'<span class="fx-pill" style="font-size:0.65rem;padding:2px 8px;color:{badge_color};background:{badge_color}22;border:1px solid {badge_color}55">{"AI" if ai else "auto"}</span>'
    stamp = str(entry.get("generated_at", ""))
    when = html.escape(
        stamp[:16].replace("T", " ") if "T" in stamp else stamp
    )  # ISO timestamps trimmed to minutes
    return (
        f'<div style="margin-top:12px;padding:10px 12px;border-left:3px solid {BORDER};color:{TEXT};font-size:0.86rem;line-height:1.45">'
        f"{html.escape(entry['text'])}"
        f'<div class="fx-muted" style="font-size:0.72rem;margin-top:6px">{badge} &nbsp;{when} UTC</div></div>'
    )


def card(body_html: str, title: str | None = None) -> None:
    """Render a card (surface, 1px border, 12px radius, 20px padding)."""
    head = f"<h3>{html.escape(title)}</h3>" if title else ""
    st.markdown(f'<div class="fx-card">{head}{body_html}</div>', unsafe_allow_html=True)


def sparkline_svg(values: pd.Series, color: str, width: int = 220, height: int = 44) -> str:
    """Inline SVG sparkline (no Plotly overhead for tiny charts)."""
    v = pd.Series(values, dtype=float).dropna().to_numpy()
    if len(v) < 2:
        return ""
    lo, hi = float(v.min()), float(v.max())
    span = hi - lo if hi > lo else 1.0
    xs = [i * (width - 2) / (len(v) - 1) + 1 for i in range(len(v))]
    ys = [height - 2 - (val - lo) / span * (height - 4) for val in v]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="display:block;margin-top:10px">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" points="{pts}"/>'
        f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="2.4" fill="{color}"/></svg>'
    )


def html_table(df: pd.DataFrame, formats: dict[str, str] | None = None) -> str:
    """Styled HTML table; `formats` maps column -> format spec (e.g. '{:.1f}')."""
    formats = formats or {}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            val = r[c]
            if c in formats and pd.notna(val):
                cells.append(f"<td>{formats[c].format(val)}</td>")
            elif isinstance(val, float) and pd.isna(val):
                cells.append('<td class="fx-muted">–</td>')
            else:
                cells.append(f"<td>{html.escape(str(val))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="fx-table"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def sidebar(disclaimer: str) -> None:
    """Sidebar chrome: wordmark + disclaimer (page-specific widgets are added by the page)."""
    with st.sidebar:
        st.markdown(
            '<div class="fx-wordmark" style="font-size:1.1rem">FX Regime Radar</div>',
            unsafe_allow_html=True,
        )
        st.caption(disclaimer)


def footer(disclaimer: str, extra: str = "") -> None:
    st.markdown(
        f'<div class="fx-footer">{html.escape(disclaimer)} {extra}</div>', unsafe_allow_html=True
    )


def available_universes() -> list[str]:
    """Universes whose artifacts exist on disk (fx first)."""
    from fxradar import config, universes

    out = [
        n
        for n in universes.UNIVERSES
        if (config.universe_dirs(n)["data"] / "regimes.parquet").exists()
    ]
    return out or ["fx"]


def universe_selector() -> tuple[str, object, dict]:
    """Sidebar universe switch shared by every page: returns (name, Universe, dirs). Persisted in
    session state so pages agree; the FX universe keeps the repository default paths."""
    from fxradar import config, universes

    names = available_universes()
    # deep-link support: ?universe=crypto seeds the selection once (shareable scenario links)
    qp = st.query_params.get("universe") if hasattr(st, "query_params") else None
    if qp in names and not st.session_state.get("_universe_from_url"):
        st.session_state["universe_select"] = qp
        st.session_state["_universe_from_url"] = True
    current = st.session_state.get("universe", names[0])
    if current not in names:
        current = names[0]
    with st.sidebar:
        label = st.selectbox(
            "Universe",
            names,
            index=names.index(current),
            format_func=lambda n: universes.get(n).label,
            key="universe_select",
        )
    st.session_state["universe"] = label
    return label, universes.get(label), config.universe_dirs(label)
