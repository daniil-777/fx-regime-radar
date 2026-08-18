"""FX Regime Radar — dashboard. Reads small artifacts only (CLAUDE.md rule 8); no models here.

Universe switch (FX majors / Crypto majors) and a scenario explorer: an "as of" date that shows the
weather station exactly as it would have looked on that day — every number is filtered/causal, so
replaying history is legitimate and nothing after the chosen date is drawn.
"""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(
    0, str(Path(__file__).resolve().parent)
)  # so `import ui` works under `streamlit run`
import orb  # noqa: E402
import ui  # noqa: E402
from fxradar import narrate  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

st.set_page_config(
    page_title="FX Regime Radar", page_icon="📡", layout="wide", initial_sidebar_state="expanded"
)
ui.inject_css()

REGIME_ORDER = ["calm", "trend", "chop", "crisis"]

# --------------------------------------------------------------------------------------
# sidebar: universe, pair, scenario — and the disclaimer
# --------------------------------------------------------------------------------------
ui.sidebar(DISCLAIMER)
UNI_NAME, UNI, DIRS = ui.universe_selector()
PAIRS = list(UNI.pairs)
DATA_DIR = DIRS["data"]
PRICES_PATH, REGIMES_PATH = DATA_DIR / "prices.parquet", DATA_DIR / "regimes.parquet"
REPORT_PATH, STATUS_PATH = DATA_DIR / "report.json", DATA_DIR / "pipeline_status.json"
OOS_START = pd.Timestamp(UNI.val_start)


def _mtime(path: Path) -> float:
    return os.path.getmtime(path) if path.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_regimes(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_prices(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)[["date", "pair", "close"]]


@st.cache_data(show_spinner=False)
def load_json(path: str, mtime: float) -> dict:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def regime_runs(path: str, mtime: float, pair: str) -> pd.DataFrame:
    """Consecutive same-regime days merged into bands: regime, start, end (light pandas)."""
    r = load_regimes(path, mtime)
    g = r[r["pair"] == pair].sort_values("date").reset_index(drop=True)
    new_run = g["regime"].ne(g["regime"].shift(1)).cumsum()
    runs = g.groupby(new_run).agg(
        regime=("regime", "first"), start=("date", "first"), end=("date", "last")
    )
    runs["end"] = runs["start"].shift(-1).fillna(runs["end"])
    return runs.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def anatomy(
    path_r: str,
    mtime_r: float,
    path_p: str,
    mtime_p: float,
    pair: str,
    oos_start: str,
    ann_days: int,
) -> pd.DataFrame:
    """Out-of-sample regime anatomy for one pair (same definitions as the validation report)."""
    r = load_regimes(path_r, mtime_r)
    p = load_prices(path_p, mtime_p)
    g = r[r["pair"] == pair].merge(p[p["pair"] == pair], on=["date", "pair"]).sort_values("date")
    g["ret"] = np.log(g["close"] / g["close"].shift(1))
    g = g[g["date"] >= pd.Timestamp(oos_start)]
    new_run = g["regime"].ne(g["regime"].shift(1)).cumsum()
    run_len = g.groupby(new_run).agg(regime=("regime", "first"), length=("regime", "size"))
    rows = []
    for regime in REGIME_ORDER:
        rr = g.loc[g["regime"] == regime, "ret"].dropna()
        eq = np.exp(rr.cumsum())
        rows.append(
            {
                "regime": regime,
                "days": int(len(rr)),
                "share %": 100 * len(rr) / max(len(g), 1),
                "mean run (d)": (
                    float(run_len.loc[run_len["regime"] == regime, "length"].mean())
                    if len(rr)
                    else np.nan
                ),
                "ann. vol %": (
                    float(rr.std(ddof=1) * np.sqrt(ann_days) * 100) if len(rr) > 1 else np.nan
                ),
                "mean ret (bp)": float(rr.mean() * 1e4) if len(rr) else np.nan,
                "worst dd %": float((eq / eq.cummax() - 1).min() * 100) if len(rr) else np.nan,
            }
        )
    return pd.DataFrame(rows)


API_URL = os.environ.get("FXRADAR_API_URL", "").rstrip("/")


@st.cache_data(show_spinner=False, ttl=60)
def load_api_latest(api_url: str, pairs: tuple[str, ...]) -> dict:
    """Latest scored state per pair from the Rust service (GET /api/regimes/{pair}); {} on any failure."""
    if not api_url:
        return {}
    import urllib.request

    out: dict = {}
    for p in pairs:
        try:
            with urllib.request.urlopen(f"{api_url}/api/regimes/{p}", timeout=2) as r:
                out[p] = json.loads(r.read())
        except Exception:
            return {}
    return out


if not (REGIMES_PATH.exists() and PRICES_PATH.exists()):
    st.warning(
        f"No artifacts for the {UNI.label} universe yet — run `FXRADAR_UNIVERSE={UNI_NAME} make pipeline`."
    )
    st.stop()

regimes_all = load_regimes(str(REGIMES_PATH), _mtime(REGIMES_PATH))
prices_all = load_prices(str(PRICES_PATH), _mtime(PRICES_PATH))
status = load_json(str(STATUS_PATH), _mtime(STATUS_PATH))
report = load_json(str(REPORT_PATH), _mtime(REPORT_PATH))
latest_date = regimes_all["date"].max()

# ---- scenario explorer: named episodes + free "as of" date ---------------------------------
EPISODES = {"today (latest data)": None}
for p, events in UNI.known_events.items():
    for d, label in events:
        EPISODES[f"{label} — {UNI.display(p)} {d}"] = (pd.Timestamp(d), p)
# deep links: ?universe=crypto&pair=BTC-USD&asof=2022-11-09 (a shareable scenario)
qp = st.query_params if hasattr(st, "query_params") else {}
qp_pair = qp.get("pair") if qp.get("pair") in PAIRS else None
qp_asof = None
try:
    qp_asof = pd.Timestamp(qp.get("asof")) if qp.get("asof") else None
except Exception:
    qp_asof = None
with st.sidebar:
    pair = st.selectbox(
        "Pair", PAIRS, index=PAIRS.index(qp_pair) if qp_pair else 0, format_func=UNI.display
    )
    st.markdown(
        '<div class="fx-muted" style="font-size:0.8rem;margin-top:8px">Scenario explorer</div>',
        unsafe_allow_html=True,
    )
    episode = st.selectbox("Jump to an episode", list(EPISODES), index=0)
    ep = EPISODES[episode]
    default_date = (
        ep[0]
        if ep
        else (
            qp_asof
            if qp_asof is not None and not st.session_state.get("_asof_from_url")
            else latest_date
        )
    ).date()
    if qp_asof is not None:
        st.session_state["_asof_from_url"] = True
    as_of_date = st.date_input(
        "or pick an 'as of' date",
        value=default_date,
        key=f"asof_{UNI_NAME}_{episode}_{qp_asof.date() if qp_asof is not None else ''}",  # new episode/link → fresh widget
        min_value=(regimes_all["date"].min() + pd.Timedelta(days=30)).date(),
        max_value=latest_date.date(),
    )
as_of = min(pd.Timestamp(as_of_date), latest_date)
time_machine = as_of < latest_date
if ep and ep[1] in PAIRS and ep[1] != pair and st.session_state.get("_last_episode") != episode:
    pass  # the user may keep their pair; the episode's pair is only a hint (shown in the label)
st.session_state["_last_episode"] = episode

# everything below sees ONLY data up to `as_of` (all outputs are filtered/causal, so this is honest)
regimes = regimes_all[regimes_all["date"] <= as_of]
prices = prices_all[prices_all["date"] <= as_of]
api_latest = load_api_latest(API_URL, tuple(PAIRS)) if not time_machine else {}
data_through = regimes["date"].max()

# --------------------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------------------
updated = status.get("last_run_utc", "")
right = f'Data through <span class="fx-num">{data_through:%Y-%m-%d}</span>'
if updated and not time_machine:
    right += (
        f' · updated <span class="fx-num">{html.escape(updated[:16].replace("T", " "))} UTC</span>'
    )
if api_latest:
    served = str(next(iter(api_latest.values())).get("served_by", "rust"))
    right += f' <span class="fx-pill" style="font-size:0.65rem;padding:2px 8px;color:{ui.REGIME_COLORS["trend"]};background:{ui.REGIME_COLORS["trend"]}22;border:1px solid {ui.REGIME_COLORS["trend"]}55">served by {html.escape(served)}</span>'
st.markdown(
    f'<div class="fx-header"><div><span class="fx-wordmark">FX Regime Radar</span>'
    f'<span class="fx-sub">{html.escape(UNI.label)} · market weather, updated daily</span></div>'
    f'<div class="fx-right">{right}</div></div>',
    unsafe_allow_html=True,
)
if time_machine:
    st.markdown(
        f'<div class="fx-card" style="border-color:{ui.REGIME_COLORS["chop"]}66;padding:10px 16px;margin-bottom:12px">'
        f'<span style="color:{ui.REGIME_COLORS["chop"]};font-weight:600">Time machine — viewing as of {as_of:%Y-%m-%d}.</span> '
        '<span class="fx-muted">Everything on this page was computable on that day: regimes are filtered (no hindsight), change risk and the siren use only rows up to it, and nothing after the date is drawn. '
        "Narration is the deterministic template. Choose “today” in the sidebar to return.</span></div>",
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------------------
# hero row: one weather card per pair
# --------------------------------------------------------------------------------------
cols = st.columns(len(PAIRS))
for col, p in zip(cols, PAIRS, strict=True):
    gp = regimes[regimes["pair"] == p].sort_values("date")
    if gp.empty:
        with col:
            ui.card(
                f'<span style="font-weight:600">{UNI.display(p)}</span><div class="fx-muted">no data as of this date</div>'
            )
        continue
    latest = gp.iloc[-1]
    if p in api_latest:  # live state from the Rust service (same fields as the parquet row)
        latest = pd.Series(
            {**latest.to_dict(), **{k: v for k, v in api_latest[p].items() if k in latest.index}}
        )
    color = ui.REGIME_COLORS[latest["regime"]]
    closes = prices[prices["pair"] == p].sort_values("date")["close"].tail(20)
    px_fmt = "{:.4f}" if closes.iloc[-1] < 100 else "{:,.0f}"
    if time_machine:
        stats = narrate.build_stats(p, regimes, None, prices)
        narration = {
            "text": narrate.template_narrate(stats),
            "generated_at": f"{as_of:%Y-%m-%d} (replay)",
            "source": "template",
        }
    else:
        narration = report.get(p)
    body = (
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<span style="font-weight:600;font-size:1.05rem">{UNI.display(p)}</span>{ui.regime_pill(latest["regime"], large=True)}</div>'
        f'<div class="fx-muted" style="font-size:0.82rem;margin-bottom:6px">{ui.REGIME_BLURB[latest["regime"]]}</div>'
        f"{ui.confidence_bar(latest['regime_prob'], color)}"
        f'<div class="fx-kv" style="margin-top:6px"><span>day <span class="fx-num">{int(latest["days_in_regime"])}</span> of this regime</span>'
        f'<span>last close <span class="fx-num">{px_fmt.format(closes.iloc[-1])}</span></span></div>'
        f"{ui.sparkline_svg(closes, color)}"
        f'<div class="fx-kv"><span>20-day close</span><span class="fx-num">{(closes.iloc[-1] / closes.iloc[0] - 1) * 100:+.2f}%</span></div>'
        + (
            ui.risk_gauge(latest["change_risk_5d"], list(latest["top_drivers"]))
            if "change_risk_5d" in latest and pd.notna(latest["change_risk_5d"])
            else ""
        )
        + ui.narration(narration)
    )
    with col:
        ui.card(body)

# --------------------------------------------------------------------------------------
# main panel: close with regime bands (cut at as_of)
# --------------------------------------------------------------------------------------
g = prices[prices["pair"] == pair].sort_values("date")
runs = regime_runs(str(REGIMES_PATH), _mtime(REGIMES_PATH), pair)
runs = runs[runs["start"] <= as_of].copy()
runs["end"] = runs["end"].clip(upper=as_of)
legend = " ".join(ui.regime_pill(r) for r in REGIME_ORDER)
sel_g = regimes[regimes["pair"] == pair].sort_values("date")
sel = sel_g.iloc[-1] if len(sel_g) else None
if sel is not None and pair in api_latest:
    sel = pd.Series(
        {**sel.to_dict(), **{k: v for k, v in api_latest[pair].items() if k in sel.index}}
    )
orb_col, title_col = st.columns([1, 7])
with (
    orb_col
):  # the regime orb: a display of the same numbers as the card (regime, change risk, siren)
    if sel is not None:
        orb.render(
            str(sel["regime"]),
            float(sel.get("change_risk_5d", 0.0) or 0.0),
            float(sel.get("anomaly_pct", 0.0) or 0.0),
            size=150,
            pair=pair,
        )
with title_col:
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin:34px 0 -4px 2px">'
        f'<span style="font-weight:600">{UNI.display(pair)} — close with filtered regime bands{" · as of " + as_of.strftime("%Y-%m-%d") if time_machine else ""}</span><span>{legend}</span></div>',
        unsafe_allow_html=True,
    )
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=g["date"],
        y=g["close"],
        mode="lines",
        name="close",
        line=dict(color=ui.TEXT, width=1.1),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y}<extra></extra>",
    )
)
shapes = [
    dict(
        type="rect",
        xref="x",
        yref="paper",
        x0=r.start,
        x1=r.end,
        y0=0,
        y1=1,
        fillcolor=ui.REGIME_COLORS[r.regime],
        opacity=0.28,
        line_width=0,
        layer="below",
    )
    for r in runs.itertuples(index=False)
]
if len(g) and g["date"].min() < OOS_START <= as_of:
    shapes.append(
        dict(
            type="line",
            xref="x",
            yref="paper",
            x0=OOS_START,
            x1=OOS_START,
            y0=0,
            y1=1,
            line=dict(color=ui.MUTED, width=1, dash="dash"),
        )
    )
annotations = (
    [
        dict(
            x=OOS_START,
            y=1.02,
            xref="x",
            yref="paper",
            text="out-of-sample →",
            showarrow=False,
            font=dict(color=ui.MUTED, size=11),
            xanchor="left",
        )
    ]
    if len(g) and g["date"].min() < OOS_START <= as_of
    else []
)
if time_machine:
    shapes.append(
        dict(
            type="line",
            xref="x",
            yref="paper",
            x0=as_of,
            x1=as_of,
            y0=0,
            y1=1,
            line=dict(color=ui.REGIME_COLORS["chop"], width=1.5),
        )
    )
    annotations.append(
        dict(
            x=as_of,
            y=1.02,
            xref="x",
            yref="paper",
            text="as of",
            showarrow=False,
            font=dict(color=ui.REGIME_COLORS["chop"], size=11),
            xanchor="right",
        )
    )
fig.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    shapes=shapes,
    height=430,
    margin=dict(l=40, r=20, t=30, b=40),
    annotations=annotations,
    xaxis=dict(
        rangeselector=dict(
            buttons=[
                dict(count=1, label="1y", step="year", stepmode="backward"),
                dict(count=3, label="3y", step="year", stepmode="backward"),
                dict(step="all", label="max"),
            ],
            bgcolor=ui.SURFACE,
            activecolor=ui.BORDER,
            bordercolor=ui.BORDER,
            font=dict(color=ui.TEXT),
        ),
    ),
    yaxis=dict(
        fixedrange=False,
        type="log" if UNI.name == "crypto" else "linear",
        dtick="D2" if UNI.name == "crypto" else None,
        tickformat=",.5~g",
    ),
    showlegend=False,
)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# --------------------------------------------------------------------------------------
# regime anatomy (out of sample, full history — a property of the model, not of the as-of date)
# --------------------------------------------------------------------------------------
an = anatomy(
    str(REGIMES_PATH),
    _mtime(REGIMES_PATH),
    str(PRICES_PATH),
    _mtime(PRICES_PATH),
    pair,
    UNI.val_start,
    UNI.trading_days,
)
an_html = ui.html_table(
    an,
    {
        "share %": "{:.1f}",
        "mean run (d)": "{:.0f}",
        "ann. vol %": "{:.1f}",
        "mean ret (bp)": "{:+.1f}",
        "worst dd %": "{:.1f}",
    },
)
for rname in REGIME_ORDER:
    an_html = an_html.replace(f"<td>{rname}</td>", f"<td>{ui.regime_pill(rname)}</td>")
ui.card(
    f'<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">Out-of-sample since {html.escape(UNI.val_start)} (full history, not the as-of view) — how each label has behaved once the model could no longer see the data. Regimes describe conditions, not direction.</div>{an_html}',
    title=f"Regime anatomy — {UNI.display(pair)}",
)

# --------------------------------------------------------------------------------------
# anomaly siren
# --------------------------------------------------------------------------------------
if "anomaly_pct" in regimes.columns:
    st.markdown(
        '<div style="font-weight:600;margin:6px 0 8px 2px">Anomaly siren — how unlike a calm day is today?</div>',
        unsafe_allow_html=True,
    )
    scols = st.columns(len(PAIRS))
    for col, p in zip(scols, PAIRS, strict=True):
        gs = regimes[regimes["pair"] == p].sort_values("date")
        if gs.empty:
            continue
        latest = gs.iloc[-1]
        two_years = gs[gs["date"] >= gs["date"].max() - pd.DateOffset(years=2)]
        body = ui.siren_dial(latest["anomaly_pct"], UNI.display(p)) + ui.sparkline_svg(
            two_years["anomaly_pct"], ui.siren_color(latest["anomaly_pct"]), width=300, height=40
        )
        body += (
            '<div class="fx-kv"><span>2-year anomaly percentile</span><span class="fx-num">'
            + f'{two_years["anomaly_pct"].iloc[-1]:.0f}'
            + "</span></div>"
        )
        with col:
            ui.card(body)
    loud = (
        regimes[regimes["pair"] == pair]
        .nlargest(8, "anomaly_score")[["date", "regime", "anomaly_score", "anomaly_pct"]]
        .copy()
    )
    loud["date"] = loud["date"].dt.strftime("%Y-%m-%d")
    loud = loud.rename(columns={"anomaly_score": "score", "anomaly_pct": "percentile"})
    ui.card(
        '<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">The days the autoencoder found hardest to reconstruct — history the model never learnt as "normal". Detection only: nothing here predicts.</div>'
        + ui.html_table(loud, {"score": "{:.2f}", "percentile": "{:.1f}"}),
        title=f"Loudest days in history — {UNI.display(pair)}"
        + (f" (up to {as_of:%Y-%m-%d})" if time_machine else ""),
    )

ui.footer(DISCLAIMER, "· Regimes are filtered (causal) HMM states; see Methodology.")
