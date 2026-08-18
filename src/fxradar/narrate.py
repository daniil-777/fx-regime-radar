"""Narrator: turns each pair's computed numbers into three plain-English sentences.

Guardrails (CLAUDE.md rules 4 and 9): the model sees ONLY a small JSON of computed statistics
and a fixed system prompt; it never analyses markets from memory, never predicts prices, never
advises. If the API key is missing or any call fails, a deterministic template writes the same
three sentences, and the artifact records source = "template". The Streamlit app never calls the
API — it reads data/report.json only.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fxradar import config

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"  # latest small Haiku-class model (exact ID; no date suffix)
TEMPERATURE = 0.3
MAX_TOKENS = 350
RETRIES = 2  # SDK retries with exponential backoff on 429/5xx/connection errors
SYSTEM_PROMPT = (
    "You are the narrator for an educational FX dashboard. Using ONLY the JSON provided, write "
    "exactly three sentences in calm, plain English: (1) the current regime, its confidence and "
    "age; (2) the 5-day regime-change risk and its top drivers, translated into ordinary words; "
    "(3) the anomaly status, mentioning the closest historical match only if anomaly_pct > 90. "
    "Never predict prices, never give advice, never add facts not present in the JSON, never use "
    "jargon without a plain-word gloss."
)
DRIVER_WORDS = {
    "vol_20": "recent volatility",
    "vol_60": "the three-month volatility backdrop",
    "vol_ratio": "how fast volatility is rising",
    "mom_20": "one-month momentum",
    "rng_hl": "the size of daily trading ranges",
    "corr_20": "how much the dollar is moving everything at once",
    "ret_5d_abs": "the size of the past week's move",
    "days_in_regime": "how long the current regime has lasted",
    "hmm_entropy": "how unsure the regime model is",
    "vol_trend": "the direction of volatility",
    "regime_trend": "being in a trend regime",
    "regime_chop": "being in a chop regime",
    "regime_crisis": "being in a crisis regime",
}
DRIVER_WORDS.update({f"pair_{p}": w for p, w in config.UNIVERSE.pair_words.items()})
REGIME_WORDS = {"calm": "calm", "trend": "trending", "chop": "choppy", "crisis": "crisis"}
REPORT_PATH = config.REPORT_PATH


# --------------------------------------------------------------------------------------
# stats: numbers only, no free text
# --------------------------------------------------------------------------------------
def build_stats(
    pair: str,
    regimes: pd.DataFrame | None = None,
    detail: pd.DataFrame | None = None,
    prices: pd.DataFrame | None = None,
) -> dict:
    """Latest computed numbers for one pair from the artifacts. Every value is a number, a date
    string, or a feature name — nothing free-form goes to the model."""
    regimes = pd.read_parquet(config.REGIMES_PATH) if regimes is None else regimes
    prices = pd.read_parquet(config.PRICES_PATH) if prices is None else prices
    r = regimes[regimes["pair"] == pair].sort_values("date").iloc[-1]
    px = prices[prices["pair"] == pair].sort_values("date")["close"]
    ret_5d = float(px.iloc[-1] / px.iloc[-6] - 1) if len(px) > 6 else 0.0
    nn_date = None
    if detail is None:
        detail_path = config.DATA_DIR / "siren_detail.parquet"
        detail = pd.read_parquet(detail_path) if detail_path.exists() else None
    if detail is not None:
        d = detail[(detail["pair"] == pair) & (detail["date"] == r["date"])]
        if len(d) and pd.notna(d.iloc[0]["nn_date"]):
            nn_date = str(pd.Timestamp(d.iloc[0]["nn_date"]).date())
    return {
        "pair": pair,
        "date": str(pd.Timestamp(r["date"]).date()),
        "regime": str(r["regime"]),
        "regime_prob": round(float(r["regime_prob"]), 3),
        "days_in_regime": int(r["days_in_regime"]),
        "change_risk_5d": round(float(r.get("change_risk_5d", float("nan"))), 3),
        "top_drivers": [str(x) for x in list(r["top_drivers"])] if "top_drivers" in r else [],
        "anomaly_pct": round(float(r.get("anomaly_pct", float("nan"))), 1),
        "nearest_neighbor_date": nn_date,
        "ret_5d_pct": round(100 * ret_5d, 2),
    }


# --------------------------------------------------------------------------------------
# deterministic template
# --------------------------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def template_narrate(stats: dict) -> str:
    """The same three sentences, written by an f-string. Always available, never wrong about facts."""
    pair = config.UNIVERSE.display(stats["pair"])  # EUR/USD, BTC/USD
    regime = stats["regime"]
    days = stats["days_in_regime"]
    s1 = (
        f"{pair} is in a {REGIME_WORDS.get(regime, regime)} regime ({regime}) with {_pct(stats['regime_prob'])} "
        f"confidence, now on day {days} of this regime."
    )
    risk = stats["change_risk_5d"]
    drivers = [DRIVER_WORDS.get(d, d.replace("_", " ")) for d in stats.get("top_drivers", [])[:3]]
    level = "low" if risk < 0.2 else ("moderate" if risk <= 0.4 else "elevated")
    drv = (
        f", driven mainly by {', '.join(drivers[:-1])} and {drivers[-1]}"
        if len(drivers) >= 2
        else (f", driven mainly by {drivers[0]}" if drivers else "")
    )
    s2 = f"The model puts the chance of a regime change within five trading days at {_pct(risk)}, which is {level}{drv}."
    pct = stats["anomaly_pct"]
    if pct > 98:
        s3 = f"Today looks highly unusual compared with calm history (anomaly percentile {pct:.0f})"
    elif pct > 90:
        s3 = f"Today looks somewhat unusual compared with calm history (anomaly percentile {pct:.0f})"
    else:
        s3 = (
            f"Nothing looks unusual today compared with calm history (anomaly percentile {pct:.0f})"
        )
    if pct > 90 and stats.get("nearest_neighbor_date"):
        s3 += f"; the closest historical match is {stats['nearest_neighbor_date']}."
    else:
        s3 += "."
    return f"{s1} {s2} {s3}"


# --------------------------------------------------------------------------------------
# LLM path
# --------------------------------------------------------------------------------------
def get_api_key() -> str | None:
    """ANTHROPIC_API_KEY from the environment, else Streamlit secrets; None if absent. Never logged."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:  # only works inside a Streamlit runtime with .streamlit/secrets.toml present
        import streamlit as st

        return st.secrets.get("ANTHROPIC_API_KEY")  # type: ignore[no-any-return]
    except Exception:
        return None


def narrate(stats: dict, api_key: str | None = None) -> str:
    """Three sentences from the model, given ONLY the stats JSON. Raises on any failure."""
    import anthropic

    key = api_key or get_api_key()
    if not key:
        raise RuntimeError("no ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=key, max_retries=RETRIES, timeout=30.0)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(stats, sort_keys=True)}],
    )
    text = " ".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("empty narration")
    return text


def narrate_with_fallback(stats: dict) -> tuple[str, str]:
    """(text, source) — source is 'llm' or 'template'. Never raises."""
    try:
        return narrate(stats), "llm"
    except Exception as exc:  # missing key, network, API error, empty text
        log.info("narrator fallback to template for %s: %s", stats.get("pair"), type(exc).__name__)
        return template_narrate(stats), "template"


# --------------------------------------------------------------------------------------
# artifact
# --------------------------------------------------------------------------------------
def build_report(
    pairs: list[str] | None = None,
    regimes: pd.DataFrame | None = None,
    detail: pd.DataFrame | None = None,
    prices: pd.DataFrame | None = None,
) -> dict:
    """{pair: {text, generated_at, source}} for every pair (contract of data/report.json)."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {}
    for pair in pairs or config.PAIRS:
        stats = build_stats(pair, regimes, detail, prices)
        text, source = narrate_with_fallback(stats)
        out[pair] = {"text": text, "generated_at": now, "source": source, "stats": stats}
    return out


def write_report(report: dict, path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    report = build_report()
    write_report(report)
    for pair, r in report.items():
        print(f"[{r['source']}] {pair}: {r['text']}")
    print(f"wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
