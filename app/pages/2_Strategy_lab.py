"""Strategy lab: net equity curves, drawdowns, metrics, per-regime attribution — reads artifacts only."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar.config import DATA_DIR, DISCLAIMER, TEST_START, VAL_START  # noqa: E402

st.set_page_config(page_title="Strategy lab — FX Regime Radar", page_icon="📡", layout="wide")
ui.inject_css()
ui.sidebar(DISCLAIMER)

BACKTESTS = DATA_DIR / "backtests.parquet"
METRICS = DATA_DIR / "strategy_metrics.json"
ATTRIB = DATA_DIR / "strategy_attribution.json"
NAMES = ["S1_trend", "S2_meanrev", "S3_regime_gate", "BLEND"]
LINE = {
    "S1_trend": ui.REGIME_COLORS["trend"],
    "S2_meanrev": ui.REGIME_COLORS["chop"],
    "S3_regime_gate": ui.REGIME_COLORS["calm"],
    "BLEND": ui.TEXT,
}


def _mtime(p: Path) -> float:
    return os.path.getmtime(p) if p.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_curves(mtime: float) -> pd.DataFrame:
    b = pd.read_parquet(BACKTESTS)
    b = b[b["strategy"].isin(NAMES)]
    pooled = b.groupby(["date", "strategy"])["ret_net"].mean().unstack()
    return pooled


@st.cache_data(show_spinner=False)
def load_metrics(mtime: float) -> pd.DataFrame:
    return pd.DataFrame(json.loads(METRICS.read_text()))


@st.cache_data(show_spinner=False)
def load_attrib(mtime: float) -> dict:
    return json.loads(ATTRIB.read_text())


st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Strategy lab</span>'
    '<span class="fx-sub">do the signals survive costs?</span></div></div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="fx-card" style="border-color:{ui.REGIME_COLORS["chop"]}66;padding:12px 16px">'
    f'<span style="color:{ui.REGIME_COLORS["chop"]};font-weight:600">Research demonstration on daily data — not a live trading system.</span> '
    '<span class="fx-muted">Positions come from pre-declared mechanical rules and the regime gate; the overlay only decides how much risk to take. '
    "Every number is net of volatility-scaled costs with the lag law applied inside the engine. Test period 2019+ was scored once and frozen.</span></div>",
    unsafe_allow_html=True,
)

if not (BACKTESTS.exists() and METRICS.exists() and ATTRIB.exists()):
    st.warning("Strategy artifacts not built yet — run `python -m fxradar.strategies`.")
    st.stop()

curves = load_curves(_mtime(BACKTESTS))
metrics = load_metrics(_mtime(METRICS))
attrib = load_attrib(_mtime(ATTRIB))

# ---- equity + drawdown -----------------------------------------------------------------
equity = (1 + curves).cumprod()
dd = equity / equity.cummax() - 1
fig = go.Figure()
for n in NAMES:
    if n in equity:
        fig.add_trace(
            go.Scatter(
                x=equity.index,
                y=equity[n],
                name=n,
                line=dict(color=LINE[n], width=2 if n == "BLEND" else 1.2),
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:.3f}<extra>" + n + "</extra>",
            )
        )
for x, label in [(VAL_START, "validation →"), (TEST_START, "test (frozen) →")]:
    fig.add_vline(x=pd.Timestamp(x), line=dict(color=ui.MUTED, dash="dash", width=1))
    fig.add_annotation(
        x=pd.Timestamp(x),
        y=1.0,
        yref="paper",
        text=label,
        showarrow=False,
        xanchor="left",
        font=dict(color=ui.MUTED, size=11),
    )
fig.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    height=380,
    margin=dict(l=40, r=20, t=30, b=40),
    showlegend=True,
    yaxis_title="net equity (all pairs equal weight)",
)
st.markdown(
    '<div style="font-weight:600;margin:6px 0 -4px 2px">Net equity — S1 trend · S2 mean reversion · S3 regime gate · blend</div>',
    unsafe_allow_html=True,
)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

fig2 = go.Figure()
for n in NAMES:
    if n in dd:
        fig2.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd[n],
                name=n,
                line=dict(color=LINE[n], width=1),
                fill="tozeroy" if n == "BLEND" else None,
                fillcolor="rgba(231,236,244,0.08)",
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1%}<extra>" + n + "</extra>",
            )
        )
fig2.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    height=240,
    margin=dict(l=40, r=20, t=20, b=40),
    showlegend=False,
    yaxis=dict(tickformat=".0%", title="drawdown"),
)
st.markdown(
    '<div style="font-weight:600;margin:6px 0 -4px 2px">Drawdowns</div>', unsafe_allow_html=True
)
st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})

# ---- metrics table (test, gross vs net) --------------------------------------------
split = st.radio("period", ["test", "val", "train", "all"], horizontal=True, index=0)
m = metrics[metrics["split"] == split].copy()
m = m[m["strategy"].isin(NAMES)]
tbl = m[
    [
        "strategy",
        "kind",
        "cagr",
        "ann_vol",
        "sharpe",
        "max_drawdown",
        "turnover_ann",
        "cost_drag",
        "hit_rate",
    ]
].rename(
    columns={
        "cagr": "CAGR",
        "ann_vol": "ann. vol",
        "sharpe": "Sharpe",
        "max_drawdown": "max DD",
        "turnover_ann": "turnover/yr",
        "cost_drag": "cost drag",
        "hit_rate": "hit rate",
    }
)
for c in ["CAGR", "ann. vol", "max DD", "cost drag", "hit rate"]:
    tbl[c] = tbl[c] * 100
ui.card(
    '<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">Gross and net always side by side. Percent columns in %, Sharpe annualised, turnover in units of position per year.</div>'
    + ui.html_table(
        tbl,
        {
            "CAGR": "{:+.1f}",
            "ann. vol": "{:.1f}",
            "Sharpe": "{:+.2f}",
            "max DD": "{:.1f}",
            "turnover/yr": "{:.0f}",
            "cost drag": "{:.1f}",
            "hit rate": "{:.0f}",
        },
    ),
    title=f"Metrics — {split}, all pairs equal weight",
)

# ---- per-regime attribution + correlation ------------------------------------------
att = pd.DataFrame(attrib["attribution_test"])
piv = (
    att.pivot(index="strategy", columns="regime", values="sharpe_net")[
        ["calm", "trend", "chop", "crisis"]
    ]
    .reindex(NAMES)
    .reset_index()
)
corr = pd.DataFrame(attrib["corr_test"]).round(2).reset_index().rename(columns={"index": ""})
c1, c2 = st.columns([3, 2])
with c1:
    ui.card(
        '<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">Net Sharpe of each strategy inside each regime (regime known when the position was decided), test period. Small samples per regime: directional, not significant.</div>'
        + ui.html_table(
            piv, {"calm": "{:+.2f}", "trend": "{:+.2f}", "chop": "{:+.2f}", "crisis": "{:+.2f}"}
        ),
        title="Per-regime attribution (test)",
    )
with c2:
    ui.card(
        '<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">Correlation of net daily returns (test). Low correlation is what makes a blend worth more than its parts.</div>'
        + ui.html_table(corr, {c: "{:+.2f}" for c in corr.columns if c}),
        title="Strategy correlation (test)",
    )

# ---- stress panel ------------------------------------------------------------------------
STRESS = DATA_DIR / "stress_tests.json"
if STRESS.exists():
    stress = json.loads(STRESS.read_text())
    st.markdown(
        '<div style="font-weight:600;margin:10px 0 6px 2px">Stress lab — replays, breakeven cost, bootstrapped drawdowns</div>',
        unsafe_allow_html=True,
    )
    s1, s2 = st.columns([3, 2])
    with s1:
        rep = pd.DataFrame(stress["replays"])
        rep_tbl = rep.assign(
            **{
                "return": rep["return"] * 100,
                "max DD": rep["max_drawdown"] * 100,
                "worst day": rep["worst_day"] * 100,
            }
        )[["window", "strategy", "return", "max DD", "worst day"]]
        be = pd.DataFrame(stress["breakeven"])[
            ["strategy", "gross_sharpe", "sharpe_at_1x", "breakeven_cost_mult"]
        ].rename(
            columns={
                "gross_sharpe": "gross Sharpe",
                "sharpe_at_1x": "net Sharpe",
                "breakeven_cost_mult": "breakeven cost ×",
            }
        )
        ui.card(
            '<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">Breakeven cost multiplier — the multiple of the cost model at which net Sharpe crosses zero (0 = no edge even at zero cost).</div>'
            + ui.html_table(
                be,
                {"gross Sharpe": "{:+.2f}", "net Sharpe": "{:+.2f}", "breakeven cost ×": "{:.2f}"},
            )
            + '<div class="fx-muted" style="font-size:0.82rem;margin:14px 0 8px 0">Historical replays (net, all pairs): SNB week, COVID crash, 2022 — %.</div>'
            + ui.html_table(
                rep_tbl, {"return": "{:+.1f}", "max DD": "{:.1f}", "worst day": "{:.2f}"}
            ),
            title="Breakeven cost and replays",
        )
    with s2:
        boot = pd.DataFrame(stress["bootstrap"]).rename(
            columns={
                "median_max_dd": "median",
                "p5_pain_max_dd": "5th pct pain",
                "p95_max_dd": "95th pct",
            }
        )
        for c in ["median", "5th pct pain", "95th pct"]:
            boot[c] = boot[c] * 100
        png = Path(__file__).resolve().parents[2] / "reports" / "stress_bootstrap_dd.png"
        ui.card(
            '<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">One-year max drawdown, 1 000 block-bootstrapped paths (20-day blocks), %.</div>'
            + ui.html_table(
                boot, {"median": "{:.1f}", "5th pct pain": "{:.1f}", "95th pct": "{:.1f}"}
            ),
            title="Bootstrapped drawdowns",
        )
        if png.exists():
            st.image(str(png), width="stretch")
    st.markdown(
        f'<div class="fx-muted" style="font-size:0.82rem;margin:4px 2px 0 2px">{stress["verdicts"]["costs"]}</div>',
        unsafe_allow_html=True,
    )

ui.footer(DISCLAIMER, "· Research demonstration on daily data — not a live trading system.")
