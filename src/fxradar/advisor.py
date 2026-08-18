"""Advisor: market stability, regime durability, risk budgets, and grounded Q&A.

What this module deliberately is NOT: a direction call. Nothing here says buy or sell (CLAUDE.md
rules 4, 5). It answers the questions the models can answer honestly — how STABLE is each market
right now, how DURABLE is the current regime, how MUCH of your own normal risk it is reasonable to
carry, and how that risk could be split across markets — all from the filtered, causal artifacts,
with the reasoning shown. The Q&A helper lets an LLM answer free questions using ONLY a JSON
snapshot of those numbers (never the web, never its own market opinions), with a template fallback.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from fxradar import config, narrate

log = logging.getLogger(__name__)

# ---- Market Stability Index: transparent weights, documented on the Methodology page -----------
# Each component is a 0..1 "instability" signal; the index is 100 x (1 - weighted mean).
STABILITY_WEIGHTS = {
    "regime": 0.35,  # P(crisis) + 0.5 P(chop) from the filtered probabilities (regime_prob proxy)
    "change_risk": 0.20,  # 5-day regime-change probability
    "siren": 0.20,  # anomaly percentile above 80 scaled to 0..1
    "vol_front": 0.15,  # vol_ratio above 1 (recent vol vs the season)
    "entropy": 0.10,  # HMM entropy / ln(4): how unsure the regime model is
}
STABILITY_WORDS = [(75, "Fair"), (55, "Unsettled"), (35, "Stormy"), (0, "Severe")]
REGIME_INSTABILITY = {"calm": 0.0, "trend": 0.35, "chop": 0.55, "crisis": 1.0}
DEFAULT_TARGET_VOL = 0.10  # the "normal risk" a beginner's calculator assumes (10 % annualised)


def stability_word(score: float) -> str:
    for threshold, word in STABILITY_WORDS:
        if score >= threshold:
            return word
    return "Severe"


def stability_components(row: pd.Series) -> dict[str, float]:
    """0..1 instability components from one regimes+features row (all causal, all from artifacts)."""
    regime = str(row.get("regime", "calm"))
    p = float(row.get("regime_prob", 1.0))
    # blend the label's instability with the residual probability mass (spread across other states)
    reg = REGIME_INSTABILITY.get(regime, 0.5) * p + 0.5 * (1.0 - p)
    risk = float(row.get("change_risk_5d", 0.0) or 0.0)
    pct = float(row.get("anomaly_pct", 0.0) or 0.0)
    siren = max(0.0, min(1.0, (pct - 80.0) / 20.0))
    vr = float(row.get("vol_ratio", 1.0) or 1.0)
    vol_front = max(0.0, min(1.0, (vr - 1.0) / 1.5))
    ent = float(row.get("hmm_entropy", 0.0) or 0.0) / math.log(4)
    return {
        "regime": reg,
        "change_risk": risk,
        "siren": siren,
        "vol_front": vol_front,
        "entropy": max(0.0, min(1.0, ent)),
    }


def stability_index(row: pd.Series) -> tuple[float, dict[str, float]]:
    """0 (severe) .. 100 (fair) with its components."""
    comps = stability_components(row)
    instab = sum(STABILITY_WEIGHTS[k] * v for k, v in comps.items())
    return round(100.0 * (1.0 - instab), 1), comps


def expected_regime_duration(transmat_diag: float) -> float:
    """Geometric mean duration of a regime whose self-transition probability is p: 1 / (1 - p) days."""
    return float("inf") if transmat_diag >= 1.0 else 1.0 / (1.0 - transmat_diag)


def durability(row: pd.Series, self_prob: float | None) -> dict:
    """How long regimes like this typically last vs how long this one has lasted (memoryless: the
    HMM does not think a long run is 'due' to end — that is the honest answer)."""
    days = int(row.get("days_in_regime", 0) or 0)
    if self_prob is None:
        return {
            "days_in_regime": days,
            "typical_days": None,
            "note": "typical duration unavailable",
        }
    typical = expected_regime_duration(self_prob)
    return {
        "days_in_regime": days,
        "typical_days": round(typical, 1),
        "self_prob": round(float(self_prob), 4),
        "note": (
            f"regimes like this typically last about {typical:.0f} days; this one is on day {days}. "
            "The model is memoryless: a long run is not 'due' to end — the change-risk gauge, not the age, carries that information."
        ),
    }


# ---- risk budget: how much of YOUR normal risk, never which way --------------------------------
def risk_budget(row: pd.Series) -> dict:
    """Fraction (0..1) of a user's normal position size the models justify right now, with reasons.
    Mirrors the phase-15 overlay: scale by (1 - change_risk) above 0.30, stop on the siren (> 98),
    halve in crisis, and never exceed 1.0. Direction is not part of this — by design."""
    reasons: list[str] = []
    budget = 1.0
    regime = str(row.get("regime", "calm"))
    risk = float(row.get("change_risk_5d", 0.0) or 0.0)
    pct = float(row.get("anomaly_pct", 0.0) or 0.0)
    if pct > 98:
        budget = 0.0
        reasons.append(
            f"siren stop: today looks unlike any calm day the model learnt from (anomaly percentile {pct:.0f} > 98) → stand aside"
        )
    else:
        if regime == "crisis":
            budget *= 0.5
            reasons.append("crisis regime: half size — storms are when sizing mistakes hurt most")
        elif regime == "chop":
            budget *= 0.8
            reasons.append("chop regime: 80 % — directionless conditions punish conviction")
        if risk > 0.30:
            budget *= 1.0 - risk
            reasons.append(f"regime-change risk {risk:.0%} > 30 % → scale by (1 − risk)")
        else:
            reasons.append(f"regime-change risk {risk:.0%} is low → no reduction for change risk")
        if pct > 90:
            budget *= 0.7
            reasons.append(f"siren elevated (percentile {pct:.0f}) → 70 %")
    budget = float(max(0.0, min(1.0, budget)))
    return {"budget": round(budget, 3), "reasons": reasons}


def allocation(rows: dict[str, pd.Series], vols: dict[str, float]) -> dict[str, float]:
    """Split a unit of risk across markets: inverse realised vol × each market's risk budget,
    normalised (so a stopped market gets 0 and the rest share). Returns weights summing to ≤ 1."""
    raw = {}
    for pair, row in rows.items():
        v = float(vols.get(pair, 0.0) or 0.0)
        raw[pair] = (risk_budget(row)["budget"] / v) if v > 0 else 0.0
    total = sum(raw.values())
    if total <= 0:
        return {p: 0.0 for p in rows}
    return {p: round(x / total, 3) for p, x in raw.items()}


def sizing(capital: float, target_vol: float, asset_vol: float, budget: float) -> dict:
    """Beginner calculator: notional exposure that runs the account at `target_vol` × budget given
    the market's realised annualised vol. Notional = capital × (target_vol / asset_vol) × budget."""
    if asset_vol <= 0:
        return {"notional": 0.0, "leverage": 0.0}
    lev = min(2.0, target_vol / asset_vol) * budget
    return {
        "notional": round(capital * lev, 2),
        "leverage": round(lev, 3),
        "cap_note": "leverage capped at 2×",
    }


# ---- snapshot: the evidence base for the app and the Q&A -----------------------------------------
def snapshot(
    regimes: pd.DataFrame,
    features: pd.DataFrame,
    prices: pd.DataFrame,
    transmat_diag: dict[str, dict[str, float]] | None = None,
    as_of: pd.Timestamp | None = None,
    universe=None,
) -> dict:
    """Everything the Advisor page and the Q&A may know, as plain numbers, per market."""
    universe = universe or config.UNIVERSE
    as_of = as_of or regimes["date"].max()
    r = regimes[regimes["date"] <= as_of]
    f = features[features["date"] <= as_of]
    p = prices[prices["date"] <= as_of]
    markets, rows, vols = {}, {}, {}
    for pair in universe.pairs:
        rr = r[r["pair"] == pair].sort_values("date")
        ff = f[f["pair"] == pair].sort_values("date")
        if rr.empty or ff.empty:
            continue
        row = pd.concat(
            [
                rr.iloc[-1],
                ff.iloc[-1][
                    [
                        c
                        for c in ["vol_20", "vol_60", "vol_ratio", "mom_20", "corr_20"]
                        if c in ff.columns
                    ]
                ],
            ]
        )
        rows[pair] = row
        vols[pair] = float(row.get("vol_20", 0.0) or 0.0)
        idx, comps = stability_index(row)
        diag = (transmat_diag or {}).get(pair, {}).get(str(row["regime"]))
        stats = narrate.build_stats(pair, r, None, p)
        markets[pair] = {
            "label": universe.display(pair),
            "date": str(pd.Timestamp(row["date"]).date()),
            "regime": str(row["regime"]),
            "regime_prob": round(float(row["regime_prob"]), 3),
            "days_in_regime": int(row["days_in_regime"]),
            "change_risk_5d": round(float(row.get("change_risk_5d", 0.0) or 0.0), 3),
            "top_drivers": (
                [str(x) for x in list(row["top_drivers"])]
                if "top_drivers" in row.index and row["top_drivers"] is not None
                else []
            ),
            "anomaly_pct": round(float(row.get("anomaly_pct", 0.0) or 0.0), 1),
            "vol_20": round(vols[pair], 4),
            "vol_ratio": round(float(row.get("vol_ratio", 1.0) or 1.0), 3),
            "corr_20": round(float(row.get("corr_20", 0.0) or 0.0), 3),
            "ret_5d_pct": stats["ret_5d_pct"],
            "stability": idx,
            "stability_word": stability_word(idx),
            "stability_components": {k: round(v, 3) for k, v in comps.items()},
            "durability": durability(row, diag),
            "risk_budget": risk_budget(row),
        }
    alloc = allocation(rows, vols) if rows else {}
    for pair, w in alloc.items():
        markets[pair]["allocation_weight"] = w
    overall = (
        round(float(np.mean([m["stability"] for m in markets.values()])), 1)
        if markets
        else float("nan")
    )
    return {
        "universe": universe.name,
        "universe_label": universe.label,
        "as_of": str(pd.Timestamp(as_of).date()),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_stability": overall,
        "overall_word": stability_word(overall) if markets else "n/a",
        "markets": markets,
        "weights": STABILITY_WEIGHTS,
        "target_vol_default": DEFAULT_TARGET_VOL,
    }


# ---- Q&A grounded in the snapshot ---------------------------------------------------------------
QA_SYSTEM = (
    "You are the Advisor of an educational market-weather dashboard for beginners. Answer the user's "
    "question using ONLY the JSON snapshot provided (computed numbers: regimes, stability, risk "
    "budgets, change risk, anomaly percentiles). Rules: never predict prices or direction, never say "
    "buy/sell/long/short, never recommend an instrument, never add facts not in the JSON, never use "
    "your own market knowledge or news. You may explain what a number means in plain words and how "
    "much of one's own normal risk the models justify (the risk_budget field) and why. Keep it to at "
    "most five short sentences, then a line 'Evidence:' listing the JSON fields you used. If the "
    "question cannot be answered from the JSON, say so and point to the Methodology page."
)
GLOSSARY = {
    "regime": "the market's current 'weather' as one of calm, trend, chop, crisis, inferred causally by a hidden Markov model",
    "stability": "0–100: 100 is a fair, quiet market; below 35 is stormy — a weighted mix of regime, change risk, the siren, the volatility front and model uncertainty",
    "change risk": "the model's calibrated probability that the regime label is different at some point in the next five trading days",
    "siren": "how unusual today looks compared with calm history — an anomaly percentile from an autoencoder",
    "risk budget": "how much of YOUR normal position size the models justify right now — never which direction",
}


def template_answer(question: str, snap: dict) -> str:
    """Deterministic answers for the common questions, from the snapshot only."""
    q = (question or "").lower()
    ms = snap.get("markets", {})
    if not ms:
        return "No data for this universe yet. Evidence: markets = {}"
    best = max(ms.values(), key=lambda m: m["stability"])
    worst = min(ms.values(), key=lambda m: m["stability"])
    if any(w in q for w in ["mean", "what is", "explain", "define"]):
        for key, text in GLOSSARY.items():
            if key in q:
                return f"{key.capitalize()}: {text}. Evidence: glossary."
    if any(w in q for w in ["stable", "stability", "calm", "safe", "risky", "weather", "how is"]):
        parts = [
            f"Overall stability is {snap['overall_stability']:.0f}/100 ({snap['overall_word']}) as of {snap['as_of']}."
        ]
        parts.append(
            f"The steadiest market is {best['label']} at {best['stability']:.0f} ({best['regime']} regime, change risk {best['change_risk_5d']:.0%}); the least steady is {worst['label']} at {worst['stability']:.0f} ({worst['regime']}, siren percentile {worst['anomaly_pct']:.0f})."
        )
        parts.append(
            "Stability describes conditions, not direction — it says how carefully to size, not what to buy."
        )
        return (
            " ".join(parts)
            + " Evidence: overall_stability, markets[*].stability, regime, change_risk_5d, anomaly_pct."
        )
    if any(
        w in q for w in ["how much", "size", "budget", "allocate", "invest", "position", "risk"]
    ):
        lines = [
            f"The models justify these fractions of your normal position size right now ({snap['as_of']}):"
        ]
        for m in ms.values():
            lines.append(
                f"{m['label']}: {m['risk_budget']['budget']:.0%} of normal size (allocation weight {m.get('allocation_weight', 0):.0%}) — {m['risk_budget']['reasons'][0] if m['risk_budget']['reasons'] else 'no reduction'}."
            )
        lines.append(
            "This is a risk budget, not a direction: the models never say which way. Use the calculator on the Advisor page to turn it into a notional for your own capital and volatility target."
        )
        return " ".join(lines) + " Evidence: markets[*].risk_budget, allocation_weight."
    if any(
        w in q
        for w in ["buy", "sell", "long", "short", "go up", "go down", "price", "predict", "will"]
    ):
        return "I can't answer that: this tool never predicts price direction or recommends buying or selling — by design (see Methodology). What it can tell you is how stable each market is and how much of your normal risk the models justify. Evidence: none used."
    return (
        f"Snapshot as of {snap['as_of']}: overall stability {snap['overall_stability']:.0f}/100 ({snap['overall_word']}); "
        + "; ".join(
            f"{m['label']} {m['regime']} (stability {m['stability']:.0f}, risk budget {m['risk_budget']['budget']:.0%})"
            for m in ms.values()
        )
        + ". Ask about stability, risk budget, or what a term means. Evidence: overall_stability, markets[*]."
    )


def answer(question: str, snap: dict, api_key: str | None = None) -> tuple[str, str]:
    """(text, source) — LLM grounded in the snapshot when a key exists, else the template. Never raises."""
    question = (question or "").strip()[:500]
    try:
        import anthropic

        key = api_key or narrate.get_api_key()
        if not key:
            raise RuntimeError("no key")
        client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=30.0)
        payload = {"question": question, "snapshot": snap, "glossary": GLOSSARY}
        resp = client.messages.create(
            model=narrate.MODEL,
            max_tokens=450,
            temperature=0.2,
            system=QA_SYSTEM,
            messages=[
                {"role": "user", "content": json.dumps(payload, sort_keys=True, default=str)}
            ],
        )
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            raise RuntimeError("empty")
        return text, "llm"
    except Exception as exc:
        log.info("advisor Q&A fallback to template: %s", type(exc).__name__)
        return template_answer(question, snap), "template"
