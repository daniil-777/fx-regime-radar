"""Resolve registry cards into ready-to-render specs (phase 36).

Two constitutional rules shape this module. Rule 8 — pipeline writes, app reads — means every card
is resolved HERE, at pipeline time, into `data/visual_boards.json`; the serving path only looks a
card up by key. Rule 11 — the wall — means the Rust service never calls Python: it reads this
artifact and `data/visual_index.json` (the retrieval index) as data.

Consequences worth stating plainly:
  * the model never produces a number, and neither does the browser: every value in a rendered card
    was computed by this pipeline from a published artifact, exactly like the spoken answer;
  * a card whose data is unavailable is simply absent from the artifact, so the serving path can
    never offer a card it cannot fill;
  * cards taking a user-supplied value (an exposure, a hypothetical move) are deliberately NOT
    precomputed — they belong to the scenario engine, where the user's own number is the input.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from fxradar import config, visuals

log = logging.getLogger(__name__)

BOARDS_PATH = config.DATA_DIR / "visual_boards.json"
INDEX_PATH = config.DATA_DIR / "visual_index.json"
WINDOW_DAYS = {"30d": 30, "90d": 90, "1y": 252, "5y": 1260}
METRIC_LABELS = {
    "var_99": "99% value at risk",
    "var_95": "95% value at risk",
    "es_99": "99% expected shortfall",
    "es_95": "95% expected shortfall",
}
MAX_TRACE_POINTS = 90  # a card is 480px wide; more points than this is invisible detail

Provider = Callable[[dict, dict], dict | None]
PROVIDERS: dict[str, Provider] = {}


def provider(card_id: str) -> Callable[[Provider], Provider]:
    def wrap(fn: Provider) -> Provider:
        PROVIDERS[card_id] = fn
        return fn

    return wrap


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _pair_rows(ctx: dict, pair: str) -> pd.DataFrame:
    return ctx["regimes"][ctx["regimes"]["pair"] == pair].sort_values("date")


def _tail(df: pd.DataFrame, window: str) -> pd.DataFrame:
    return df.tail(WINDOW_DAYS.get(window, 90))


def _downsample(rows: list[dict]) -> list[dict]:
    if len(rows) <= MAX_TRACE_POINTS:
        return rows
    step = math.ceil(len(rows) / MAX_TRACE_POINTS)
    return rows[::step] + [rows[-1]]


def _num(value: Any, nd: int = 2) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return round(float(value), nd)


def _pack_pair(ctx: dict, pair: str) -> dict:
    """A pair's latest block, from the majors or from any other board the radar computes."""
    direct = (ctx["pack"].get("pairs") or {}).get(pair)
    if direct:
        return direct
    for uni in (ctx["pack"].get("markets") or {}).values():
        block = (uni.get("pairs") or {}).get(pair)
        if block:
            return dict(block, _asof=uni.get("data_through"))
    return {}


def all_markets(ctx: dict) -> list[str]:
    """Every pair with a published block — the three majors plus the G10, EM and crypto boards."""
    out = list((ctx["pack"].get("pairs") or {}).keys())
    for uni in (ctx["pack"].get("markets") or {}).values():
        out += [p for p in (uni.get("pairs") or {}) if p not in out]
    return out


def _runs(dates: pd.Series, labels: pd.Series) -> list[dict]:
    """Consecutive same-label stretches → ribbon segments."""
    out: list[dict] = []
    for date, label in zip(dates, labels, strict=False):
        if out and out[-1]["tone"] == label:
            out[-1]["weight"] += 1
            out[-1]["end"] = f"{date:%Y-%m-%d}"
        else:
            out.append(
                {
                    "tone": str(label),
                    "weight": 1,
                    "start": f"{date:%Y-%m-%d}",
                    "end": f"{date:%Y-%m-%d}",
                }
            )
    return out


# ---------------------------------------------------------------------------------------------
# providers — one per card, each returning the primitive's `data` dict (or None if unavailable)
# ---------------------------------------------------------------------------------------------
@provider("condition_card")
def _condition(args: dict, ctx: dict) -> dict | None:
    p = _pack_pair(ctx, args["pair"])
    if not p:
        return None
    return {
        "stats": [
            {"value": p["regime"], "label": "regime", "tone": p["regime"], "mono": False},
            {"value": f"{p['change_risk_5d']:.2f}", "label": "change risk"},
            {"value": f"{p['anomaly_pct']:.0f}", "label": "siren"},
        ],
        "subline": f"band {p['risk_lo']:.2f} to {p['risk_hi']:.2f} · day {p['days_in_regime']} of this regime",
    }


@provider("consensus_dots")
def _consensus(args: dict, ctx: dict) -> dict | None:
    rows = _pair_rows(ctx, args["pair"])
    if rows.empty:
        return None
    last = rows.iloc[-1]
    names = [
        ("vote_hmm", "regime model"),
        ("vote_bocpd", "changepoint"),
        ("vote_vol", "volatility"),
    ]
    items = []
    for col, label in names:
        stressed = bool(last.get(col, 0))
        items.append(
            {
                "label": label,
                "tone": "crisis" if stressed else "calm",
                "sub": "stress" if stressed else "quiet",
            }
        )
    return {"items": items}


@provider("siren_gauge")
def _siren(args: dict, ctx: dict) -> dict | None:
    p = _pack_pair(ctx, args["pair"])
    if not p:
        return None
    pct = p["anomaly_pct"]
    tone = "crisis" if pct >= 98 else "chop" if pct >= 90 else "calm"
    return {
        "stats": [{"value": f"{pct:.0f}", "label": "siren percentile", "tone": tone}],
        "subline": "above 98 means today looks unlike anything in the calm training years",
    }


@provider("pair_compare_table")
def _pair_compare(args: dict, ctx: dict) -> dict | None:
    pairs = ctx["pack"].get("pairs") or {}
    if not pairs:
        return None
    rows = [
        [p["label"], p["regime"], f"{p['change_risk_5d']:.2f}", f"{p['anomaly_pct']:.0f}"]
        for p in pairs.values()
    ]
    return {"columns": ["market", "regime", "risk", "siren"], "rows": rows}


@provider("drift_status")
def _drift(args: dict, ctx: dict) -> dict | None:
    status = ctx.get("status") or {}
    drifted = status.get("drifted_features") or []
    stale = bool((ctx["pack"].get("drift") or {}).get("model_stale"))
    return {
        "stats": [
            {
                "value": "stale" if stale else "healthy",
                "label": "model",
                "tone": "crisis" if stale else "calm",
                "mono": False,
            },
            {"value": str(len(drifted)), "label": "drifted features"},
        ],
        "subline": (
            ("features outside their training distribution: " + ", ".join(drifted[:4]))
            if drifted
            else "every feature is inside its training distribution"
        ),
    }


@provider("risk_trace")
def _risk_trace(args: dict, ctx: dict) -> dict | None:
    df = _tail(_pair_rows(ctx, args["pair"]), args["window"])
    if df.empty or "change_risk_5d" not in df:
        return None
    pts = [
        {
            "v": _num(r.change_risk_5d, 3),
            "lo": _num(r.risk_lo, 3),
            "hi": _num(r.risk_hi, 3),
            "d": f"{r.date:%Y-%m-%d}",
        }
        for r in df.itertuples()
        if pd.notna(r.change_risk_5d)
    ]
    pts = [p for p in pts if p["v"] is not None]
    if not pts:
        return None
    if any(p["lo"] is None or p["hi"] is None for p in pts):
        for p in pts:
            p.pop("lo", None)
            p.pop("hi", None)
    return {
        "points": _downsample(pts),
        "subline": f"{args['window']} · shaded band is the 90% conformal interval",
    }


@provider("vol_trace")
def _vol_trace(args: dict, ctx: dict) -> dict | None:
    feats = ctx.get("features")
    if feats is None:
        return None
    df = _tail(feats[feats["pair"] == args["pair"]].sort_values("date"), args["window"])
    pts = [
        {"v": _num(r.vol_20, 4), "d": f"{r.date:%Y-%m-%d}"}
        for r in df.itertuples()
        if pd.notna(r.vol_20)
    ]
    if not pts:
        return None
    return {"points": _downsample(pts), "subline": f"{args['window']} · 20-day realised volatility"}


@provider("regime_timeline_ribbon")
def _ribbon(args: dict, ctx: dict) -> dict | None:
    df = _tail(_pair_rows(ctx, args["pair"]), args["window"])
    if df.empty:
        return None
    segs = _runs(df["date"], df["regime"])
    present = list(dict.fromkeys(s["tone"] for s in segs))
    return {
        "segments": [
            {
                "tone": s["tone"],
                "weight": s["weight"],
                "title": f"{s['tone']} {s['start']} → {s['end']}",
            }
            for s in segs
        ],
        "legend": [{"label": t} for t in present],
    }


@provider("regime_history_table")
def _history(args: dict, ctx: dict) -> dict | None:
    df = _pair_rows(ctx, args["pair"])
    if df.empty:
        return None
    segs = [s for s in _runs(df["date"], df["regime"]) if s["tone"] in ("crisis", "chop")]
    segs = sorted(segs, key=lambda s: s["start"], reverse=True)[:6]
    if not segs:
        return None
    return {
        "columns": ["episode", "from", "to", "days"],
        "rows": [[s["tone"], s["start"], s["end"], str(s["weight"])] for s in segs],
    }


@provider("what_changed_card")
def _what_changed(args: dict, ctx: dict) -> dict | None:
    df = _pair_rows(ctx, args["pair"]).tail(2)
    if len(df) < 2:
        return None
    prev, now = df.iloc[0], df.iloc[1]
    delta = float(now.change_risk_5d) - float(prev.change_risk_5d)
    flipped = str(prev.regime) != str(now.regime)
    return {
        "stats": [
            {
                "value": str(now.regime),
                "label": "regime today",
                "tone": str(now.regime),
                "mono": False,
            },
            {"value": f"{delta:+.2f}", "label": "change risk move"},
            {"value": f"{now.anomaly_pct:.0f}", "label": "siren"},
        ],
        "subline": (
            f"regime flipped from {prev.regime}"
            if flipped
            else f"same regime as yesterday ({prev.regime})"
        ),
        "_caption": {
            "delta": f"{delta:+.2f}",
            "word": str(now.regime),
            "risk": f"{float(now.change_risk_5d):.2f}",
        },
    }


@provider("feature_driver_bars")
def _drivers(args: dict, ctx: dict) -> dict | None:
    df = _pair_rows(ctx, args["pair"])
    if df.empty or "top_drivers" not in df:
        return None
    raw = df.iloc[-1].get("top_drivers")
    names = list(raw) if hasattr(raw, "__len__") and not isinstance(raw, str) else []
    if not names:
        return None
    # The forecaster publishes an ORDERED list of the features that mattered most today, not their
    # SHAP magnitudes, so the bars encode rank. Saying so in the sub-line keeps the chart honest.
    rows = [
        {
            "label": str(n).replace("_", " "),
            "value": len(names) - i,
            "display": f"#{i + 1}",
            "highlight": i == 0,
        }
        for i, n in enumerate(names[:5])
    ]
    return {"rows": rows}


@provider("treasury_light")
def _light(args: dict, ctx: dict) -> dict | None:
    tre = ((ctx.get("treasury") or {}).get("pairs") or {}).get(args["pair"])
    if not tre:
        return None
    light = str(tre.get("light", "ladder"))
    tone = {"hedge": "crisis", "ladder": "chop", "wait": "calm"}.get(light, "chop")
    return {
        "stats": [{"value": light, "label": "treasury light", "tone": tone, "mono": False}],
        "subline": str(tre.get("light_reason", "")),
    }


@provider("var_es_bars")
def _var_es(args: dict, ctx: dict) -> dict | None:
    tre = ((ctx.get("treasury") or {}).get("pairs") or {}).get(args["pair"])
    if not tre:
        return None
    table = tre.get("table") or {}
    metric = args["metric"]
    current = str(tre.get("current_regime", ""))
    rows = []
    for regime in ("calm", "trend", "chop", "crisis"):
        cell = table.get(regime) or {}
        val = cell.get(metric)
        if val is None:
            continue
        rows.append(
            {
                "label": regime,
                "value": abs(float(val)),
                "display": f"{abs(float(val)) * 100:.2f}%",
                "tone": regime,
                "highlight": regime == current,
            }
        )
    return {"rows": rows} if rows else None


@provider("cost_of_waiting_curve")
def _cost_wait(args: dict, ctx: dict) -> dict | None:
    tre = ((ctx.get("treasury") or {}).get("pairs") or {}).get(args["pair"])
    if not tre:
        return None
    cell = (tre.get("table") or {}).get(str(tre.get("current_regime", "calm"))) or {}
    es = cell.get("es_99")
    if es is None:
        return None
    pts = [{"v": round(abs(float(es)) * math.sqrt(w), 4), "d": f"{w}w"} for w in range(1, 13)]
    return {
        "points": pts,
        "subline": "expected shortfall of the uncovered exposure, square-root-of-time scaled",
    }


@provider("scoreboard_card")
def _scoreboard(args: dict, ctx: dict) -> dict | None:
    led = ctx["pack"].get("ledger") or {}
    if not led:
        return None
    return {
        "stats": [
            {"value": str(led.get("days_live", 0)), "label": "days live"},
            {
                "value": (
                    f"{led.get('live_brier'):.3f}" if led.get("live_brier") is not None else "—"
                ),
                "label": "live Brier",
            },
            {
                "value": (
                    f"{led.get('frozen_brier'):.3f}" if led.get("frozen_brier") is not None else "—"
                ),
                "label": "frozen Brier",
            },
        ],
        "subline": f"chain head {led.get('chain_head_short', '—')} · "
        f"{led.get('n_forecasts', 0)} forecasts sealed before their outcomes",
    }


@provider("chain_verify_card")
def _chain(args: dict, ctx: dict) -> dict | None:
    led = ctx["pack"].get("ledger") or {}
    if not led:
        return None
    ok = bool(led.get("chain_ok"))
    return {
        "stats": [
            {
                "value": "VALID" if ok else "BROKEN",
                "label": "chain",
                "tone": "calm" if ok else "crisis",
                "mono": False,
            },
            {"value": str(led.get("n_forecasts", 0)), "label": "sealed rows"},
        ],
        "subline": f"head {led.get('chain_head_short', '—')} — clone the repository and run the "
        f"verifier yourself; it uses the standard library only",
    }


@provider("direction_evidence_card")
def _direction(args: dict, ctx: dict) -> dict | None:
    led = ctx["pack"].get("ledger") or {}
    return {
        "stats": [
            {"value": "none", "label": "direction models", "mono": False},
            {"value": str(led.get("days_live", 0)), "label": "days of sealed record"},
        ],
        "subline": "this system models conditions and risk; it has never modelled which way a price "
        "moves, which is why its record can be audited at all",
    }


@provider("event_countdown_strip")
def _events(args: dict, ctx: dict) -> dict | None:
    events = ctx["pack"].get("events") or []
    if not events:
        return None
    items = []
    for e in events[:6]:
        days = int(e.get("days", 0))
        items.append(
            {
                "label": str(e.get("type", "")),
                "sub": f"{days}d",
                "tone": "chop" if days <= 3 else "calm",
            }
        )
    return {"items": items}


@provider("glossary_card")
def _glossary(args: dict, ctx: dict) -> dict | None:
    text = (ctx.get("glossary") or {}).get(args["term"])
    if not text:
        return None
    return {"stats": [{"value": args["term"], "label": "term", "mono": False}], "subline": text}


@provider("metric_table")
def _metrics(args: dict, ctx: dict) -> dict | None:
    pairs = ctx["pack"].get("pairs") or {}
    if not pairs:
        return None
    rows = []
    for p in pairs.values():
        rows += [
            [f"{p['label']} regime", str(p["regime"])],
            [f"{p['label']} change risk", f"{p['change_risk_5d']:.2f}"],
            [f"{p['label']} siren", f"{p['anomaly_pct']:.0f}"],
        ]
    return {"columns": ["metric", "value"], "rows": rows}


@provider("hedge_compare_table")
def _hedge_compare(args: dict, ctx: dict) -> dict | None:
    dec = ((ctx.get("decision") or {}).get("pairs") or {}).get(args["pair"])
    if not dec:
        return None
    rows = []
    for tol in ("conservative", "balanced", "aggressive"):
        row = dec.get(tol) or {}
        ratio = row.get("hedge_ratio")
        if ratio is None:
            continue
        es = row.get("es_99_1w")
        rows.append([tol, f"{ratio:.0%}", f"{abs(float(es)) * 100:.2f}%" if es else "—"])
    return {"columns": ["profile", "cover", "1w ES of the rest"], "rows": rows} if rows else None


@provider("ledger_row_receipt")
def _ledger_row(args: dict, ctx: dict) -> dict | None:
    led = ctx.get("ledger_tail")
    if led is None or led.empty:
        return None
    row = led.iloc[-1]
    keep = [
        c
        for c in ("date", "pair", "regime", "change_risk_5d", "risk_lo", "risk_hi", "row_hash")
        if c in led.columns
    ]
    rows = []
    for col in keep:
        val = row[col]
        if hasattr(val, "strftime"):
            val = f"{val:%Y-%m-%d}"
        elif isinstance(val, float):
            val = f"{val:.4f}"
        rows.append([col, str(val)[:24]])
    return {"columns": ["field", "sealed value"], "rows": rows} if rows else None


@provider("regime_probability_bars")
def _regime_probs(args: dict, ctx: dict) -> dict | None:
    df = _pair_rows(ctx, args["pair"])
    cols = [c for c in ("p_calm", "p_trend", "p_chop", "p_crisis") if c in df.columns]
    if df.empty or not cols:
        return None
    last = df.iloc[-1]
    top = max(cols, key=lambda c: float(last[c]))
    rows = [
        {
            "label": c[2:],
            "value": float(last[c]),
            "display": f"{float(last[c]):.0%}",
            "tone": c[2:],
            "highlight": c == top,
        }
        for c in cols
    ]
    return {"rows": rows}


@provider("move_frequency_bars")
def _move_freq(args: dict, ctx: dict) -> dict | None:
    feats = ctx.get("features")
    if feats is None or "ret_1d" not in feats.columns:
        return None
    rets = feats[feats["pair"] == args["pair"]]["ret_1d"].dropna().abs()
    if rets.empty:
        return None
    band = float(args["size_band"].replace("pct", "")) / 100.0
    horizon = {"1pct": 1, "2pct": 5, "3pct": 10, "5pct": 21}[args["size_band"]]
    rolled = feats[feats["pair"] == args["pair"]]["ret_1d"].dropna().rolling(horizon).sum().abs()
    rows = []
    for label, series in (("in one day", rets), (f"over {horizon} days", rolled.dropna())):
        if series.empty:
            continue
        share = float((series >= band).mean())
        rows.append(
            {
                "label": label,
                "value": max(share, 1e-4),
                "display": f"{share:.1%}",
                "highlight": label == "in one day",
            }
        )
    if not rows:
        return None
    return {"rows": rows}


@provider("coverage_plot")
def _coverage(args: dict, ctx: dict) -> dict | None:
    cov = ctx.get("coverage") or {}
    per = ((cov.get("frozen_test") or {}).get("per_regime")) or {}
    if not per:
        return None
    target = 1 - float(cov.get("alpha", 0.1))
    pts = [{"v": round(float(v), 4), "d": k} for k, v in per.items() if v is not None]
    if not pts:
        return None
    return {
        "points": pts,
        "subline": f"coverage per regime against the {target:.0%} target · "
        f"overall {float((cov.get('frozen_test') or {}).get('overall', 0)):.1%}",
    }


@provider("storm_replay_mini")
def _storm(args: dict, ctx: dict) -> dict | None:
    replays = ctx.get("storms") or {}
    episode = args.get("episode") or next(iter(replays), None)
    ep = replays.get(episode) if episode else None
    if not ep:
        return None
    regimes = ctx["regimes"]
    df = regimes[
        (regimes["pair"] == ep.get("pair", "EURUSD"))
        & (regimes["date"] >= pd.Timestamp(ep["start"]))
        & (regimes["date"] <= pd.Timestamp(ep["end"]))
    ].sort_values("date")
    if df.empty:
        return None
    segs = _runs(df["date"], df["regime"])
    present = list(dict.fromkeys(s["tone"] for s in segs))
    return {
        "segments": [
            {
                "tone": s["tone"],
                "weight": s["weight"],
                "title": f"{s['tone']} {s['start']} → {s['end']}",
            }
            for s in segs
        ],
        "legend": [{"label": t} for t in present],
    }


@provider("faq_card")
def _faq(args: dict, ctx: dict) -> dict | None:
    rows = (ctx.get("faq") or {}).get(args.get("topic", ""))
    return {"columns": ["question", "answer"], "rows": rows} if rows else None


@provider("ask_your_bank_card")
def _ask_bank(args: dict, ctx: dict) -> dict | None:
    rows = ASK_BANK.get(args.get("topic", ""))
    return (
        {"columns": ["take these to your bank or adviser"], "rows": [[r] for r in rows]}
        if rows
        else None
    )


@provider("explainer_diagram")
def _diagram(args: dict, ctx: dict) -> dict | None:
    svg = (ctx.get("diagrams") or {}).get(args.get("diagram", ""))
    return {"svg": svg} if svg else None


@provider("methodology_flow")
def _flow(args: dict, ctx: dict) -> dict | None:
    svg = (ctx.get("diagrams") or {}).get("flow_" + args.get("metric", ""))
    return {"svg": svg} if svg else None


# Escalation content: the questions a treasurer should put to a licensed counterparty. Authored
# once, human-reviewed, and never generated — this card exists precisely because we do not advise.
ASK_BANK = {
    "forward": [
        "What all-in forward rate can you quote for my exact amount and value date?",
        "What is your margin over the interbank forward points, in basis points?",
        "What happens if my underlying cash flow arrives early or late?",
        "What credit line does this consume, and at what cost?",
    ],
    "option": [
        "What is the premium for a vanilla option at my strike, and what does it buy me?",
        "How does that premium compare with the forward's opportunity cost?",
        "What structures do you offer with no upfront premium, and what do I give up?",
    ],
    "spread": [
        "What spread am I paying on spot conversions today, in basis points?",
        "How does that spread widen on volatile days or outside business hours?",
        "What volume would earn a better tier?",
    ],
    "ladder": [
        "Can I execute a tranche schedule automatically, and at what cost per tranche?",
        "What is the minimum ticket size for each tranche?",
        "How would you evidence best execution across the tranches?",
    ],
    "policy": [
        "Does our hedging policy set a minimum and maximum cover ratio?",
        "Who signs off a change in cover, and how quickly can that happen?",
        "How is hedge effectiveness documented for the auditor?",
    ],
}


# ---------------------------------------------------------------------------------------------
# enumeration + build
# ---------------------------------------------------------------------------------------------
def arg_combinations(card: visuals.Card) -> list[dict]:
    """Every precomputable argument combination. Cards taking a user value are skipped — their
    input does not exist until someone asks."""
    combos: list[dict] = [{}]
    for name, spec in card.args.items():
        kind = spec.get("type")
        if kind == "from_user":
            return []
        values = spec.get("values")
        if kind == "enum" and values:
            combos = [dict(c, **{name: str(v)}) for c in combos for v in values]
        elif kind == "enum_list" or kind in ("key", "key_list"):
            combos = [dict(c) for c in combos]  # single default instance
    return combos


def key_for(card_id: str, args: dict) -> str:
    return card_id + ("|" + ",".join(f"{k}={args[k]}" for k in sorted(args)) if args else "")


def build(ctx: dict, registry: visuals.Registry | None = None) -> dict:
    reg = registry or visuals.load_registry()
    pack = ctx["pack"]
    cards: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    every_market = all_markets(ctx)
    for card in reg.built():
        fn = PROVIDERS.get(card.id)
        if fn is None:
            skipped[card.id] = "no provider yet"
            continue
        combos = arg_combinations(card)
        # Cards that only need a pair's published block work for all 23 markets, not just the three
        # majors the registry enum lists — the enum bounds what the MODEL may ask for; the artifact
        # may carry more, and a question about the yen deserves the same card as one about the euro.
        if card.id in ("condition_card", "siren_gauge") and combos:
            combos = [{"pair": p} for p in every_market]
        for args in combos:
            try:
                data = fn(args, ctx)
            except Exception as exc:  # noqa: BLE001 — one bad card must not fail the pipeline
                log.warning("card %s%s failed to resolve: %s", card.id, args, exc)
                skipped[card.id] = str(exc)
                continue
            if not data:
                skipped.setdefault(card.id, "no data for these arguments")
                continue
            extra = data.pop("_caption", {}) if isinstance(data, dict) else {}
            caption = visuals.caption_for(card, _caption_values(card, args, data, pack) | extra)
            if "{" in caption:  # a template the values could not fill is a build error, not a card
                log.warning("card %s%s caption left a placeholder: %s", card.id, args, caption)
                skipped.setdefault(card.id, "caption placeholder unresolved")
                continue
            cards[key_for(card.id, args)] = {
                "component": card.id,
                "primitive": card.primitive,
                "family": card.family,
                "title": card.id.replace("_", " "),
                "args": args,
                "caption": caption,
                "label": card.id.replace("_", " "),
                "asof": pack.get("data_through"),
                "data": data,
            }
    # A card counts as unavailable only when NO argument combination resolved; a glossary with five
    # of ten terms is a working card, not a broken one.
    resolved_ids = {c["component"] for c in cards.values()}
    unavailable = {cid: why for cid, why in skipped.items() if cid not in resolved_ids}
    return {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "registry_version": reg.version,
        "data_through": pack.get("data_through"),
        "cards": cards,
        # When a question names no market, the serving side should answer for the lead pair rather
        # than whichever key happens to sort first — an answer about AUDUSD to a question about
        # "today" is not wrong so much as arbitrary, which is worse.
        "default_args": {"pair": next(iter(pack.get("pairs") or {"EURUSD": {}}))},
        "partial": sorted(set(skipped) & resolved_ids),
        "not_resolved": unavailable,
    }


def _caption_values(card: visuals.Card, args: dict, data: dict, pack: dict) -> dict:
    """Caption templates read from the pack for pair-scoped cards; anything unresolved renders as
    an em dash rather than a stray brace."""
    values: dict[str, Any] = dict(args)
    metric = args.get("metric")
    if metric in METRIC_LABELS:
        values["metric"] = METRIC_LABELS[metric]
    pair = args.get("pair")
    if pair:
        p = (pack.get("pairs") or {}).get(pair) or {}
        if not p:  # G10, EM and crypto pairs live under the markets block
            for uni in (pack.get("markets") or {}).values():
                p = (uni.get("pairs") or {}).get(pair) or {}
                if p:
                    break
        values |= {
            "pair": p.get("label", pair),
            "word": p.get("regime"),
            "risk": f"{p['change_risk_5d']:.2f}" if p.get("change_risk_5d") is not None else None,
            "lo": f"{p['risk_lo']:.2f}" if p.get("risk_lo") is not None else None,
            "hi": f"{p['risk_hi']:.2f}" if p.get("risk_hi") is not None else None,
            "siren": f"{p['anomaly_pct']:.0f}" if p.get("anomaly_pct") is not None else None,
            "votes": p.get("agreement"),
            "days": p.get("days_in_regime"),
        }
    led = pack.get("ledger") or {}
    values.setdefault("days", led.get("days_live"))
    # "live Brier — " reads like a broken template; say what is actually true instead.
    values |= {
        "live": led.get("live_brier") if led.get("live_brier") is not None else "not scored yet",
        "frozen": led.get("frozen_brier"),
        "head": led.get("chain_head_short"),
        "n": led.get("n_forecasts"),
        "ok": led.get("chain_ok"),
        "asof": pack.get("data_through"),
    }
    for key in ("definition", "term", "metric", "window", "episode", "topic", "diagram"):
        values.setdefault(key, args.get(key, "—"))
    values.setdefault("regime", values.get("word", "—"))
    values.setdefault("stale", False)
    return {k: ("—" if v is None else v) for k, v in values.items()}


def build_index(registry: visuals.Registry | None = None) -> dict:
    """The retrieval index, exported for the Rust serving path (rule 11: data crosses, code does
    not). Rust mirrors `visuals._score`; `test_rust_python_retrieval_agree` pins them together."""
    reg = registry or visuals.load_registry()
    docs = {}
    for card in reg.built():
        text = (
            " ".join(card.intents())
            + " "
            + card.id.replace("_", " ")
            + " "
            + " ".join(card.caption.values())
        )
        norm = visuals._normalise(text)
        bag = visuals._expand(visuals._tokens(norm))
        docs[card.id] = {
            "text": norm,
            "tokens": dict(bag),
            "total": sum(bag.values()),
            "family": card.family,
            "tier": card.tier,
            "rivals": (card.disambiguation or {}).get("rivals") or [],
        }
    df: dict[str, int] = {}
    for d in docs.values():
        for tok in d["tokens"]:
            df[tok] = df.get(tok, 0) + 1
    return {
        "registry_version": reg.version,
        "n_docs": len(docs),
        "df": df,
        "docs": docs,
        "catch_alls": list(visuals.CATCH_ALLS),
        "top_k": visuals.TOP_K,
        "expansion": {k: sorted(v) for k, v in visuals._EXPANSION.items()},
        "pair_aliases": visuals.PAIR_ALIASES,
    }


def _context(ctx: dict) -> dict:
    """Gather the artifacts the providers read. I/O lives here, at the edge."""
    data = config.DATA_DIR
    out: dict[str, Any] = {
        "pack": ctx.get("avatar_context") or json.loads((data / "avatar_context.json").read_text()),
        "regimes": (
            ctx.get("regimes")
            if ctx.get("regimes") is not None
            else pd.read_parquet(data / "regimes.parquet")
        ),
    }
    for name, key in (("features.parquet", "features"),):
        path = data / name
        if path.exists():
            out[key] = pd.read_parquet(path)
    for name, key in (
        ("treasury_risk.json", "treasury"),
        ("status.json", "status"),
        ("decision_table.json", "decision"),
    ):
        path = data / name
        if path.exists():
            out[key] = json.loads(path.read_text())
    ledger = data / "ledger.parquet"
    if ledger.exists():
        out["ledger_tail"] = pd.read_parquet(ledger).tail(40)
    out["glossary"] = _glossary_terms()
    cov = data / "conformal_coverage.json"
    if cov.exists():
        out["coverage"] = json.loads(cov.read_text())
    storms = data / "storm_replays.json"
    if storms.exists():
        raw = json.loads(storms.read_text())
        out["storms"] = dict(raw) if isinstance(raw, dict) else {e["id"]: e for e in raw}
    out["faq"] = _faq_topics()
    out["diagrams"] = _diagrams()
    return out


def _faq_topics() -> dict[str, list[list[str]]]:
    """Product answers, taken verbatim from the knowledge pack the presenter already speaks."""
    path = config.ROOT / "docs" / "avatar_knowledge.md"
    if not path.exists():
        return {}
    import re as _re

    blocks = _re.findall(
        r"^### Q: (?P<q>.+?)\n(?P<a>.*?)(?=^### Q: |^## |\Z)", path.read_text(), _re.M | _re.S
    )
    topics = {
        "pricing": ["tier", "cost", "franc"],
        "tiers": ["tier"],
        "alerts": ["alert"],
        "api": ["api", "partner"],
        "data": ["data"],
        "privacy": ["transcript", "privacy"],
    }
    out: dict[str, list[list[str]]] = {}
    for topic, words in topics.items():
        rows = [
            [q.strip(), " ".join(a.split())[:160]]
            for q, a in blocks
            if any(w in (q + a).lower() for w in words)
        ]
        if rows:
            out[topic] = rows[:4]
    return out


def _diagrams() -> dict[str, str]:
    """Pre-authored SVGs from docs/diagrams — server-side assets, never user input."""
    folder = config.ROOT / "docs" / "diagrams"
    if not folder.exists():
        return {}
    return {p.stem: p.read_text() for p in folder.glob("*.svg")}


def _glossary_terms() -> dict[str, str]:
    """The glossary paragraph of the knowledge pack, split into terms."""
    path = config.ROOT / "docs" / "avatar_knowledge.md"
    if not path.exists():
        return {}
    text = path.read_text()
    start = text.find("## Glossary")
    if start < 0:
        return {}
    body = " ".join(text[start:].split("\n## ")[0].splitlines()[1:])
    out: dict[str, str] = {}
    # the glossary is written as "Term: definition. Term: definition." across wrapped lines
    import re as _re

    for match in _re.finditer(
        r"([A-Z][A-Za-z -]{2,20}):\s*(.+?)(?=(?:[A-Z][A-Za-z -]{2,20}:)|$)", body
    ):
        term, definition = match.group(1).strip().lower(), " ".join(match.group(2).split())
        out[term] = definition.rstrip() if definition.endswith(".") else definition + "."
    return out


def stage(ctx: dict) -> None:
    """run_daily stage (after avatar + decision): resolve every card the artifacts can fill."""
    if "avatar_context" not in ctx:
        return
    bundle = _context(ctx)
    boards = build(bundle)
    index = build_index()
    ctx["visual_boards"], ctx["visual_index"] = boards, index
    writers = ctx.setdefault("extra_writers", {})
    writers["visual_boards.json"] = lambda c: BOARDS_PATH.write_text(
        json.dumps(c["visual_boards"], indent=1)
    )
    writers["visual_index.json"] = lambda c: INDEX_PATH.write_text(
        json.dumps(c["visual_index"], indent=1)
    )
    log.info(
        "visual boards: %d cards resolved, %d cards without data",
        len(boards["cards"]),
        len(boards["not_resolved"]),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    bundle = _context({})
    boards, index = build(bundle), build_index()
    BOARDS_PATH.write_text(json.dumps(boards, indent=1))
    INDEX_PATH.write_text(json.dumps(index, indent=1))
    print(f"wrote {BOARDS_PATH.name}: {len(boards['cards'])} resolved cards")
    print(f"wrote {INDEX_PATH.name}: {index['n_docs']} indexed cards")
    if boards["not_resolved"]:
        print("no data yet for:", ", ".join(sorted(boards["not_resolved"])))


if __name__ == "__main__":
    main()
