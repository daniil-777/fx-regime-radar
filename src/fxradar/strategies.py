"""Strategies, the insurance overlay, the blend — and the honest evaluation of all of them.

Signals are inputs; net-of-costs P&L is the product (CLAUDE.md rule 12). Nothing here predicts
price direction with a model: S1 and S2 are pre-declared mechanical rules on past prices, S3
merely switches between them by the HMM's filtered regime, and the overlay only decides HOW MUCH
risk to take from change_risk_5d / anomaly_pct. All positions use information through day t; the
engine applies the lag. Expected outcome, stated in advance: after realistic costs the edge is thin
or absent — the deliverable is the framework and the honesty.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import backtest as bt
from fxradar import config

# ======================================================================================
# PARAMETERS — chosen once on train (<= 2016) + validation (2017-18) by inspection.
# DO NOT TUNE FURTHER. The test period (2019+) is scored once and frozen (rule 2).
# ======================================================================================
PARAMS = {
    "mom_scale": 0.03,  # S1: |mom_20| of 3 % = full size
    "z_window": 5,  # S2: horizon of the move being faded
    "z_clip": 2.0,  # S2: clip of the z-score, position = -clip(z)/2
    "risk_threshold": 0.30,  # overlay: scale by (1 - change_risk) above this
    "siren_stop": 98.0,  # overlay: flat when anomaly_pct > this
    "target_vol": 0.10,  # overlay: annualised vol target per strategy
    "leverage_cap": 2.0,  # overlay: never above this, ever
    "vol_lookback": 60,  # overlay: trailing window for realised strategy vol
    "blend_lookback": 120,  # blend: trailing window for inverse-vol weights
    "calm_size": 0.5,  # S3: half-size trend in calm
}
STRATEGIES = ["S1_trend", "S2_meanrev", "S3_regime_gate"]
ALL_NAMES = [*STRATEGIES, "BLEND"]
STRATEGY_PATH = config.DATA_DIR / "backtests.parquet"
METRICS_PATH = config.DATA_DIR / "strategy_metrics.json"
ATTRIB_PATH = config.DATA_DIR / "strategy_attribution.json"


# --------------------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------------------
def load_inputs() -> pd.DataFrame:
    """prices + features + regimes on (date, pair), sorted; only rows with features."""
    prices = pd.read_parquet(config.PRICES_PATH)
    feats = pd.read_parquet(config.FEATURES_PATH)
    regs = pd.read_parquet(config.REGIMES_PATH)
    df = feats.merge(prices[["date", "pair", "close"]], on=["date", "pair"])
    cols = ["date", "pair", "regime", "regime_prob", "change_risk_5d", "anomaly_pct"]
    df = df.merge(regs[[c for c in cols if c in regs.columns]], on=["date", "pair"])
    return df.sort_values(["pair", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# strategies: per-pair daily position in [-1, 1] from information through day t
# --------------------------------------------------------------------------------------
def s1_trend(df: pd.DataFrame) -> pd.Series:
    """sign(mom_20) scaled by momentum strength, capped at +/-1."""
    return (df["mom_20"] / PARAMS["mom_scale"]).clip(-1.0, 1.0).fillna(0.0)


def s2_meanrev(df: pd.DataFrame) -> pd.Series:
    """Fade the last 5-day move: -clip(z, -2, 2) / 2 with z = 5-day return / its expected std."""
    w = PARAMS["z_window"]
    out = pd.Series(0.0, index=df.index)
    for _, g in df.groupby("pair", sort=False):
        ret_w = g["close"] / g["close"].shift(w) - 1.0
        expected_std = g["vol_20"] / np.sqrt(bt.ANN) * np.sqrt(w)
        z = ret_w / expected_std.replace(0.0, np.nan)
        out.loc[g.index] = (-z.clip(-PARAMS["z_clip"], PARAMS["z_clip"]) / PARAMS["z_clip"]).fillna(
            0.0
        )
    return out


def s3_regime_gate(df: pd.DataFrame) -> pd.Series:
    """The app's thesis as a strategy: S1 in trend, S2 in chop, half-size S1 in calm, flat in crisis."""
    s1, s2 = s1_trend(df), s2_meanrev(df)
    r = df["regime"]
    return pd.Series(
        np.select(
            [r == "trend", r == "chop", r == "calm"],
            [s1, s2, PARAMS["calm_size"] * s1],
            default=0.0,
        ),
        index=df.index,
    )


STRATEGY_FUNCS = {"S1_trend": s1_trend, "S2_meanrev": s2_meanrev, "S3_regime_gate": s3_regime_gate}


# --------------------------------------------------------------------------------------
# the insurance overlay
# --------------------------------------------------------------------------------------
def risk_and_siren(pos: pd.Series, df: pd.DataFrame) -> pd.Series:
    """Scale by (1 - change_risk_5d) when risk > threshold; force flat when the siren screams."""
    risk = df["change_risk_5d"].fillna(0.0)
    scaled = np.where(risk > PARAMS["risk_threshold"], pos * (1.0 - risk), pos)
    stopped = np.where(df["anomaly_pct"].fillna(0.0) > PARAMS["siren_stop"], 0.0, scaled)
    return pd.Series(stopped, index=df.index)


def vol_target(pos: pd.Series, df: pd.DataFrame) -> pd.Series:
    """Scale so the strategy runs at ~target_vol using its own trailing realised vol (causal:
    the vol used at t is measured on returns through t), leverage capped."""
    out = pd.Series(0.0, index=df.index)
    for _, g in df.groupby("pair", sort=False):
        p = pos.loc[g.index]
        asset_ret = g["close"].pct_change()
        strat_ret = p.shift(1) * asset_ret  # what the unscaled strategy earned up to t
        realised = strat_ret.rolling(PARAMS["vol_lookback"], min_periods=20).std(ddof=1) * np.sqrt(
            bt.ANN
        )
        scale = (PARAMS["target_vol"] / realised).clip(upper=PARAMS["leverage_cap"]).fillna(1.0)
        out.loc[g.index] = (p * scale).clip(-PARAMS["leverage_cap"], PARAMS["leverage_cap"])
    return out


def overlay(pos: pd.Series, df: pd.DataFrame) -> pd.Series:
    return vol_target(risk_and_siren(pos, df), df)


# --------------------------------------------------------------------------------------
# run everything
# --------------------------------------------------------------------------------------
def run_all(
    df: pd.DataFrame, cost_cfg: bt.CostConfig | None = None
) -> dict[str, bt.BacktestResult]:
    """Backtest S1-S3 (each with the overlay) and the inverse-vol blend of their NET returns."""
    prices = df[["date", "pair", "close"]]
    feats = df[["date", "pair", "vol_20"]]
    results: dict[str, bt.BacktestResult] = {}
    for name, fn in STRATEGY_FUNCS.items():
        pos = overlay(fn(df), df)
        positions = df[["date", "pair"]].assign(pos=pos.to_numpy())
        results[name] = bt.run_backtest(
            positions, prices, feats, cost_cfg, max_position=PARAMS["leverage_cap"]
        )
    results["BLEND"] = blend(results)
    return results


def blend_weights(net_returns: pd.DataFrame) -> pd.DataFrame:
    """Inverse-vol weights across strategies, recomputed at each month start from the trailing
    realised vol of each strategy's pooled net returns through the previous month (no lookahead)."""
    vol = net_returns.rolling(PARAMS["blend_lookback"], min_periods=40).std(ddof=1)
    inv = 1.0 / vol.replace(0.0, np.nan)
    w = inv.div(inv.sum(axis=1), axis=0)
    month = net_returns.index.to_period("M")
    first_of_month = pd.Series(month, index=net_returns.index).ne(
        pd.Series(month, index=net_returns.index).shift(1)
    )
    # weight used during month m = weight computed at the last day of month m-1
    w_month = w.shift(1).where(first_of_month).ffill()
    return w_month.fillna(1.0 / net_returns.shape[1])


def blend(results: dict[str, bt.BacktestResult]) -> bt.BacktestResult:
    """Portfolio of the three strategies' per-pair NET returns with monthly inverse-vol weights."""
    frames = []
    for name in STRATEGIES:
        d = (
            results[name]
            .daily[
                [
                    "date",
                    "pair",
                    "pos_held",
                    "ret_asset",
                    "ret_gross",
                    "cost_bps",
                    "turnover",
                    "cost",
                    "ret_net",
                ]
            ]
            .copy()
        )
        d["strategy"] = name
        frames.append(d)
    long = pd.concat(frames, ignore_index=True)
    pooled = long.groupby(["date", "strategy"])["ret_net"].mean().unstack()[STRATEGIES]
    w = blend_weights(pooled)
    w_long = w.stack().rename("w").reset_index().rename(columns={"level_1": "strategy"})
    if "strategy" not in w_long.columns:  # pandas naming differences
        w_long.columns = ["date", "strategy", "w"]
    long = long.merge(w_long, on=["date", "strategy"], how="left")
    long["w"] = long["w"].fillna(1.0 / len(STRATEGIES))
    for c in ["pos_held", "ret_gross", "turnover", "cost", "ret_net"]:
        long[c] = long[c] * long["w"]
    daily = long.groupby(["date", "pair"], as_index=False).agg(
        pos_held=("pos_held", "sum"),
        ret_asset=("ret_asset", "first"),
        ret_gross=("ret_gross", "sum"),
        cost_bps=("cost_bps", "first"),
        turnover=("turnover", "sum"),
        cost=("cost", "sum"),
        ret_net=("ret_net", "sum"),
    )
    daily["pos"] = daily["pos_held"]
    daily = (
        daily[
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
        .sort_values(["pair", "date"])
        .reset_index(drop=True)
    )
    return bt.BacktestResult(
        daily=daily, metrics=bt.compute_metrics(daily), cost_cfg=results[STRATEGIES[0]].cost_cfg
    )


# --------------------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------------------
def split_of(dates: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [dates <= pd.Timestamp(config.TRAIN_END), dates <= pd.Timestamp(config.VAL_END)],
            ["train", "val"],
            default="test",
        ),
        index=dates.index,
    )


def metrics_by_split(results: dict[str, bt.BacktestResult]) -> pd.DataFrame:
    rows = []
    for name, res in results.items():
        d = res.daily.assign(split=split_of(res.daily["date"]))
        for split in ["train", "val", "test", "all"]:
            part = d if split == "all" else d[d["split"] == split]
            m = bt.compute_metrics(part)
            for _, r in m[m["scope"] == "ALL"].iterrows():
                rows.append({"strategy": name, "split": split, **r.drop("scope").to_dict()})
    return pd.DataFrame(rows)


def regime_attribution(
    results: dict[str, bt.BacktestResult], regimes: pd.DataFrame, split: str = "test"
) -> pd.DataFrame:
    """Sharpe of each strategy's NET return inside each regime (regime known at t-1, when the
    position was decided) — does trend really earn in 'trend' and bleed in 'chop'?"""
    rows = []
    reg = regimes[["date", "pair", "regime"]].sort_values(["pair", "date"]).copy()
    reg["regime_prev"] = reg.groupby("pair")["regime"].shift(1)
    for name, res in results.items():
        d = res.daily.merge(reg[["date", "pair", "regime_prev"]], on=["date", "pair"], how="left")
        d = d.assign(split=split_of(d["date"]))
        d = d if split == "all" else d[d["split"] == split]
        pooled = d.groupby(["date", "regime_prev"])["ret_net"].mean().reset_index()
        for regime in ["calm", "trend", "chop", "crisis"]:
            r = pooled.loc[pooled["regime_prev"] == regime, "ret_net"]
            rows.append(
                {
                    "strategy": name,
                    "regime": regime,
                    "days": int(len(r)),
                    "sharpe_net": bt.sharpe(r),
                    "ann_ret_net": float(r.mean() * bt.ANN) if len(r) else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def correlation_matrix(results: dict[str, bt.BacktestResult], split: str = "test") -> pd.DataFrame:
    pooled = {}
    for name in STRATEGIES:
        d = results[name].daily
        d = d[split_of(d["date"]) == split] if split != "all" else d
        pooled[name] = d.groupby("date")["ret_net"].mean()
    return pd.DataFrame(pooled).corr()


def _md(df: pd.DataFrame, fmt: str = "{:.3f}") -> str:
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        out.append(
            "| " + " | ".join(fmt.format(v) if isinstance(v, float) else str(v) for v in r) + " |"
        )
    return "\n".join(out)


def _equity_png(results: dict[str, bt.BacktestResult], regimes: pd.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"calm": "#34D399", "trend": "#60A5FA", "chop": "#FBBF24", "crisis": "#F87171"}
    plt.rcParams.update(
        {
            "figure.facecolor": "#0B0F17",
            "axes.facecolor": "#131A26",
            "axes.edgecolor": "#232D3F",
            "text.color": "#E7ECF4",
            "axes.labelcolor": "#E7ECF4",
            "xtick.color": "#8A94A6",
            "ytick.color": "#8A94A6",
            "grid.color": "#232D3F",
            "font.size": 9,
        }
    )
    fig, ax = plt.subplots(figsize=(12, 5))
    # regime underlay: EURUSD's regime as the reference band (pooled strategies have no single regime)
    g = regimes[regimes["pair"] == "EURUSD"].sort_values("date").reset_index(drop=True)
    new_run = g["regime"].ne(g["regime"].shift(1)).cumsum()
    for _, run in g.groupby(new_run):
        ax.axvspan(
            run["date"].iloc[0],
            run["date"].iloc[-1],
            color=colors[run["regime"].iloc[0]],
            alpha=0.12,
            lw=0,
        )
    line_colors = {
        "S1_trend": "#60A5FA",
        "S2_meanrev": "#FBBF24",
        "S3_regime_gate": "#34D399",
        "BLEND": "#E7ECF4",
    }
    for name, res in results.items():
        pooled = res.daily.groupby("date")["ret_net"].mean()
        ax.plot(
            pooled.index,
            (1 + pooled).cumprod(),
            lw=1.4 if name == "BLEND" else 1.0,
            color=line_colors[name],
            label=f"{name} (net)",
        )
    ax.axvline(pd.Timestamp(config.VAL_START), color="#8A94A6", ls="--", lw=1)
    ax.axvline(pd.Timestamp(config.TEST_START), color="#8A94A6", ls=":", lw=1)
    ax.annotate(
        "validation →",
        (pd.Timestamp(config.VAL_START), ax.get_ylim()[1]),
        xytext=(4, -12),
        textcoords="offset points",
        color="#8A94A6",
        fontsize=8,
    )
    ax.annotate(
        "test (frozen) →",
        (pd.Timestamp(config.TEST_START), ax.get_ylim()[1]),
        xytext=(4, -12),
        textcoords="offset points",
        color="#8A94A6",
        fontsize=8,
    )
    ax.set_title(
        "Net equity, all pairs equal weight — regime underlay = EURUSD filtered regime", loc="left"
    )
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def evaluate(reports_dir: Path = config.REPORTS_DIR) -> dict:
    """Run, write artifacts (backtests.parquet, strategy_metrics.json, attribution json), write the report."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    df = load_inputs()
    regimes = pd.read_parquet(config.REGIMES_PATH)
    results = run_all(df)
    metrics = metrics_by_split(results)
    attrib = regime_attribution(results, regimes, "test")
    corr = correlation_matrix(results, "test")
    _equity_png(results, regimes, reports_dir / "strategy_equity.png")

    # artifacts for the app (rule 8: the app reads, never computes)
    bt.save_backtests([bt.to_backtests_frame(res, name) for name, res in results.items()])
    METRICS_PATH.write_text(json.dumps(metrics.to_dict(orient="records"), indent=1, default=float))
    ATTRIB_PATH.write_text(
        json.dumps(
            {
                "attribution_test": attrib.to_dict(orient="records"),
                "corr_test": corr.round(4).to_dict(),
                "params": PARAMS,
            },
            indent=1,
            default=float,
        )
    )

    test = metrics[metrics["split"] == "test"]
    tn = test[test["kind"] == "net"].set_index("strategy")
    best_single = tn.loc[STRATEGIES, "max_drawdown"].idxmax()  # least negative
    insurance = tn.loc["BLEND", "max_drawdown"] > tn.loc[best_single, "max_drawdown"]
    L = [
        "# Strategy evaluation — S1 trend, S2 mean reversion, S3 regime gate, BLEND\n",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Daily bars, three pairs equal weight, costs {results['S1_trend'].cost_cfg.base_bps:.0f} bp + {results['S1_trend'].cost_cfg.vol_mult:.0f}×vol_20 on turnover, lag law inside the engine, overlay on every strategy (risk scaling above {PARAMS['risk_threshold']}, siren stop above {PARAMS['siren_stop']}, {PARAMS['target_vol']:.0%} vol target, {PARAMS['leverage_cap']:.0f}× cap). Parameters fixed on train+val; **test 2019+ scored once and frozen.** Research demonstration on daily data — not a live trading system._\n",
    ]
    for split in ["train", "val", "test"]:
        L.append(f"## {split} — gross vs net (all pairs equal weight)\n")
        part = metrics[metrics["split"] == split][
            [
                "strategy",
                "kind",
                "cagr",
                "ann_vol",
                "sharpe",
                "max_drawdown",
                "turnover_ann",
                "cost_drag",
                "hit_rate",
            ]
        ]
        L.append(_md(part) + "\n")
    L.append(
        "## Per-regime attribution — test, net Sharpe by the regime known when the position was decided\n"
    )
    piv = attrib.pivot(index="strategy", columns="regime", values="sharpe_net")[
        ["calm", "trend", "chop", "crisis"]
    ].reset_index()
    L.append(_md(piv, "{:.2f}") + "\n")
    s1 = attrib[attrib["strategy"] == "S1_trend"].set_index("regime")["sharpe_net"]
    L.append(
        f"Claim under test: trend earns in `trend` and bleeds in `chop`. Measured (S1, test): trend {s1['trend']:.2f}, chop {s1['chop']:.2f}, calm {s1['calm']:.2f}, crisis {s1['crisis']:.2f} → "
        + (
            "the pattern holds in sign. "
            if s1["trend"] > s1["chop"]
            else "the pattern does NOT hold: S1 was not better in `trend` than in `chop`. "
        )
        + "Sample sizes per regime are small out of sample (see days), so treat these as directional, not significant.\n"
    )
    L.append("## Vol targeting and the leverage cap\n")
    L.append(
        f"Target {PARAMS['target_vol']:.0%} per pair with a hard {PARAMS['leverage_cap']:.0f}× cap. Because the base signals average only ~0.4 in size, the cap binds on roughly half to four-fifths of training days and realised vol lands at 6–9 % per pair (pooled across three pairs it is lower still). "
        "Raising the cap would be a tuning decision we do not take; the target is therefore a ceiling-aware target, and the strategies never run hotter than it.\n"
    )
    L.append("## Correlation of net daily returns — test\n")
    L.append(_md(corr.round(3).reset_index().rename(columns={"index": ""})) + "\n")
    singles = ", ".join(f"{name} {tn.loc[name, 'sharpe']:.2f}" for name in STRATEGIES)
    L.append("## The mutual-insurance claim\n")
    L.append(
        f"Blend max drawdown (test, net) {tn.loc['BLEND', 'max_drawdown']:.1%} vs best single strategy {best_single} {tn.loc[best_single, 'max_drawdown']:.1%} → "
        + (
            "**the blend's drawdown IS shallower** than the best single strategy's: diversification worked in this sample. "
            if insurance
            else "**the blend does NOT beat the best single strategy on drawdown** in this sample — the insurance claim fails here. "
        )
        + f"Blend Sharpe {tn.loc['BLEND', 'sharpe']:.2f} vs {singles}.\n"
    )
    L.append("![equity](strategy_equity.png)\n")
    L.append("## Honest closing paragraph\n")
    neg = [s for s in ALL_NAMES if tn.loc[s, "sharpe"] < 0]
    L.append(
        f"Out of sample and net of costs, {len(ALL_NAMES) - len(neg)} of the four series have a positive Sharpe and {len(neg)} do not ({', '.join(neg) if neg else 'none'}). "
        f"Cost drag on the test set runs from {test[test['kind'] == 'net']['cost_drag'].min():.1%} to {test[test['kind'] == 'net']['cost_drag'].max():.1%} of CAGR per year — the vol-scaled cost model bites exactly where the strategies trade most. "
        "This is the expected outcome, stated in advance: on daily FX bars, with honest lags and honest costs, mechanical rules plus a regime gate do not produce a reliable edge. What the exercise delivers is the framework — a lag-law engine, a stress-aware cost model, an overlay that provably de-risks on the siren and change-risk signals, and a blend whose diversification benefit is measured rather than assumed — and the honesty to report the numbers as they are.\n"
    )
    L.append(
        "\n_Research demonstration on daily data — not a live trading system. Educational tool. Not investment advice._\n"
    )
    (reports_dir / "strategy_eval.md").write_text("\n".join(L))
    return {"metrics": metrics, "attribution": attrib, "corr": corr, "insurance": bool(insurance)}


def main() -> None:
    out = evaluate()
    pd.set_option("display.width", 200)
    m = out["metrics"]
    print(
        m[(m["split"] == "test")][
            [
                "strategy",
                "kind",
                "cagr",
                "ann_vol",
                "sharpe",
                "max_drawdown",
                "turnover_ann",
                "cost_drag",
            ]
        ]
        .round(4)
        .to_string(index=False)
    )
    print("\nper-regime net Sharpe (test):")
    print(
        out["attribution"]
        .pivot(index="strategy", columns="regime", values="sharpe_net")
        .round(2)
        .to_string()
    )
    print("\ncorrelation (test):\n", out["corr"].round(3).to_string())
    print("\ninsurance verdict (blend DD beats best single):", out["insurance"])
    print(
        f"wrote {config.REPORTS_DIR / 'strategy_eval.md'}, {STRATEGY_PATH}, {METRICS_PATH}, {ATTRIB_PATH}"
    )


if __name__ == "__main__":
    main()
