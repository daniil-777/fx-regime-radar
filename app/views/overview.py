"""Overview — the condition banner. Reads small artifacts only (CLAUDE.md rule 8); no models here.

The full market state readable in three seconds from two metres: the regime word huge in its
colour, one metrics line (change risk ± band, siren), the quiet 90-day risk trace, the three-dot
consensus; then the three decisions a treasurer makes with it (next scheduled storm, treasury light,
interval coverage), the trust strip, and one compact weather card per market. The detailed charts
live on the Pairs page. Universe switch and the scenario explorer ("as of" date) sit in the sidebar;
every number is filtered/causal, so replaying history is legitimate and nothing after the chosen
date is drawn.
"""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # app/ on the path: `import ui`
import ui  # noqa: E402
from fxradar import config, narrate  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

REGIME_ORDER = ["calm", "trend", "chop", "crisis"]
EVENT_LABEL = {
    "SNB": "SNB rate decision",
    "ECB": "ECB rate decision",
    "FOMC": "FOMC rate decision",
    "BOE": "BoE rate decision",
    "NFP": "US payrolls",
    "CPI": "US CPI print",
}

ui.sidebar(DISCLAIMER)
UNI_NAME, UNI, DIRS = ui.universe_selector()
PAIRS = list(UNI.pairs)
DATA_DIR = DIRS["data"]
PRICES_PATH, REGIMES_PATH = DATA_DIR / "prices.parquet", DATA_DIR / "regimes.parquet"
REPORT_PATH, STATUS_PATH = DATA_DIR / "report.json", DATA_DIR / "pipeline_status.json"


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
def load_events(path: str, mtime: float) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=["date", "type", "source"])
    ev = pd.read_csv(p)
    ev["date"] = pd.to_datetime(ev["date"])
    return ev


@st.cache_data(show_spinner=False)
def load_api_latest(api_url: str, pairs: tuple[str, ...]) -> dict:
    """Newest row per pair from the Rust service, if one is configured and answering (1 s budget)."""
    if not api_url:
        return {}
    import urllib.request

    out = {}
    for p in pairs:
        try:
            with urllib.request.urlopen(f"{api_url.rstrip('/')}/api/regimes/{p}", timeout=1) as r:
                out[p] = json.loads(r.read())
        except Exception:  # noqa: BLE001 — any failure means "use the artifacts"
            return {}
    return out


API_URL = os.environ.get("FXRADAR_API_URL", "")

if not (REGIMES_PATH.exists() and PRICES_PATH.exists()):
    ui.state(
        f"No artifacts for the {UNI.label} universe yet.",
        "The dashboard reads files the pipeline writes; none exist for this universe.",
        f"Run `FXRADAR_UNIVERSE={UNI_NAME} make pipeline` once, then reload.",
    )
    st.stop()

regimes_all = load_regimes(str(REGIMES_PATH), _mtime(REGIMES_PATH))
prices_all = load_prices(str(PRICES_PATH), _mtime(PRICES_PATH))
status = load_json(str(STATUS_PATH), _mtime(STATUS_PATH))
drift_status = load_json(str(DATA_DIR / "status.json"), _mtime(DATA_DIR / "status.json"))
report = load_json(str(REPORT_PATH), _mtime(REPORT_PATH))
live = load_json(str(DATA_DIR / "live_record.json"), _mtime(DATA_DIR / "live_record.json"))
# the treasury table is an FX artifact (francs); other FX universes fall back to it for the pairs it covers
_tre_path = DATA_DIR / "treasury_risk.json"
if not _tre_path.exists() and UNI.trading_days == 252:
    _tre_path = config.ROOT / "data" / "treasury_risk.json"
treasury = load_json(str(_tre_path), _mtime(_tre_path))
coverage = load_json(
    str(DATA_DIR / "conformal_coverage.json"), _mtime(DATA_DIR / "conformal_coverage.json")
)
# the scheduled-decision calendar is macro, not per universe: fall back to the FX copy
_ev_path = DATA_DIR / "events.csv"
if not _ev_path.exists():
    _ev_path = config.ROOT / "data" / "events.csv"
events = load_events(str(_ev_path), _mtime(_ev_path))

# ---- scenario explorer (shared with the other pages) ------------------------------------------
pair, as_of, time_machine, episode = ui.scenario_controls(UNI, PAIRS, regimes_all)
regimes = regimes_all[regimes_all["date"] <= as_of]
prices = prices_all[prices_all["date"] <= as_of]
api_latest = load_api_latest(API_URL, tuple(PAIRS)) if not time_machine else {}
data_through = regimes["date"].max()

# --------------------------------------------------------------------------------------
# header: wordmark · live dot · data through · drift badge
# --------------------------------------------------------------------------------------
days_live = int(live.get("days_recorded", 0) or 0)
live_label = f"live · day {days_live}" if days_live else "live · first run pending"
right = f'data through <span class="fx-num">{data_through:%Y-%m-%d}</span>'
if drift_status and not time_machine:
    right += " " + ui.stale_badge(drift_status)
if api_latest:
    served = str(next(iter(api_latest.values())).get("served_by", "rust"))
    right += f' <span class="fx-pill" style="font-size:0.65rem;padding:2px 8px;color:{ui.REGIME_COLORS["trend"]};background:{ui.alpha(ui.REGIME_COLORS["trend"], 0.12)};border:1px solid {ui.alpha(ui.REGIME_COLORS["trend"], 0.35)}">served by {html.escape(served)}</span>'
st.markdown(
    f'<div class="fx-header"><div style="display:flex;align-items:baseline;gap:18px;flex-wrap:wrap">'
    f'<span class="fx-wordmark">FX regime radar</span>'
    f'<span class="fx-sub">{html.escape(UNI.label)} · market weather, updated daily</span>'
    f"{'' if time_machine else ui.live_dot(live_label)}</div>"
    f'<div class="fx-right">{right}</div></div>',
    unsafe_allow_html=True,
)
ui.mobile_bar(UNI, PAIRS)  # phones: universe + market pills (hidden on desktop)
if time_machine:
    st.markdown(
        f'<div class="fx-card" style="border-color:{ui.alpha(ui.REGIME_COLORS["chop"], 0.4)};padding:10px 16px;margin-bottom:12px">'
        f'<span style="color:{ui.REGIME_COLORS["chop"]};font-weight:500">Time machine — viewing as of {as_of:%Y-%m-%d}.</span> '
        '<span class="fx-muted">Everything on this page was computable on that day: regimes are filtered (no hindsight), change risk and the siren use only rows up to it, and nothing after the date is drawn. '
        "Choose “today” in the sidebar to return.</span></div>",
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------------------
# signature 1: the condition banner (selected pair)
# --------------------------------------------------------------------------------------
sel_g = regimes[regimes["pair"] == pair].sort_values("date")
if sel_g.empty:
    ui.state(
        "No data for this pair as of this date.",
        "The artifacts start later than the chosen day.",
        "Move the as-of date forward in the sidebar.",
    )
    st.stop()
sel = sel_g.iloc[-1]
if pair in api_latest:
    sel = pd.Series(
        {**sel.to_dict(), **{k: v for k, v in api_latest[pair].items() if k in sel.index}}
    )
trail = sel_g.tail(90)
trace = ui.risk_trace_svg(
    trail["change_risk_5d"] if "change_risk_5d" in trail else pd.Series(dtype=float),
    trail["risk_lo"] if "risk_lo" in trail else None,
    trail["risk_hi"] if "risk_hi" in trail else None,
    ui.REGIME_COLORS[sel["regime"]],
)
ui.condition_banner(
    UNI.display(pair),
    f"{data_through:%a %d %b %Y}",
    str(sel["regime"]),
    sel.get("change_risk_5d"),
    sel.get("risk_lo"),
    sel.get("risk_hi"),
    sel.get("anomaly_pct"),
    sel.get("agreement"),
    {k: sel.get(k) for k in ("vote_hmm", "vote_bocpd", "vote_vol")},
    trace,
    eyebrow_extra=" · time machine" if time_machine else "",
)
if trace:
    st.markdown(
        '<div class="fx-dim" style="font-size:0.72rem;margin:-6px 0 6px 0">90-day change-risk trace · shaded = 90 % conformal band · regime word and dot carry the state, colour only repeats it</div>',
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------------------
# signature 2: the trust strip (never below the fold)
# --------------------------------------------------------------------------------------
ui.trust_strip(DATA_DIR)

# --------------------------------------------------------------------------------------
# the three decisions: next scheduled storm · treasury light · interval coverage
# --------------------------------------------------------------------------------------
c1, c2, c3 = st.columns(3)
with c1:
    nxt = events[events["date"] > as_of].sort_values("date").head(1) if len(events) else events
    if len(nxt):
        e = nxt.iloc[0]
        days = int((e["date"] - as_of).days)
        tone = ui.REGIME_COLORS["chop"] if days <= 5 else ui.MUTED
        ui.card(
            f'<div style="font-size:1.05rem;font-weight:500">{html.escape(EVENT_LABEL.get(str(e["type"]), str(e["type"])))}</div>'
            f'<div class="fx-num" style="font-size:0.82rem;color:{tone};margin-top:3px">in {days} day{"s" if days != 1 else ""} · {e["date"]:%a %d %b}</div>'
            '<div class="fx-dim" style="font-size:0.74rem;margin-top:4px">scheduled dates only — surprises have no calendar</div>',
            title="next scheduled storm",
        )
    else:
        ui.card(
            '<div class="fx-muted">No event calendar loaded.</div><div class="fx-dim" style="font-size:0.74rem;margin-top:4px">data/events.csv is written by the calendar step (phase 23).</div>',
            title="next scheduled storm",
        )
with c2:
    tp = (treasury.get("pairs") or {}).get(pair, {})
    fx = treasury.get("fx") or {}
    light = str(tp.get("light", "")) if not time_machine else ""
    if light:
        lc = {
            "hedge": ui.REGIME_COLORS["crisis"],
            "ladder": ui.REGIME_COLORS["chop"],
            "wait": ui.REGIME_COLORS["calm"],
        }.get(light, ui.MUTED)
        reg = str(tp.get("current_regime", sel["regime"]))
        cell = (tp.get("table") or {}).get(reg, {})
        es99 = cell.get("es_99")
        # €500k for 4 weeks: the mockup's example, √t scaling (documented approximation)
        amount, weeks = 500_000, 4
        rate = fx.get("EURCHF") or 1.0
        chf = amount * float(es99) * (weeks**0.5) * float(rate) if es99 else None
        ui.card(
            f'<div style="display:flex;align-items:center;gap:8px;font-size:1.05rem;font-weight:500;text-transform:capitalize">'
            f'<span class="fx-pip" style="background:{lc};border-color:{lc}"></span>{html.escape(light)}</div>'
            + (
                f'<div class="fx-num fx-muted" style="font-size:0.82rem;margin-top:3px">waiting risk ≈ CHF {chf:,.0f} <span class="fx-dim">(99% ES · €500k · 4 weeks)</span></div>'
                if chf
                else ""
            )
            + f'<div class="fx-dim fx-clamp2" style="font-size:0.74rem;margin-top:4px" title="{html.escape(str(tp.get("light_reason", "")))}">{html.escape(str(tp.get("light_reason", "")))}</div>',
            title=f"treasury light · {html.escape(UNI.display(pair))}",
        )
    else:
        ui.card(
            '<div class="fx-muted">Treasury light not available for this view.</div><div class="fx-dim" style="font-size:0.74rem;margin-top:4px">'
            + (
                "the light is computed for today only, not for the time machine"
                if time_machine
                else "run `make treasury` to write data/treasury_risk.json"
            )
            + "</div>",
            title="treasury light",
        )
with c3:
    cv_live = (coverage.get("live") or {}) if coverage else {}
    cv_test = (coverage.get("frozen_test") or {}) if coverage else {}
    if cv_live.get("coverage") is not None:
        ui.card(
            f'<div class="fx-num" style="font-size:1.35rem;font-weight:500">{cv_live["coverage"]:.1%}</div>'
            f'<div class="fx-dim fx-num" style="font-size:0.78rem">target 90 · {cv_live.get("n", 0)} scored rows · live</div>',
            title="interval coverage · live",
        )
    elif cv_test.get("overall") is not None:
        ui.card(
            f'<div class="fx-num" style="font-size:1.35rem;font-weight:500">{cv_test["overall"]:.1%}</div>'
            f'<div class="fx-dim fx-num" style="font-size:0.78rem">target 90 · frozen test n = {cv_test.get("n", 0):,} · live band warming up</div>',
            title="interval coverage · frozen test",
        )
    else:
        ui.card(
            '<div class="fx-muted">No coverage receipt yet.</div><div class="fx-dim" style="font-size:0.74rem;margin-top:4px">written by the conformal step of the pipeline.</div>',
            title="interval coverage",
        )

# --------------------------------------------------------------------------------------
# alerts (only when there is something to act on)
# --------------------------------------------------------------------------------------
_latest_rows = {
    p: regimes[regimes["pair"] == p].sort_values("date").iloc[-1]
    for p in PAIRS
    if not regimes[regimes["pair"] == p].empty
}
_alerts = []
for p, r in _latest_rows.items():
    if r["regime"] == "crisis":
        _alerts.append(
            (
                ui.REGIME_COLORS["crisis"],
                f"{UNI.display(p)} is in a crisis regime (confidence {r['regime_prob']:.0%})",
            )
        )
    if float(r.get("anomaly_pct", 0) or 0) > 98:
        _alerts.append(
            (
                ui.REGIME_COLORS["crisis"],
                f"{UNI.display(p)}: siren at percentile {float(r['anomaly_pct']):.0f} — today looks unlike any calm day",
            )
        )
    if float(r.get("change_risk_5d", 0) or 0) > 0.4:
        _alerts.append(
            (
                ui.REGIME_COLORS["chop"],
                f"{UNI.display(p)}: 5-day regime-change risk {float(r['change_risk_5d']):.0%}",
            )
        )
    if int(r.get("agreement", 0) or 0) == 3:
        _alerts.append(
            (ui.REGIME_COLORS["crisis"], f"{UNI.display(p)}: 3/3 voters agree — storm conditions")
        )
if _alerts:
    st.markdown(
        "".join(
            f'<div class="fx-alert" style="border-color:{ui.alpha(c, 0.35)}"><span style="width:8px;height:8px;border-radius:50%;background:{c};display:inline-block"></span><span>{html.escape(t)}</span></div>'
            for c, t in _alerts
        ),
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------------------
# one compact weather card per market (the banner shows the selected one in full)
# --------------------------------------------------------------------------------------
st.markdown('<div class="fx-section">All markets</div>', unsafe_allow_html=True)
if len(PAIRS) > 4:
    # large universe: one dense table (numbers in a well-set table beat ten cramped cards)
    table_rows = []
    for p in PAIRS:
        gp = regimes[regimes["pair"] == p].sort_values("date")
        if gp.empty:
            continue
        latest = gp.iloc[-1]
        closes = prices[prices["pair"] == p].sort_values("date")["close"].tail(20)
        px_fmt = "{:.4f}" if closes.iloc[-1] < 100 else "{:,.2f}"
        table_rows.append(
            {
                "label": UNI.display(p),
                "regime": str(latest["regime"]),
                "regime_prob": float(latest["regime_prob"]),
                "days_in_regime": int(latest["days_in_regime"]),
                "change_risk": float(latest.get("change_risk_5d", 0.0) or 0.0),
                "risk_lo": latest.get("risk_lo") if pd.notna(latest.get("risk_lo")) else None,
                "risk_hi": latest.get("risk_hi") if pd.notna(latest.get("risk_hi")) else None,
                "agreement": (
                    int(latest["agreement"]) if pd.notna(latest.get("agreement")) else None
                ),
                "anomaly_pct": latest.get("anomaly_pct"),
                "close": px_fmt.format(closes.iloc[-1]),
                "closes": closes,
            }
        )
    ui.card(
        ui.market_table(table_rows)
        + '<div class="fx-dim" style="font-size:0.74rem;margin-top:8px">Pick a market in the header or sidebar to read it in full (banner above, detail on the Pairs page). Regimes describe conditions, never direction.</div>'
    )
else:
    for col, p in ui.grid(PAIRS, per_row=3):
        gp = regimes[regimes["pair"] == p].sort_values("date")
        if gp.empty:
            with col:
                ui.card(
                    f'<span style="font-weight:500">{UNI.display(p)}</span><div class="fx-muted">no data as of this date</div>'
                )
            continue
        latest = gp.iloc[-1]
        if p in api_latest:
            latest = pd.Series(
                {
                    **latest.to_dict(),
                    **{k: v for k, v in api_latest[p].items() if k in latest.index},
                }
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
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
            f'<span style="font-weight:500;font-size:1rem">{UNI.display(p)}</span>{ui.regime_pill(latest["regime"], large=True)}</div>'
            f'<div class="fx-muted" style="font-size:0.8rem;margin-bottom:4px">{ui.REGIME_BLURB[latest["regime"]]}</div>'
            f"{ui.confidence_bar(latest['regime_prob'], color)}"
            f'<div class="fx-kv" style="margin-top:4px"><span>day <span class="fx-num">{int(latest["days_in_regime"])}</span> of this regime</span>'
            f'<span>close <span class="fx-num">{px_fmt.format(closes.iloc[-1])}</span></span></div>'
            f"{ui.sparkline_svg(closes, color)}"
            + (
                ui.risk_gauge(
                    latest["change_risk_5d"],
                    None,
                    lo=latest.get("risk_lo"),
                    hi=latest.get("risk_hi"),
                    regime=str(latest["regime"]),
                )
                if "change_risk_5d" in latest and pd.notna(latest["change_risk_5d"])
                else ""
            )
            + ui.consensus_meter(
                latest.get("agreement"),
                {k: latest.get(k) for k in ("vote_hmm", "vote_bocpd", "vote_vol")},
                None,
            )
            + (
                f'<div class="fx-kv" style="margin-top:6px"><span>siren</span><span class="fx-num" style="color:{ui.siren_color(float(latest["anomaly_pct"]))}">{float(latest["anomaly_pct"]):.0f}/100</span></div>'
                if pd.notna(latest.get("anomaly_pct"))
                else ""
            )
            + ui.narration(narration, compact=True)
        )
        with col:
            ui.card(body)

ui.footer(
    DISCLAIMER,
    "· Risk information, never direction forecasts. Details per market on the Pairs page; the record on Proof.",
)
