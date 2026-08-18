"""Advisor: market stability, regime durability, risk budgets and a grounded Q&A — never a direction."""

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
from fxradar import advisor  # noqa: E402
from fxradar import hmm_model as hm  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

ui.sidebar(DISCLAIMER)
UNI_NAME, UNI, DIRS = ui.universe_selector()
PAIRS = list(UNI.pairs)
DATA = DIRS["data"]
REGIMES_PATH, FEATURES_PATH, PRICES_PATH = (
    DATA / "regimes.parquet",
    DATA / "features.parquet",
    DATA / "prices.parquet",
)


def _mtime(p: Path) -> float:
    return os.path.getmtime(p) if p.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_parquet(path: str, mtime: float, cols: tuple[str, ...] | None = None) -> pd.DataFrame:
    df = pd.read_parquet(path)
    return df[list(cols)] if cols else df


@st.cache_data(show_spinner=False)
def load_diag(models_dir: str, mtime: float) -> dict:
    """Self-transition probability per regime from the saved HMM bundles (for durability)."""
    try:
        bundles = hm.load_bundles(pairs=PAIRS, models_dir=Path(models_dir))  # this universe's pairs
        return {
            p: {b.mapping[i]: float(b.model.transmat_[i, i]) for i in range(hm.N_STATES)}
            for p, b in bundles.items()
        }
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def build_snapshot(
    uni_name: str, mtime_r: float, mtime_f: float, mtime_p: float, as_of: str, diag: dict
) -> dict:
    from fxradar import universes

    r = load_parquet(str(REGIMES_PATH), mtime_r)
    f = load_parquet(str(FEATURES_PATH), mtime_f)
    p = load_parquet(str(PRICES_PATH), mtime_p, ("date", "pair", "close"))
    return advisor.snapshot(
        r, f, p, transmat_diag=diag, as_of=pd.Timestamp(as_of), universe=universes.get(uni_name)
    )


if not (REGIMES_PATH.exists() and FEATURES_PATH.exists()):
    st.warning(
        f"No artifacts for {UNI.label} yet — run `FXRADAR_UNIVERSE={UNI_NAME} make pipeline`."
    )
    st.stop()

regimes_all = load_parquet(str(REGIMES_PATH), _mtime(REGIMES_PATH))
pair, as_of, time_machine, episode = ui.scenario_controls(UNI, PAIRS, regimes_all)
diag = load_diag(str(DIRS["models"]), _mtime(DIRS["models"] / "manifest.json"))
snap = build_snapshot(
    UNI_NAME,
    _mtime(REGIMES_PATH),
    _mtime(FEATURES_PATH),
    _mtime(PRICES_PATH),
    str(as_of.date()),
    diag,
)
markets = snap["markets"]

# ---- header + KPI strip ------------------------------------------------------------------------
st.markdown(
    f'<div class="fx-header"><div><span class="fx-wordmark">Advisor</span>'
    f'<span class="fx-sub">{html.escape(UNI.label)} · how stable, how durable, how much — never which way</span></div>'
    f'<div class="fx-right">as of <span class="fx-num">{html.escape(snap["as_of"])}</span></div></div>',
    unsafe_allow_html=True,
)
if time_machine:
    label = episode if not episode.startswith("today") else f"viewing as of {snap['as_of']}"
    st.markdown(
        f'<div class="fx-card" style="border-color:{ui.REGIME_COLORS["chop"]}66;padding:10px 16px;margin-bottom:12px"><span style="color:{ui.REGIME_COLORS["chop"]};font-weight:600">Time machine — {html.escape(label)}.</span> <span class="fx-muted">All numbers below were computable on {html.escape(snap["as_of"])}.</span></div>',
        unsafe_allow_html=True,
    )
oc = ui.stability_color(snap["overall_stability"])
n_stop = sum(1 for m in markets.values() if m["risk_budget"]["budget"] == 0)
n_crisis = sum(1 for m in markets.values() if m["regime"] == "crisis")
ui.kpi_strip(
    [
        ui.kpi(
            "overall stability",
            f'{snap["overall_stability"]:.0f}<span class="fx-muted" style="font-size:0.9rem">/100</span>',
            snap["overall_word"],
            oc,
        ),
        ui.kpi(
            "markets in crisis",
            str(n_crisis),
            "of " + str(len(markets)),
            ui.REGIME_COLORS["crisis"] if n_crisis else ui.TEXT,
        ),
        ui.kpi(
            "siren stops",
            str(n_stop),
            "markets where the budget is 0",
            ui.REGIME_COLORS["crisis"] if n_stop else ui.TEXT,
        ),
        ui.kpi(
            "avg risk budget",
            f'{100 * sum(m["risk_budget"]["budget"] for m in markets.values()) / max(len(markets), 1):.0f}%',
            "of your normal size",
            ui.TEXT,
        ),
    ]
)

# ---- what this is / is not --------------------------------------------------------------------
st.markdown(
    '<div class="fx-card" style="padding:12px 16px"><span style="font-weight:600">What you get here.</span> '
    '<span class="fx-muted">A stability score (0–100) per market, how long regimes like today\'s usually last, and a <b style="color:#E7ECF4">risk budget</b>: the share of your own normal position size the models justify right now — with the reasons. '
    "What you never get: a direction. No buy, no sell, no “this will go up”. The models describe conditions; sizing is where that is useful, and it is the only place we let them speak.</span></div>",
    unsafe_allow_html=True,
)

# ---- per-market cards ------------------------------------------------------------------------
st.markdown(
    '<div class="fx-section">Markets — stability, durability, risk budget</div>',
    unsafe_allow_html=True,
)
cols = st.columns(max(len(markets), 1))
for col, m in zip(cols, markets.values(), strict=False):
    color = ui.REGIME_COLORS[m["regime"]]
    rb = m["risk_budget"]
    d = m["durability"]
    reasons = "".join(f'<li style="margin:2px 0">{html.escape(r)}</li>' for r in rb["reasons"])
    body = (
        f'<div style="display:flex;justify-content:space-between;align-items:center"><span style="font-weight:600;font-size:1.05rem">{html.escape(m["label"])}</span>{ui.regime_pill(m["regime"])}</div>'
        f'<div style="display:flex;align-items:center;gap:14px;margin-top:6px">{ui.gauge_svg(m["stability"], 110, m["stability_word"])}'
        f'<div style="font-size:0.82rem"><div class="fx-muted">stability</div><div class="fx-num" style="font-size:1.1rem;color:{ui.stability_color(m["stability"])}">{m["stability"]:.0f}/100</div>'
        f'<div class="fx-muted" style="margin-top:6px">confidence {m["regime_prob"]:.0%} · change risk {m["change_risk_5d"]:.0%} · siren {m["anomaly_pct"]:.0f}</div></div></div>'
        f'<div class="fx-kv" style="margin-top:8px"><span>durability</span><span class="fx-num">day {d["days_in_regime"]}'
        + (f' of ~{d["typical_days"]:.0f} typical' if d.get("typical_days") else "")
        + "</span></div>"
        f'<div class="fx-kv" style="margin-top:10px"><span style="font-weight:600">risk budget</span><span class="fx-num" style="font-weight:600;color:{ui.risk_color(1 - rb["budget"]) if rb["budget"] < 1 else ui.REGIME_COLORS["calm"]}">{rb["budget"]:.0%} of normal size</span></div>'
        f'<div class="fx-bar"><div style="width:{100 * rb["budget"]:.1f}%;background:{color}"></div></div>'
        f'<ul class="fx-muted" style="font-size:0.78rem;padding-left:16px;margin:6px 0 0 0">{reasons}</ul>'
        f'<div class="fx-kv" style="margin-top:8px"><span>allocation weight</span><span class="fx-num">{m.get("allocation_weight", 0):.0%}</span></div>'
    )
    with col:
        ui.card(body)

# ---- calculator ------------------------------------------------------------------------------
st.markdown(
    '<div class="fx-section">Turn the budget into a size — a calculator, not a recommendation</div>',
    unsafe_allow_html=True,
)
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    capital = st.number_input(
        "your capital (any currency)", min_value=100.0, value=10_000.0, step=500.0
    )
with c2:
    target_vol = st.number_input(
        "your normal annualised risk (vol target)",
        min_value=0.01,
        max_value=0.5,
        value=advisor.DEFAULT_TARGET_VOL,
        step=0.01,
        format="%.2f",
    )
rows = []
for m in markets.values():
    s = advisor.sizing(capital, target_vol, m["vol_20"], m["risk_budget"]["budget"])
    rows.append(
        {
            "market": m["label"],
            "realised vol": m["vol_20"] * 100,
            "risk budget %": m["risk_budget"]["budget"] * 100,
            "leverage": s["leverage"],
            "notional at full budget": advisor.sizing(capital, target_vol, m["vol_20"], 1.0)[
                "notional"
            ],
            "notional now": s["notional"],
        }
    )
tbl = pd.DataFrame(rows)
with c3:
    ui.card(
        '<div class="fx-muted" style="font-size:0.8rem;margin-bottom:8px">notional = capital × (your vol target ÷ the market\'s realised vol) × risk budget, leverage capped at 2×. It answers “how much”, in either direction — the direction is yours.</div>'
        + ui.html_table(
            tbl,
            {
                "realised vol": "{:.0f}%",
                "risk budget %": "{:.0f}",
                "leverage": "{:.2f}×",
                "notional at full budget": "{:,.0f}",
                "notional now": "{:,.0f}",
            },
        ),
        title="Sizing",
    )

# ---- ask the radar ---------------------------------------------------------------------------
st.markdown('<div class="fx-section">Ask the radar</div>', unsafe_allow_html=True)
q1, q2 = st.columns([3, 1])
with q1:
    question = st.text_input(
        "Ask in plain words",
        placeholder="e.g. how stable is the market right now? how much should I risk in BTC/USD? what does chop mean?",
        key=f"q_{UNI_NAME}",
    )
with q2:
    st.markdown(
        '<div class="fx-muted" style="font-size:0.78rem;margin-top:30px">Answers come only from this page\'s numbers (a JSON snapshot); the assistant never uses news or its own market opinions and never gives a direction. Without an API key it answers from templates.</div>',
        unsafe_allow_html=True,
    )
if question:
    text, source = advisor.answer(question, snap)
    badge_color = ui.REGIME_COLORS["trend"] if source == "llm" else ui.MUTED
    ui.card(
        f'<div style="font-size:0.92rem;line-height:1.55">{html.escape(text)}</div>'
        f'<div class="fx-muted" style="font-size:0.72rem;margin-top:8px"><span class="fx-pill" style="font-size:0.65rem;padding:2px 8px;color:{badge_color};background:{badge_color}22;border:1px solid {badge_color}55">{"AI" if source == "llm" else "auto"}</span> &nbsp;grounded in the snapshot as of {html.escape(snap["as_of"])}</div>'
    )
with st.expander("the snapshot the assistant sees (numbers only)"):
    st.code(
        json.dumps({k: v for k, v in snap.items() if k != "weights"}, indent=1, default=str)[:6000],
        language="json",
    )

ui.footer(DISCLAIMER, "· Risk budgets describe how much, never which way. Not investment advice.")
