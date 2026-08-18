"""Cost-aware backtest engine — neutral plumbing that answers one question honestly:
after realistic frictions, does a position series make or lose money?

DAILY BARS ONLY. There is no intraday pretension here: a position is decided from information
up to the close of day t and earns the simple close-to-close return of day t+1.

THE LAG LAW lives INSIDE the engine (`run_backtest` shifts positions by one day itself), so no
caller can forget it. Costs scale with volatility — cost_bps_t = base_bps + vol_mult * vol_20_t —
so spreads widen exactly when markets are stressed, and are charged on turnover
|pos_t - pos_{t-1}| on the day the position actually changes. Every metric is reported gross AND
net; nothing is ever shown gross-only (CLAUDE.md rule 12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import config

ANN = 252.0
BACKTESTS_PATH = config.DATA_DIR / "backtests.parquet"


@dataclass(frozen=True)
class CostConfig:
    """cost_bps_t = base_bps + vol_mult * vol_20_t (vol_20 annualised, e.g. 0.06 = 6 %).

    Defaults: base 1 bp, vol_mult 80 → calm ≈ 5 bp, crisis ≈ 12–16 bp per unit of turnover
    (measured on the HMM's own regime means: crisis/calm ≈ 2.4× EURUSD, 3.1× GBPUSD, 8× USDCHF
    whose crisis state is the SNB shock). Deliberately on the expensive side of retail FX —
    a strategy that only works at zero cost is a finding, not a result.
    """

    base_bps: float = 1.0
    vol_mult: float = 80.0

    def cost_bps(self, vol_20: pd.Series) -> pd.Series:
        return self.base_bps + self.vol_mult * vol_20.fillna(vol_20.median())


@dataclass
class BacktestResult:
    daily: pd.DataFrame  # date, pair, pos, ret_asset, ret_gross, cost_bps, turnover, cost, ret_net
    metrics: pd.DataFrame  # one row per (pair | ALL) x (gross | net)
    cost_cfg: CostConfig = field(default_factory=CostConfig)


# --------------------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------------------
def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min()) if len(equity) else float("nan")


def cagr(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) == 0:
        return float("nan")
    growth = float((1.0 + r).prod())
    return growth ** (ANN / len(r)) - 1.0 if growth > 0 else -1.0


def sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    return (
        float(r.mean() / r.std(ddof=1) * np.sqrt(ANN))
        if len(r) > 1 and r.std(ddof=1) > 0
        else float("nan")
    )


def _metric_row(
    label: str,
    kind: str,
    ret: pd.Series,
    turnover: pd.Series,
    pos: pd.Series,
    gross_for_drag: pd.Series | None = None,
) -> dict:
    active = pos.abs() > 0
    return {
        "scope": label,
        "kind": kind,
        "cagr": cagr(ret),
        "ann_vol": float(ret.std(ddof=1) * np.sqrt(ANN)) if len(ret) > 1 else float("nan"),
        "sharpe": sharpe(ret),
        "max_drawdown": max_drawdown(ret),
        "turnover_ann": float(turnover.sum() * ANN / max(len(turnover), 1)),
        "cost_drag": (cagr(gross_for_drag) - cagr(ret)) if gross_for_drag is not None else 0.0,
        "hit_rate": float((ret[active] > 0).mean()) if active.any() else float("nan"),
        "days": int(len(ret)),
    }


def compute_metrics(daily: pd.DataFrame) -> pd.DataFrame:
    """Per pair and pooled equal-weight 'ALL', gross and net."""
    rows = []
    for pair, g in daily.groupby("pair", sort=True):
        rows.append(_metric_row(pair, "gross", g["ret_gross"], g["turnover"], g["pos"]))
        rows.append(_metric_row(pair, "net", g["ret_net"], g["turnover"], g["pos"], g["ret_gross"]))
    wide_g = daily.pivot(index="date", columns="pair", values="ret_gross")
    wide_n = daily.pivot(index="date", columns="pair", values="ret_net")
    wide_t = daily.pivot(index="date", columns="pair", values="turnover")
    wide_p = daily.pivot(index="date", columns="pair", values="pos")
    port_g, port_n = wide_g.mean(axis=1), wide_n.mean(axis=1)
    rows.append(_metric_row("ALL", "gross", port_g, wide_t.mean(axis=1), wide_p.abs().mean(axis=1)))
    rows.append(
        _metric_row("ALL", "net", port_n, wide_t.mean(axis=1), wide_p.abs().mean(axis=1), port_g)
    )
    return pd.DataFrame(rows)


def metrics_table(result: BacktestResult, scope: str = "ALL") -> pd.DataFrame:
    """Gross vs net side by side for one scope — the shape every report uses."""
    m = result.metrics[result.metrics["scope"] == scope].set_index("kind")
    cols = [
        "cagr",
        "ann_vol",
        "sharpe",
        "max_drawdown",
        "turnover_ann",
        "cost_drag",
        "hit_rate",
        "days",
    ]
    return m[cols].T


# --------------------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------------------
def run_backtest(
    positions: pd.DataFrame,
    prices: pd.DataFrame,
    features: pd.DataFrame,
    cost_cfg: CostConfig | None = None,
    *,
    _disable_lag_for_tests: bool = False,
) -> BacktestResult:
    """positions: date, pair, pos in [-1, 1] decided from information up to day t.

    The engine shifts positions by one day (the lag law) so a signal formed at close t earns the
    return of t+1; `_disable_lag_for_tests` exists ONLY so the foresight test can prove that the
    lag is what stops a cheating signal — never use it elsewhere.
    """
    cost_cfg = cost_cfg or CostConfig()
    px = prices[["date", "pair", "close"]].sort_values(["pair", "date"])
    px = px.assign(ret_asset=px.groupby("pair")["close"].pct_change())
    df = px.merge(positions[["date", "pair", "pos"]], on=["date", "pair"], how="left")
    df = df.merge(features[["date", "pair", "vol_20"]], on=["date", "pair"], how="left")
    df = df.sort_values(["pair", "date"]).reset_index(drop=True)
    df["pos"] = df["pos"].clip(-1.0, 1.0)
    df["pos"] = df.groupby("pair")["pos"].transform(lambda s: s.fillna(0.0))
    # positions held DURING day t = decision made at close t-1 (lag law)
    held = df["pos"] if _disable_lag_for_tests else df.groupby("pair")["pos"].shift(1).fillna(0.0)
    df["pos_held"] = held
    df["ret_gross"] = df["pos_held"] * df["ret_asset"].fillna(0.0)
    df["turnover"] = (df["pos_held"] - df.groupby("pair")["pos_held"].shift(1).fillna(0.0)).abs()
    df["cost_bps"] = cost_cfg.cost_bps(df["vol_20"])
    df["cost"] = df["turnover"] * df["cost_bps"] / 1e4
    df["ret_net"] = df["ret_gross"] - df["cost"]
    daily = df[
        [
            "date",
            "pair",
            "pos",
            "pos_held",
            "ret_asset",
            "ret_gross",
            "cost_bps",
            "turnover",
            "cost",
            "ret_net",
        ]
    ]
    return BacktestResult(daily=daily, metrics=compute_metrics(daily), cost_cfg=cost_cfg)


def to_backtests_frame(result: BacktestResult, strategy: str) -> pd.DataFrame:
    """Contract rows for data/backtests.parquet: date, strategy, pair, pos, ret_gross, ret_net, cost_bps."""
    d = result.daily
    return pd.DataFrame(
        {
            "date": d["date"],
            "strategy": strategy,
            "pair": d["pair"],
            "pos": d["pos_held"],
            "ret_gross": d["ret_gross"],
            "ret_net": d["ret_net"],
            "cost_bps": d["cost_bps"],
        }
    )


def save_backtests(frames: list[pd.DataFrame], path: Path = BACKTESTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).sort_values(["strategy", "pair", "date"]).to_parquet(
        path, index=False
    )


def always_long(prices: pd.DataFrame) -> pd.DataFrame:
    """The dummy strategy used to demonstrate the engine: +1 in every pair, every day."""
    return prices[["date", "pair"]].assign(pos=1.0)


def main() -> None:
    prices = pd.read_parquet(config.PRICES_PATH)
    feats = pd.read_parquet(config.FEATURES_PATH)
    prices = prices[prices["date"] >= feats["date"].min()]
    res = run_backtest(always_long(prices), prices, feats)
    pd.set_option("display.width", 160)
    print("== always-long, all pairs equal weight — gross vs net ==")
    print(metrics_table(res).round(4).to_string())
    print("\n== per pair, net ==")
    print(
        res.metrics[res.metrics["kind"] == "net"]
        .set_index("scope")[
            ["cagr", "ann_vol", "sharpe", "max_drawdown", "turnover_ann", "cost_drag"]
        ]
        .round(4)
        .to_string()
    )
    print(
        f"\ncost model: base {res.cost_cfg.base_bps} bp + {res.cost_cfg.vol_mult} x vol_20 → mean {res.daily['cost_bps'].mean():.1f} bp, max {res.daily['cost_bps'].max():.1f} bp"
    )
    save_backtests([to_backtests_frame(res, "always_long")])
    print(f"wrote {BACKTESTS_PATH}")


if __name__ == "__main__":
    main()
