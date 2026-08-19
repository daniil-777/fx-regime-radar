"""Mondrian (per-regime) split conformal intervals on the 5-day change risk + coverage tracker.

Every probability we publish wears an error bar. Split conformal, hand-rolled:
  * calibration set = the 2017–2018 VALIDATION years (embargoed, same split code as the
    forecaster). HONEST NOTE: these years also chose the forecaster's early-stopping round and
    decision threshold — a documented dual use. The 2019+ test is never touched here; it is
    scored once, for the coverage receipt below.
  * nonconformity = |realized outcome − predicted probability| on calibration rows;
  * per regime r (Mondrian): q_r = the ceil((n_r+1)(1−α))/n_r empirical quantile, α = 0.1;
  * interval = [p̂ − q_r, p̂ + q_r] clipped to [0, 1].
Time series violate exchangeability, so we do NOT cite the theorem's guarantee anywhere
user-facing; we report EMPIRICAL coverage — on the frozen test once, and live as ledger rows
mature (the kinship is with VaR coverage backtesting: promised 90 %, count the hits).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import config, forecaster

log = logging.getLogger(__name__)

ALPHA = 0.10  # 90 % nominal
REGIMES = ["calm", "trend", "chop", "crisis"]
PARAMS_PATH = config.MODELS_DIR / "conformal_v1.json"
COVERAGE_PATH = config.DATA_DIR / "conformal_coverage.json"
INTERVAL_COLUMNS = ["risk_lo", "risk_hi", "conformal_q"]
MIN_CAL = 30  # below this many calibration rows a regime borrows the pooled quantile


def conformal_quantile(scores: np.ndarray, alpha: float = ALPHA) -> float:
    """Finite-sample-corrected empirical quantile: the k-th smallest, k = ceil((n+1)(1-alpha))."""
    s = np.sort(np.asarray(scores, dtype=float))
    n = len(s)
    if n == 0:
        return float("nan")
    k = int(np.ceil((n + 1) * (1 - alpha)))
    return float(s[min(k, n) - 1])


def calibration_rows(regimes: pd.DataFrame) -> pd.DataFrame:
    """Validation rows (2017–2018, embargoed) with outcome labels — the calibration set."""
    m = regimes[["date", "pair", "regime", "change_risk_5d"]].copy()
    m["y"] = forecaster.build_labels(m)
    m["split"] = forecaster.assign_splits(m)
    cal = m[(m["split"] == "val") & m["y"].notna() & m["change_risk_5d"].notna()]
    assert cal["date"].min() >= pd.Timestamp(config.VAL_START), "calibration before VAL_START"
    assert cal["date"].max() <= pd.Timestamp(config.VAL_END), "calibration after VAL_END"
    return cal


def fit(regimes: pd.DataFrame, alpha: float = ALPHA) -> dict:
    """Per-regime q_r from the calibration rows (+ pooled fallback). Deterministic."""
    cal = calibration_rows(regimes)
    s = (cal["y"] - cal["change_risk_5d"]).abs().to_numpy()
    pooled = conformal_quantile(s, alpha)
    q: dict[str, float] = {}
    n: dict[str, int] = {}
    for r in REGIMES:
        mask = (cal["regime"] == r).to_numpy()
        n[r] = int(mask.sum())
        q[r] = conformal_quantile(s[mask], alpha) if n[r] >= MIN_CAL else pooled
    return {
        "alpha": alpha,
        "q": q,
        "n_cal": n,
        "q_pooled": pooled,
        "calibration": {
            "start": str(cal["date"].min().date()),
            "end": str(cal["date"].max().date()),
            "n": int(len(cal)),
            "note": (
                "2017–2018 validation years; also used for the forecaster's early stopping and "
                "threshold (documented dual use). The 2019+ test is untouched."
            ),
        },
    }


def apply(regimes: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Add risk_lo / risk_hi / conformal_q to `regimes` (rows untouched)."""
    params = params or load_params()
    q = regimes["regime"].map(params["q"]).astype(float)
    out = regimes.drop(columns=[c for c in INTERVAL_COLUMNS if c in regimes.columns]).copy()
    p = out["change_risk_5d"].astype(float)
    out["risk_lo"] = (p - q).clip(lower=0.0)
    out["risk_hi"] = (p + q).clip(upper=1.0)
    out["conformal_q"] = q
    return out


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float | None:
    """Fraction of realized outcomes inside [lo, hi] (None when empty)."""
    y, lo, hi = (np.asarray(a, dtype=float) for a in (y, lo, hi))
    ok = ~np.isnan(y) & ~np.isnan(lo) & ~np.isnan(hi)
    if not ok.any():
        return None
    return float(((y[ok] >= lo[ok]) & (y[ok] <= hi[ok])).mean())


def frozen_test_coverage(regimes: pd.DataFrame, params: dict) -> dict:
    """Empirical coverage on the frozen 2019+ test (overall + per regime) and a rolling series."""
    m = apply(regimes, params)[["date", "pair", "regime", "change_risk_5d", *INTERVAL_COLUMNS]]
    m["y"] = forecaster.build_labels(m)
    m["split"] = forecaster.assign_splits(m)
    te = m[(m["split"] == "test") & m["y"].notna()].sort_values("date")
    per_regime = {r: coverage(g["y"], g["risk_lo"], g["risk_hi"]) for r, g in te.groupby("regime")}
    te["inside"] = ((te["y"] >= te["risk_lo"]) & (te["y"] <= te["risk_hi"])).astype(float)
    rolling = te.groupby("date")["inside"].mean().rolling(120, min_periods=60).mean().dropna()
    return {
        "overall": coverage(te["y"], te["risk_lo"], te["risk_hi"]),
        "per_regime": per_regime,
        "n": int(len(te)),
        "test_start": str(te["date"].min().date()) if len(te) else None,
        "rolling_120d": {str(d.date()): round(float(v), 4) for d, v in rolling.items()},
    }


def live_coverage(ledger: pd.DataFrame) -> dict:
    """Coverage on matured ledger rows that carry an interval (live receipt)."""
    if ledger is None or not {"risk_lo", "risk_hi", "outcome"} <= set(ledger.columns):
        return {"n": 0, "coverage": None}
    m = ledger[ledger["outcome"].notna() & ledger["risk_lo"].notna()]
    return {"n": int(len(m)), "coverage": coverage(m["outcome"], m["risk_lo"], m["risk_hi"])}


def save_params(params: dict, path: Path = PARAMS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(params, indent=1))


def load_params(path: Path = PARAMS_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing — run `python -m fxradar.conformal --fit`")
    return json.loads(path.read_text())


def stage(ctx: dict) -> None:
    """run_daily stage: intervals onto ctx['regimes']; coverage receipt written in the write stage."""
    if PARAMS_PATH.exists():
        params = load_params()
    else:  # first run for this universe: calibrate on the validation years, persist
        params = fit(ctx["regimes"])
        save_params(params)
        log.info("conformal: calibrated on %s → %s", params["calibration"], PARAMS_PATH)
    ctx["regimes"] = apply(ctx["regimes"], params)
    ctx["conformal_params"] = params
    receipt = {
        "alpha": params["alpha"],
        "q": params["q"],
        "frozen_test": frozen_test_coverage(ctx["regimes"], params),
    }
    ctx["conformal_receipt"] = receipt
    ctx.setdefault("extra_writers", {})["conformal_coverage.json"] = (
        lambda c: COVERAGE_PATH.write_text(
            json.dumps({**c["conformal_receipt"], "live": live_coverage(c.get("ledger"))}, indent=1)
        )
    )
    latest = ctx["regimes"].sort_values("date").groupby("pair").tail(1)
    log.info(
        "conformal: %s",
        ", ".join(f"{r.pair} [{r.risk_lo:.2f}, {r.risk_hi:.2f}]" for r in latest.itertuples()),
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Mondrian conformal intervals on change risk")
    ap.add_argument("--fit", action="store_true", help="(re)calibrate on the validation years")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    regimes = pd.read_parquet(config.REGIMES_PATH)
    if args.fit or not PARAMS_PATH.exists():
        save_params(fit(regimes))
    params = load_params()
    print(json.dumps({k: v for k, v in params.items()}, indent=1))
    cov = frozen_test_coverage(regimes, params)
    print("frozen-test coverage:", cov["overall"], cov["per_regime"], "n =", cov["n"])


if __name__ == "__main__":
    main()
