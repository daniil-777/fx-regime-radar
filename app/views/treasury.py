"""Treasury: exposure in, traffic light + money-at-risk out. Arithmetic on the artifact only."""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar import treasury  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

ui.sidebar(DISCLAIMER)
PATH = treasury.PATH
LIGHT_WORD = {"hedge": "HEDGE", "ladder": "LADDER", "wait": "WAIT"}
LIGHT_MEANING = {
    "hedge": treasury.TEMPLATES["meaning_hedge"],
    "ladder": treasury.TEMPLATES["meaning_ladder"],
    "wait": treasury.TEMPLATES["meaning_wait"],
}
SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}


@st.cache_data(show_spinner=False)
def load_artifact(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text())


def light_color(light: str) -> str:
    return ui.REGIME_COLORS[treasury.LIGHT_COLOR_REGIME[light]]


if not PATH.exists():
    ui.card(
        "No treasury_risk.json yet — run <code>make pipeline</code> (or "
        "<code>python -m fxradar.treasury</code>) to build the regime-conditional risk table.",
        title="Treasury",
    )
    ui.footer(DISCLAIMER)
    st.stop()

art = load_artifact(str(PATH), os.path.getmtime(PATH))
pairs = list(art["pairs"])
fx = art["fx"]

st.markdown(
    f'<div class="fx-header"><div><span class="fx-wordmark">Treasury</span>'
    f'<span class="fx-sub">hedge · wait · ladder — how large the move could be, never which way</span></div>'
    f'<div class="fx-right">as of <span class="fx-num">{html.escape(art["as_of"])}</span></div></div>',
    unsafe_allow_html=True,
)

# ---- inputs ---------------------------------------------------------------------------------
c1, c2, c3, c4, c5, c6 = st.columns([1.4, 0.8, 1, 1, 0.9, 0.8])
with c1:
    amount = st.number_input("exposure amount", min_value=1000.0, value=800_000.0, step=50_000.0)
with c2:
    ccy = st.selectbox("currency", ["EUR", "USD", "GBP", "CHF"], index=0)
with c3:
    suggested = treasury.SUGGESTED_PAIR.get(ccy, pairs[0])
    pair = st.selectbox(
        "pair (risk proxy)", pairs, index=pairs.index(suggested) if suggested in pairs else 0
    )
with c4:
    weeks = st.slider("horizon (weeks)", min_value=1, max_value=12, value=1)
with c5:
    home = st.selectbox("home currency", ["CHF", "EUR", "USD", "GBP"], index=0)
with c6:
    level = st.selectbox("level", ["99", "95"], index=0)

d = art["pairs"][pair]
regime = d["current_regime"]
cell = d["table"][regime]
light = d["light"]
color = light_color(light)
var_h = treasury.money_at_risk(amount, ccy, cell[f"var_{level}"], weeks, home, fx)
es_h = treasury.money_at_risk(amount, ccy, cell[f"es_{level}"], weeks, home, fx)
amount_home = treasury.round_sig(treasury.convert(amount, ccy, home, fx), 3)
cost_line = treasury.cost_of_waiting_line(amount, ccy, cell["es_99"], home, fx, regime)
fallback = cell.get("fallback", False)

# ---- the light + the price tag ----------------------------------------------------------------
left, right = st.columns([1, 1.6])
with left:
    ui.card(
        f'<div style="display:flex;align-items:center;gap:14px">'
        f'<span style="display:inline-block;width:22px;height:22px;border-radius:50%;background:{color};box-shadow:0 0 14px {color}88"></span>'
        f'<span style="font-size:2.2rem;font-weight:700;letter-spacing:0.04em;color:{color}">{LIGHT_WORD[light]}</span></div>'
        f'<div style="margin-top:8px;font-size:0.9rem;line-height:1.5">{html.escape(d["light_reason"])}</div>'
        f'<div class="fx-kv" style="margin-top:10px"><span>regime on {html.escape(pair)}</span><span>{ui.regime_pill(regime)} '
        f'<span class="fx-num">{d["regime_prob"]:.0%}</span> · day {d["days_in_regime"]}</span></div>',
        title="The light",
    )
with right:
    tiles = [
        ui.kpi(
            f"VaR {level}% · {weeks} wk",
            f"{home} {var_h:,.0f}",
            f"{100 * treasury.scale_to_horizon(cell[f'var_{level}'], weeks):.1f}% of the exposure",
            ui.TEXT,
        ),
        ui.kpi(
            f"ES {level}% · {weeks} wk",
            f"{home} {es_h:,.0f}",
            f"{100 * treasury.scale_to_horizon(cell[f'es_{level}'], weeks):.1f}% of the exposure",
            color,
        ),
        ui.kpi(
            "exposure in home currency",
            f"{home} {amount_home:,.0f}",
            f"{SYMBOL[ccy]}{amount:,.0f} at the latest close",
            ui.TEXT,
        ),
    ]
    ui.kpi_strip(tiles)
    note = (
        f' <span style="color:{ui.REGIME_COLORS["chop"]}">({html.escape(treasury.TEMPLATES["fallback_note"].format(min_n=art.get("min_windows", 30)))})</span>'
        if fallback
        else ""
    )
    ui.card(
        f'<div style="font-size:1.0rem;font-weight:600;line-height:1.5">{html.escape(cost_line)}</div>'
        f'<div class="fx-muted" style="font-size:0.8rem;margin-top:8px">1-week numbers come from {cell["n"]} train-era windows labelled '
        f"<b>{html.escape(regime)}</b> at the window start{note}. Horizons beyond 1 week use square-root-of-time scaling, an approximation. "
        f"VaR/ES are quantiles of the ABSOLUTE 5-day move: a receivable and a payable are both hurt by an adverse move, and we take no view on the sign. "
        f"Conversion at the latest close ({html.escape(pair)} {fx.get(pair, float('nan')):.4f}). "
        f"This page does no modelling: it multiplies artifact numbers by your inputs.</div>",
        title="Cost of waiting",
    )

# ---- what the light means + inputs used -------------------------------------------------------
m1, m2 = st.columns([1, 1])
with m1:
    items = "".join(
        f'<div class="fx-kv" style="margin:4px 0"><span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{light_color(k)};margin-right:8px"></span>'
        f'<b style="color:{light_color(k)}">{LIGHT_WORD[k]}</b></span><span style="text-align:right;max-width:70%">{html.escape(v)}</span></div>'
        for k, v in LIGHT_MEANING.items()
    )
    ui.card(
        items
        + '<div class="fx-muted" style="font-size:0.76rem;margin-top:8px">A rule table on published numbers, not a recommendation for your situation. The sign of the move is never modelled.</div>',
        title="What the light means",
    )
with m2:
    inp, th = d["inputs"], art["thresholds"]

    def _fmt(v, pct=False):
        if v is None:
            return '<span class="fx-muted">n/a</span>'
        return f"{float(v):.0%}" if pct else html.escape(str(v))

    rows = [
        ("change risk (5d)", _fmt(inp.get("change_risk_5d"), True)),
        (
            "interval on change risk",
            (
                f'{_fmt(inp.get("risk_lo"), True)} – {_fmt(inp.get("risk_hi"), True)}'
                if inp.get("risk_lo") is not None
                else _fmt(None)
            ),
        ),
        ("model agreement", _fmt(inp.get("agreement"))),
        ("consensus", _fmt(inp.get("consensus_text"))),
        (
            "next scheduled event",
            (
                f'{_fmt(inp.get("next_event"))} in {_fmt(inp.get("days_to_next_event"))} trading days'
                if inp.get("days_to_next_event") is not None
                else _fmt(None)
            ),
        ),
        (
            "thresholds (train era)",
            f'risk ≥ {th["high_risk"]:.0%} high · < {th["low_risk"]:.0%} low · width ≥ {th["wide"]:.2f} wide · < {th["narrow"]:.2f} narrow · event within {th["event_window_days"]} d',
        ),
    ]
    ui.card(
        "".join(
            f'<div class="fx-kv" style="margin:4px 0"><span>{html.escape(k)}</span><span class="fx-num" style="text-align:right;max-width:65%">{v}</span></div>'
            for k, v in rows
        ),
        title="Inputs the rule saw",
    )

# ---- per-regime conditioning table -------------------------------------------------------------
st.markdown(
    f'<div class="fx-section">1-week move by regime — {html.escape(pair)}, train era ≤ {html.escape(art["train_end"])}</div>',
    unsafe_allow_html=True,
)
tbl_rows = []
for r in treasury.REGIMES:
    c = d["table"][r]
    tbl_rows.append(
        {
            "regime": ui.regime_pill(r) + (" ·" if r == regime else ""),
            "n windows": c["n"],
            "VaR 95": f"{100 * c['var_95']:.1f}%",
            "ES 95": f"{100 * c['es_95']:.1f}%",
            "VaR 99": f"{100 * c['var_99']:.1f}%",
            "ES 99": f"{100 * c['es_99']:.1f}%",
            f"ES {level}% on your exposure ({home}, {weeks} wk)": f"{treasury.money_at_risk(amount, ccy, c[f'es_{level}'], weeks, home, fx):,.0f}",
            "note": "unconditional fallback" if c.get("fallback") else "",
        }
    )
u = d["unconditional"]
tbl_rows.append(
    {
        "regime": "all regimes",
        "n windows": u["n"],
        "VaR 95": f"{100 * u['var_95']:.1f}%",
        "ES 95": f"{100 * u['es_95']:.1f}%",
        "VaR 99": f"{100 * u['var_99']:.1f}%",
        "ES 99": f"{100 * u['es_99']:.1f}%",
        f"ES {level}% on your exposure ({home}, {weeks} wk)": f"{treasury.money_at_risk(amount, ccy, u[f'es_{level}'], weeks, home, fx):,.0f}",
        "note": "for reference only — never the headline",
    }
)
tbl = pd.DataFrame(tbl_rows)
head = "".join(f"<th>{html.escape(str(c))}</th>" for c in tbl.columns)
body = "".join(
    "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in tbl.itertuples(index=False)
)
ui.card(
    f'<div class="fx-table-wrap"><table class="fx-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    f'<div class="fx-muted" style="font-size:0.76rem;margin-top:8px">Historical simulation over {html.escape(art["method"])}. Regime = the filtered HMM state on the day the window starts. Today\'s regime is marked with a dot.</div>'
)

ui.footer(
    DISCLAIMER,
    "· Risk information about the size of moves, never a direction or a suitability judgement.",
)
