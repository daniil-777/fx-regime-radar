"""Treasury mode: regime-conditional 1-week VaR / ES and the hedge / wait / ladder traffic light.

One recurring treasurer question — "I have an exposure in a foreign currency; how large is the
adverse move I should budget for this week, and is now a sensible moment to act?" — answered with
risk math and a price tag, never a direction (CLAUDE.md rules 4, 5).

Method (documented in docs/TREASURY.md):
* Historical simulation. For every day t we take the 5-trading-day (overlapping) log move of the
  close, |log(close[t+5] / close[t])|, and label it with the FILTERED regime on day t — the regime
  that was known at the START of the window, so nothing looks ahead.
* Estimation uses the TRAIN ERA ONLY (window END date <= config.TRAIN_END). VaR at level q is the
  q-quantile of the ABSOLUTE move; ES is the mean of the moves at or beyond VaR.
* Why the absolute move: a treasurer with a receivable or a payable is hurt by an adverse move
  in EITHER direction, and this project never takes a direction view. We therefore quote the
  size of the move, not its sign.
* A regime with fewer than MIN_WINDOWS train windows is replaced by the unconditional cell and
  flagged (USDCHF crisis has ~20 windows).

The pipeline writes data/treasury_risk.json; the Streamlit page only multiplies its numbers by
user inputs (rule 8). `decide` is the deterministic traffic-light rule table.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import config

log = logging.getLogger(__name__)

PATH = config.DATA_DIR / "treasury_risk.json"
EVENTS_PATH = config.DATA_DIR / "events.csv"
FEATURES_EXT_PATH = config.DATA_DIR / "features_ext.parquet"

REGIMES = ["calm", "trend", "chop", "crisis"]
LEVELS = (0.95, 0.99)
HORIZON_DAYS = 5  # one trading week
MIN_WINDOWS = 30  # fewer train windows than this -> unconditional fallback
HIGH_RISK_PCTL, LOW_RISK_PCTL = 0.80, 0.40  # train-era percentiles of change_risk_5d
DEFAULT_WIDE, DEFAULT_NARROW = 0.25, 0.12  # interval width cut-offs when no conformal band exists
DEFAULT_HIGH_RISK, DEFAULT_LOW_RISK = 0.30, 0.10  # only if change_risk_5d is entirely missing
EVENT_WINDOW_DAYS = 5  # "an event within the horizon" blocks the wait light
METHOD = "historical simulation, 5-day overlapping log returns, regime-labelled train era"
LIGHT_COLOR_REGIME = {"hedge": "crisis", "ladder": "chop", "wait": "calm"}  # palette pointer
CURRENCIES = ["CHF", "EUR", "USD", "GBP"]
SUGGESTED_PAIR = {"EUR": "EURUSD", "USD": "USDCHF", "GBP": "GBPUSD", "CHF": "USDCHF"}

# Every user-facing sentence lives here so a lint test can scan them for direction words.
TEMPLATES: dict[str, str] = {
    "hedge_crisis": (
        "Crisis regime: historical 1-week moves in this state are the widest of all four; "
        "lock in a larger share of the exposure now."
    ),
    "hedge_risk": (
        "Change risk {risk:.0%} is at or above the train-era 80th percentile ({hi:.0%}) and the "
        "interval on it is wide ({width:.2f}); conditions are unstable — lock in a larger share now."
    ),
    "wait": (
        "Calm regime, change risk {risk:.0%} is below the train-era 40th percentile ({lo:.0%}){band}"
        "{event}; holding and re-checking daily is defensible."
    ),
    "ladder": (
        "Neither clear-cut: {why}. Split the exposure into tranches over the horizon so no single "
        "week carries the whole move."
    ),
    "why_regime": "regime is {regime}, not calm",
    "why_risk": "change risk {risk:.0%} is not below the 40th percentile ({lo:.0%})",
    "why_band": "the interval on change risk is {width:.2f} wide, not narrow (< {narrow:.2f})",
    "why_event": "{event} is {days} trading days away",
    "band_narrow": ", the interval on it is narrow ({width:.2f})",
    "band_unknown": ", no interval available",
    "event_far": ", next scheduled event ({event}) is {days} trading days away",
    "event_none": ", no scheduled event on file",
    "agreement": " Model agreement {agreement}/3: {consensus}.",
    "cost_of_waiting": (
        "Waiting 1 more week on {amount} risks ≈ {home} {x} at the {level} level (regime: {regime})."
    ),
    "fallback_note": "fewer than {min_n} train windows — unconditional numbers used",
    "meaning_hedge": "lock in a larger share of the exposure now with a forward.",
    "meaning_wait": "hold, re-check daily; the models see a quiet week.",
    "meaning_ladder": "split the exposure into tranches spread over the horizon.",
    "disclaimer": config.DISCLAIMER,
}
DIRECTION_WORDS = (
    "rise fall up down buy sell long short target bullish bearish rally drop appreciate "
    "depreciate strengthen weaken"
).split()
_DIRECTION_RE = re.compile(r"\b(" + "|".join(DIRECTION_WORDS) + r")\b", re.IGNORECASE)


def has_direction_words(text: str) -> list[str]:
    """Direction words found in `text` (word-boundary match) — used by the lint test."""
    return [m.group(0) for m in _DIRECTION_RE.finditer(text)]


# --------------------------------------------------------------------------------------
# risk engine (pure functions: dataframes in, dicts out)
# --------------------------------------------------------------------------------------
def weekly_moves(
    prices: pd.DataFrame, regimes: pd.DataFrame, horizon: int = HORIZON_DAYS
) -> pd.DataFrame:
    """Overlapping `horizon`-day absolute log moves labelled with the regime at the window START.

    Returns date (window start), end_date, pair, regime, move = |log(close[t+h] / close[t])|.
    The label is the regime filtered on day t — known before the window begins (no look-ahead).
    """
    p = prices[["date", "pair", "close"]].sort_values(["pair", "date"]).copy()
    g = p.groupby("pair", sort=False)
    p["end_date"] = g["date"].shift(-horizon)
    p["move"] = (np.log(g["close"].shift(-horizon)) - np.log(p["close"])).abs()
    r = regimes[["date", "pair", "regime"]]
    out = p.merge(r, on=["date", "pair"], how="inner").dropna(subset=["move", "end_date"])
    return out[["date", "end_date", "pair", "regime", "move"]].reset_index(drop=True)


def var_es(moves: np.ndarray | pd.Series, level: float) -> tuple[float, float]:
    """Historical VaR (quantile of the absolute move) and ES (mean of moves at or beyond VaR)."""
    x = np.asarray(moves, dtype=float)
    x = x[~np.isnan(x)]
    if x.size == 0:
        return float("nan"), float("nan")
    var = float(np.quantile(x, level))
    tail = x[x >= var]
    es = float(tail.mean()) if tail.size else var
    return var, es


def _cell(moves: np.ndarray | pd.Series, levels: tuple[float, ...]) -> dict:
    cell: dict = {"n": int(len(moves))}
    for lv in levels:
        var, es = var_es(moves, lv)
        key = f"{int(round(lv * 100))}"
        cell[f"var_{key}"], cell[f"es_{key}"] = var, es
    return cell


def table(
    moves: pd.DataFrame,
    train_end: str = config.TRAIN_END,
    levels: tuple[float, ...] = LEVELS,
    min_windows: int = MIN_WINDOWS,
) -> dict[str, dict]:
    """Per pair: {regime: {n, var_95, es_95, var_99, es_99, fallback}} + 'unconditional'.

    Only windows that END on or before `train_end` are used (train era, rule 2). A regime cell
    with fewer than `min_windows` windows is replaced by the unconditional cell, flagged.
    """
    train = moves[moves["end_date"] <= pd.Timestamp(train_end)]
    out: dict[str, dict] = {}
    for pair, grp in train.groupby("pair", sort=True):
        uncond = _cell(grp["move"], levels)
        uncond["fallback"] = False
        cells: dict[str, dict] = {}
        for regime in REGIMES:
            m = grp.loc[grp["regime"] == regime, "move"]
            if len(m) >= min_windows:
                cell = _cell(m, levels)
                cell["fallback"] = False
            else:
                cell = {**uncond, "n": int(len(m)), "fallback": True}
            cells[regime] = cell
        out[str(pair)] = {"table": cells, "unconditional": uncond}
    return out


def fit_thresholds(regimes_train: pd.DataFrame) -> dict:
    """Traffic-light thresholds from the TRAIN era only.

    HIGH_RISK / LOW_RISK = 80th / 40th percentile of change_risk_5d. WIDE / NARROW = the 80th /
    40th percentile of the conformal interval width (2 x conformal_q) when that column exists,
    else the documented defaults (0.25 / 0.12).
    """
    out = {
        "high_risk": DEFAULT_HIGH_RISK,
        "low_risk": DEFAULT_LOW_RISK,
        "wide": DEFAULT_WIDE,
        "narrow": DEFAULT_NARROW,
        "risk_source": "default",
        "width_source": "default",
        "high_risk_pctl": HIGH_RISK_PCTL,
        "low_risk_pctl": LOW_RISK_PCTL,
        "event_window_days": EVENT_WINDOW_DAYS,
    }
    if "change_risk_5d" in regimes_train:
        cr = pd.to_numeric(regimes_train["change_risk_5d"], errors="coerce").dropna()
        if len(cr):
            out["high_risk"] = float(cr.quantile(HIGH_RISK_PCTL))
            out["low_risk"] = float(cr.quantile(LOW_RISK_PCTL))
            out["risk_source"] = f"train-era percentiles (n={len(cr)})"
    if "conformal_q" in regimes_train:
        w = 2.0 * pd.to_numeric(regimes_train["conformal_q"], errors="coerce").dropna()
        if len(w):
            out["wide"] = float(w.quantile(HIGH_RISK_PCTL))
            out["narrow"] = float(w.quantile(LOW_RISK_PCTL))
            out["width_source"] = f"train-era conformal widths (n={len(w)})"
    return out


def _width(risk_lo: float | None, risk_hi: float | None) -> float | None:
    if risk_lo is None or risk_hi is None:
        return None
    if any(isinstance(v, float) and math.isnan(v) for v in (risk_lo, risk_hi)):
        return None
    return float(risk_hi) - float(risk_lo)


def decide(
    regime: str,
    change_risk: float | None,
    risk_lo: float | None,
    risk_hi: float | None,
    agreement: int | None,
    days_to_event: int | None,
    thresholds: dict,
    next_event: str | None = None,
    consensus_text: str | None = None,
) -> tuple[str, str]:
    """Deterministic traffic light -> (light, reason). Lights: 'hedge' | 'ladder' | 'wait'.

    hedge : crisis OR (change_risk >= HIGH_RISK AND interval width >= WIDE)
    wait  : calm AND change_risk < LOW_RISK AND (width < NARROW or width unknown)
            AND (no event on file or the next event is > EVENT_WINDOW_DAYS trading days away)
    ladder: everything else (the reason names the first condition that failed).
    """
    risk = float(change_risk) if change_risk is not None and not pd.isna(change_risk) else 0.0
    width = _width(risk_lo, risk_hi)
    hi, lo = float(thresholds["high_risk"]), float(thresholds["low_risk"])
    wide, narrow = float(thresholds["wide"]), float(thresholds["narrow"])
    window = int(thresholds.get("event_window_days", EVENT_WINDOW_DAYS))
    event_name = next_event or "a scheduled event"
    tail = ""
    if agreement is not None and consensus_text:
        tail = TEMPLATES["agreement"].format(agreement=int(agreement), consensus=consensus_text)

    if regime == "crisis":
        return "hedge", TEMPLATES["hedge_crisis"] + tail
    if risk >= hi and width is not None and width >= wide:
        return "hedge", TEMPLATES["hedge_risk"].format(risk=risk, hi=hi, width=width) + tail

    event_far = days_to_event is None or int(days_to_event) > window
    if regime == "calm" and risk < lo and (width is None or width < narrow) and event_far:
        band = (
            TEMPLATES["band_unknown"]
            if width is None
            else TEMPLATES["band_narrow"].format(width=width)
        )
        event = (
            TEMPLATES["event_none"]
            if days_to_event is None
            else TEMPLATES["event_far"].format(event=event_name, days=int(days_to_event))
        )
        return "wait", TEMPLATES["wait"].format(risk=risk, lo=lo, band=band, event=event) + tail

    if regime != "calm":
        why = TEMPLATES["why_regime"].format(regime=regime)
    elif risk >= lo:
        why = TEMPLATES["why_risk"].format(risk=risk, lo=lo)
    elif width is not None and width >= narrow:
        why = TEMPLATES["why_band"].format(width=width, narrow=narrow)
    else:
        why = TEMPLATES["why_event"].format(event=event_name, days=int(days_to_event or 0))
    return "ladder", TEMPLATES["ladder"].format(why=why) + tail


# --------------------------------------------------------------------------------------
# events / calendar inputs (all optional, read defensively)
# --------------------------------------------------------------------------------------
def next_event_from_csv(
    events: pd.DataFrame | None, as_of: pd.Timestamp
) -> tuple[int | None, str | None]:
    """(trading days until the next event strictly after `as_of`, its type) from events.csv."""
    if events is None or len(events) == 0 or "date" not in events:
        return None, None
    ev = events.copy()
    ev["date"] = pd.to_datetime(ev["date"], errors="coerce")
    ev = ev.dropna(subset=["date"])
    ev = ev[ev["date"] > as_of].sort_values("date")
    if ev.empty:
        return None, None
    nxt = ev.iloc[0]
    days = int(np.busday_count(as_of.date(), nxt["date"].date()))
    return days, str(nxt.get("type", "event"))


def next_event_from_ext(ext_row: pd.Series | None) -> tuple[int | None, str | None]:
    """(days, TYPE) from a features_ext row's days_to_<TYPE> columns (smallest non-negative)."""
    if ext_row is None:
        return None, None
    best: tuple[int, str] | None = None
    for col, val in ext_row.items():
        if not str(col).startswith("days_to_") or val is None or pd.isna(val):
            continue
        d = int(val)
        if d >= 0 and (best is None or d < best[0]):
            best = (d, str(col)[len("days_to_") :])
    return (None, None) if best is None else best


def read_events(path: Path = EVENTS_PATH) -> pd.DataFrame | None:
    """data/events.csv (date,type,source) if present and readable, else None — never raises."""
    try:
        if Path(path).exists():
            return pd.read_csv(path)
    except Exception as exc:  # malformed file must not break the daily pipeline
        log.warning("treasury: could not read %s: %s", path, exc)
    return None


# --------------------------------------------------------------------------------------
# conversions (arithmetic only; the page calls these so it never computes anything itself)
# --------------------------------------------------------------------------------------
def latest_fx(prices: pd.DataFrame) -> dict[str, float]:
    """Latest closes of the three pairs plus the derived crosses used for conversion to CHF/EUR/GBP."""
    last = prices.sort_values("date").groupby("pair")["close"].last()
    fx = {p: float(last[p]) for p in ("EURUSD", "USDCHF", "GBPUSD") if p in last}
    if "EURUSD" in fx and "USDCHF" in fx:
        fx["EURCHF"] = fx["EURUSD"] * fx["USDCHF"]
    if "GBPUSD" in fx and "USDCHF" in fx:
        fx["GBPCHF"] = fx["GBPUSD"] * fx["USDCHF"]
    if "EURUSD" in fx and "GBPUSD" in fx:
        fx["EURGBP"] = fx["EURUSD"] / fx["GBPUSD"]
    return fx


def to_chf_rate(ccy: str, fx: dict[str, float]) -> float:
    """How many CHF one unit of `ccy` is worth at the latest closes."""
    return {"CHF": 1.0, "EUR": fx["EURCHF"], "USD": fx["USDCHF"], "GBP": fx["GBPCHF"]}[ccy]


def convert(amount: float, ccy_from: str, ccy_to: str, fx: dict[str, float]) -> float:
    """Convert an amount between CHF/EUR/USD/GBP via CHF at the latest closes."""
    return float(amount) * to_chf_rate(ccy_from, fx) / to_chf_rate(ccy_to, fx)


def scale_to_horizon(one_week: float, weeks: int) -> float:
    """Square-root-of-time scaling of a 1-week quantile to `weeks` (an approximation, documented)."""
    return float(one_week) * math.sqrt(max(int(weeks), 1))


def round_sig(x: float, sig: int = 2) -> float:
    """Round to `sig` significant figures (no false precision on money amounts)."""
    if x == 0 or not math.isfinite(x):
        return x
    return round(x, sig - int(math.floor(math.log10(abs(x)))) - 1)


def money_at_risk(
    amount: float, ccy: str, quantile: float, weeks: int, home: str, fx: dict[str, float]
) -> float:
    """amount x (1-week quantile scaled to `weeks`) converted to the home currency, rounded."""
    return round_sig(convert(float(amount) * scale_to_horizon(quantile, weeks), ccy, home, fx))


def cost_of_waiting_line(
    amount: float, ccy: str, es_99_week: float, home: str, fx: dict, regime: str
) -> str:
    """The one-week cost-of-waiting sentence (ES at 99 %, one week, home currency)."""
    x = money_at_risk(amount, ccy, es_99_week, 1, home, fx)
    symbol = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}[ccy]
    return TEMPLATES["cost_of_waiting"].format(
        amount=f"{symbol}{amount:,.0f}", home=home, x=f"{x:,.0f}", level="99%", regime=regime
    )


# --------------------------------------------------------------------------------------
# artifact
# --------------------------------------------------------------------------------------
def _opt(row: pd.Series, col: str):
    """Column value as a plain Python number / str, None when absent or NaN."""
    if col not in row.index:
        return None
    v = row[col]
    if v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v):
        return None
    if isinstance(v, (np.integer, np.floating)):
        v = v.item()
    return None if isinstance(v, float) and math.isnan(v) else v


def build(
    regimes: pd.DataFrame,
    prices: pd.DataFrame,
    features_ext: pd.DataFrame | None = None,
    events: pd.DataFrame | None = None,
    train_end: str = config.TRAIN_END,
) -> dict:
    """The full treasury_risk.json payload from the scored artifacts (pure; no I/O)."""
    regimes = regimes.sort_values(["pair", "date"])
    as_of = pd.Timestamp(regimes["date"].max())
    moves = weekly_moves(prices, regimes)
    tables = table(moves, train_end=train_end)
    thresholds = fit_thresholds(regimes[regimes["date"] <= pd.Timestamp(train_end)])
    ev_days, ev_name = next_event_from_csv(events, as_of)
    fx = latest_fx(prices)
    pairs: dict[str, dict] = {}
    for pair, grp in regimes.groupby("pair", sort=True):
        if pair not in tables:
            continue
        row = grp.iloc[-1]
        d_ev, n_ev = ev_days, ev_name
        if features_ext is not None and "pair" in features_ext:
            ext = features_ext[features_ext["pair"] == pair].sort_values("date")
            if len(ext):
                d2, n2 = next_event_from_ext(ext.iloc[-1])
                if d2 is not None and (d_ev is None or d2 < d_ev):
                    d_ev, n_ev = d2, n2
        inputs = {
            "change_risk_5d": _opt(row, "change_risk_5d"),
            "risk_lo": _opt(row, "risk_lo"),
            "risk_hi": _opt(row, "risk_hi"),
            "agreement": _opt(row, "agreement"),
            "consensus_text": _opt(row, "consensus_text"),
            "days_to_next_event": d_ev,
            "next_event": n_ev,
        }
        light, reason = decide(
            str(row["regime"]),
            inputs["change_risk_5d"],
            inputs["risk_lo"],
            inputs["risk_hi"],
            inputs["agreement"],
            d_ev,
            thresholds,
            next_event=n_ev,
            consensus_text=inputs["consensus_text"],
        )
        pairs[str(pair)] = {
            "current_regime": str(row["regime"]),
            "regime_prob": float(row.get("regime_prob", float("nan"))),
            "days_in_regime": int(row.get("days_in_regime", 0) or 0),
            "table": tables[pair]["table"],
            "unconditional": tables[pair]["unconditional"],
            "light": light,
            "light_reason": reason,
            "inputs": inputs,
        }
    return {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": str(as_of.date()),
        "levels": list(LEVELS),
        "horizon_days": HORIZON_DAYS,
        "train_end": str(train_end),
        "min_windows": MIN_WINDOWS,
        "method": METHOD,
        "thresholds": thresholds,
        "pairs": pairs,
        "fx": fx,
        "disclaimer": config.DISCLAIMER,
    }


def _no_nan(obj):
    """NaN -> null recursively (strict JSON readers such as the Rust service reject NaN)."""
    if isinstance(obj, dict):
        return {k: _no_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_no_nan(v) for v in obj]
    if isinstance(obj, (np.integer, np.floating)):
        obj = obj.item()
    return None if isinstance(obj, float) and not math.isfinite(obj) else obj


def write(payload: dict, path: Path = PATH) -> None:
    """Strict JSON (no NaN) so any reader — including the Rust service — can parse it."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(_no_nan(payload), indent=1, allow_nan=False, default=float))


def load(path: Path = PATH) -> dict | None:
    """The artifact as a dict, or None when it does not exist."""
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


def sanity_rows(payload: dict) -> list[dict]:
    """Crisis-vs-calm ES per pair and level (the phase's sanity table)."""
    rows = []
    for pair, d in payload["pairs"].items():
        for lv in ("95", "99"):
            rows.append(
                {
                    "pair": pair,
                    "level": lv,
                    "es_calm": d["table"]["calm"][f"es_{lv}"],
                    "es_crisis": d["table"]["crisis"][f"es_{lv}"],
                    "crisis_fallback": d["table"]["crisis"]["fallback"],
                    "ok": d["table"]["crisis"][f"es_{lv}"] >= d["table"]["calm"][f"es_{lv}"],
                }
            )
    return rows


def stage(ctx: dict) -> None:
    """Pipeline stage: build the treasury artifact from ctx and register its writer."""
    ext = ctx.get("features_ext")
    if ext is None and FEATURES_EXT_PATH.exists():
        try:
            ext = pd.read_parquet(FEATURES_EXT_PATH)
        except Exception as exc:  # optional input
            log.warning("treasury: could not read %s: %s", FEATURES_EXT_PATH, exc)
    ctx["treasury"] = build(ctx["regimes"], ctx["prices"], features_ext=ext, events=read_events())
    ctx.setdefault("extra_writers", {})["treasury_risk.json"] = lambda c: write(c["treasury"])
    log.info(
        "treasury: %s",
        ", ".join(
            f"{p}={d['light']} ({d['current_regime']}, es99 1w {d['table'][d['current_regime']]['es_99']:.2%})"
            for p, d in ctx["treasury"]["pairs"].items()
        ),
    )


def main() -> None:
    """Build data/treasury_risk.json from the committed artifacts and print the sanity table."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ctx = {
        "regimes": pd.read_parquet(config.REGIMES_PATH),
        "prices": pd.read_parquet(config.PRICES_PATH),
    }
    stage(ctx)
    ctx["extra_writers"]["treasury_risk.json"](ctx)
    print(pd.DataFrame(sanity_rows(ctx["treasury"])).to_string(index=False))
    print(json.dumps(ctx["treasury"]["thresholds"], indent=1))
    print(f"wrote {PATH}")


if __name__ == "__main__":
    main()
