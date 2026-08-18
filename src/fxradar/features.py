"""Feature engine: strictly causal (no look-ahead) features computed per pair.

Every feature at day t is a function of rows <= t only (CLAUDE.md rule 1). The proof is
`tests/test_features.py::test_truncation_invariance`: recomputing on a truncated series must
reproduce the overlapping rows exactly. There is no centering/scaling here — models own their
scalers, fit on the training window only.

Base feature set (data contract) and the one-sentence rationale for each:
* ret_1d      log(close_t / close_{t-1}) — the raw daily move; everything else is built on it.
* vol_20      rolling 20-day std of ret_1d x sqrt(252) — the "current weather": realised vol.
* vol_60      rolling 60-day std x sqrt(252) — the "season": the slower vol backdrop.
* vol_ratio   (rolling 5-day std x sqrt(252)) / vol_60 — a "storm front": very recent vol
              versus the season; > 1 means conditions are deteriorating fast.
* mom_20      close.pct_change(20) — one-month drift; trend regimes show persistent sign.
* rng_hl      10-day mean of (high - low) / close — intraday range, a vol read that does not
              depend on close-to-close returns (Yahoo's close is a start-of-day snapshot).
* corr_20     mean of the two 20-day rolling correlations of this pair's ret_1d with the other
              two pairs' ret_1d — "is the dollar moving everything at once?" (a stress tell).
              Returns are first put on one sign convention (foreign currency vs USD: USDCHF's
              sign is flipped, see config.USD_BASE_PAIRS) so a dollar-driven day reads as HIGH
              correlation instead of +0.9 and -0.9 cancelling out in the mean.
* ret_5d_abs  |close.pct_change(5)| — magnitude of the one-week move, sign-free by design.

Warm-up: the first 60 rows per pair are dropped (vol_60 needs 60 returns; ret_1d needs one
prior close, so row 60 is the first fully-defined row). corr_20 keeps its own short warm-up
where fewer than 20 common trading days exist, and is NaN (never a stale value) if a 20-day
window has zero variance. Rolling std uses pandas' default ddof=1 (sample std).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import config

ANNUALIZE = np.sqrt(float(config.TRADING_DAYS))  # sqrt(252) for FX, sqrt(365) for 7-day markets
WARMUP_ROWS = 60

BASE_FEATURES: list[str] = [
    "ret_1d",
    "vol_20",
    "vol_60",
    "vol_ratio",
    "mom_20",
    "rng_hl",
    "corr_20",
    "ret_5d_abs",
]
FEATURE_COLUMNS: list[str] = ["date", "pair", *BASE_FEATURES]


def _single_pair_features(g: pd.DataFrame) -> pd.DataFrame:
    """All per-pair features that need only this pair's own history. `g` is sorted by date."""
    close = g["close"]
    ret_1d = np.log(close / close.shift(1))
    out = pd.DataFrame({"date": g["date"], "pair": g["pair"]})
    out["ret_1d"] = ret_1d
    out["vol_20"] = ret_1d.rolling(20).std() * ANNUALIZE
    out["vol_60"] = ret_1d.rolling(60).std() * ANNUALIZE
    out["vol_ratio"] = (ret_1d.rolling(5).std() * ANNUALIZE) / out["vol_60"]
    out["mom_20"] = close.pct_change(20)
    out["rng_hl"] = ((g["high"] - g["low"]) / close).rolling(10).mean()
    out["ret_5d_abs"] = close.pct_change(5).abs()
    return out


def _cross_pair_corr(ret_wide: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Mean of the rolling correlations of each pair's ret_1d with the other pairs' ret_1d.

    `ret_wide` is indexed by the union of dates with one column per pair (NaN where a pair
    did not trade). USD-base pairs are sign-flipped first so every column is "foreign currency
    vs USD". Each pairwise correlation is computed on the dates BOTH pairs traded (so a
    "20-day window" is 20 common trading days) and then aligned as-of (backward, causal) onto
    the pair's own dates; a hole in pair C therefore only freezes the A-C component while the
    A-B component keeps updating. The mean is over the components defined on that date (a pair
    that starts later contributes nothing until it exists); NaN only when none is defined.
    """
    ret_wide = ret_wide.copy()
    for pair in config.USD_BASE_PAIRS:
        if pair in ret_wide.columns:
            ret_wide[pair] = -ret_wide[pair]
    cols = list(ret_wide.columns)
    out = pd.DataFrame(index=ret_wide.index)
    for a in cols:
        own_dates = ret_wide[a].dropna().index
        comps = []
        for b in cols:
            if b == a:
                continue
            both = ret_wide[[a, b]].dropna(how="any")
            comp = both[a].rolling(window).corr(both[b])
            comps.append(comp.reindex(own_dates, method="ffill"))  # as-of backward: past only
        # mean over the components that exist on that date (a pair with a shorter history simply
        # contributes nothing until it starts); NaN only when no component is defined
        out[a] = pd.concat(comps, axis=1).mean(axis=1, skipna=True).reindex(ret_wide.index)
    return out


def build_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute the base feature set per pair from tidy prices.

    Returns one row per (date, pair) with FEATURE_COLUMNS, first WARMUP_ROWS rows per pair
    dropped. Only past and current rows feed each value.
    """
    prices = prices.sort_values(["pair", "date"], kind="stable").reset_index(drop=True)
    parts = [_single_pair_features(g) for _, g in prices.groupby("pair", sort=True)]
    feats = pd.concat(parts, ignore_index=True)

    # cross-pair correlation, long format WITH NaN rows kept (a NaN must stay NaN, never be
    # replaced by a stale value), merged back on (date, pair)
    ret_wide = feats.pivot(index="date", columns="pair", values="ret_1d")
    corr = _cross_pair_corr(ret_wide)
    corr_long = corr.reset_index().melt(id_vars="date", var_name="pair", value_name="corr_20")
    feats = feats.merge(corr_long, on=["date", "pair"], how="left")

    feats = feats.sort_values(["pair", "date"], kind="stable")
    feats = feats[feats.groupby("pair").cumcount() >= WARMUP_ROWS]  # drop warm-up rows per pair
    return feats[FEATURE_COLUMNS].reset_index(drop=True)


def nan_report(feats: pd.DataFrame) -> pd.Series:
    """NaN count per feature column (post warm-up, only corr_20's own warm-up is expected)."""
    return feats[BASE_FEATURES].isna().sum()


def save_features(feats: pd.DataFrame, path: Path = config.FEATURES_PATH) -> None:
    """Write data/features.parquet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(path, index=False)


def load_features(path: Path = config.FEATURES_PATH) -> pd.DataFrame:
    """Read data/features.parquet."""
    return pd.read_parquet(path)


def main() -> None:
    """CLI: prices.parquet -> features.parquet, with shape and NaN report."""
    prices = pd.read_parquet(config.PRICES_PATH)
    feats = build_features(prices)
    save_features(feats)
    print(f"features: {feats.shape[0]} rows x {feats.shape[1]} cols -> {config.FEATURES_PATH}")
    print("rows per pair:", feats.groupby("pair").size().to_dict())
    print("date range:", feats["date"].min().date(), "->", feats["date"].max().date())
    print("\nNaN report (post warm-up):")
    print(nan_report(feats).to_string())


if __name__ == "__main__":
    main()
