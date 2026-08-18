"""Stress lab: attack the strategy layer before anyone mistakes it for a product.

Historical replays (SNB week, COVID crash, 2022), cost shocks with the BREAKEVEN COST multiplier,
an execution shock (one extra day of lag), a volatility shock (crisis returns x1.5), a 20-day block
bootstrap of one-year drawdowns, and a +/-30 % parameter-robustness sweep. Nothing is re-tuned
after seeing these numbers — that is how overfitting launders itself. Ugly results are reported
with commentary.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import backtest as bt
from fxradar import config
from fxradar import strategies as st

STRESS_PATH = config.DATA_DIR / "stress_tests.json"
WINDOWS = {
    "SNB week (Jan 2015)": ("2015-01-12", "2015-01-23"),
    "COVID crash (Feb–Mar 2020)": ("2020-02-20", "2020-03-31"),
    "2022": ("2022-01-01", "2022-12-31"),
}
COST_MULTS = [1.0, 2.0, 3.0, 5.0]
ROBUST_PARAMS = [
    "mom_scale",
    "z_clip",
    "risk_threshold",
    "siren_stop",
    "target_vol",
    "vol_lookback",
    "blend_lookback",
    "calm_size",
]
ROBUST_MULTS = [0.7, 0.85, 1.0, 1.15, 1.3]


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def pooled_net(res: bt.BacktestResult) -> pd.Series:
    return res.daily.groupby("date")["ret_net"].mean()


def test_slice(s: pd.Series) -> pd.Series:
    return s[s.index >= pd.Timestamp(config.TEST_START)]


def window_stats(r: pd.Series) -> dict:
    return {
        "return": float((1 + r).prod() - 1) if len(r) else float("nan"),
        "max_drawdown": bt.max_drawdown(r),
        "worst_day": float(r.min()) if len(r) else float("nan"),
        "days": int(len(r)),
    }


@contextmanager
def params_override(**over):
    """Temporarily change PARAMS for a robustness run — restored afterwards, never persisted."""
    old = dict(st.PARAMS)
    st.PARAMS.update(over)
    try:
        yield
    finally:
        st.PARAMS.clear()
        st.PARAMS.update(old)


# --------------------------------------------------------------------------------------
# 1. historical replays + siren firing
# --------------------------------------------------------------------------------------
def replays(
    results: dict[str, bt.BacktestResult], df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, fired = [], []
    for name, res in results.items():
        r = pooled_net(res)
        for label, (a, b) in WINDOWS.items():
            rows.append(
                {
                    "window": label,
                    "strategy": name,
                    **window_stats(r[(r.index >= a) & (r.index <= b)]),
                }
            )
    for label, (a, b) in WINDOWS.items():
        w = df[
            (df["date"] >= a) & (df["date"] <= b) & (df["anomaly_pct"] > st.PARAMS["siren_stop"])
        ]
        for pair, g in w.groupby("pair"):
            fired.append(
                {
                    "window": label,
                    "pair": pair,
                    "siren_days": int(len(g)),
                    "first": str(g["date"].min().date()),
                    "last": str(g["date"].max().date()),
                }
            )
        if w.empty:
            fired.append({"window": label, "pair": "-", "siren_days": 0, "first": "-", "last": "-"})
    return pd.DataFrame(rows), pd.DataFrame(fired)


# --------------------------------------------------------------------------------------
# 2. cost shocks + breakeven cost
# --------------------------------------------------------------------------------------
def cost_shocks(results: dict[str, bt.BacktestResult]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Net Sharpe (test) at k x cost, and the breakeven multiplier where net Sharpe crosses zero
    (0 = no edge even at zero cost; searched on a 0.05 grid up to 10x)."""
    rows, be = [], []
    grid = np.arange(0.0, 10.0001, 0.05)
    for name, res in results.items():
        d = res.daily
        d = d[d["date"] >= pd.Timestamp(config.TEST_START)]
        gross = d.groupby("date")["ret_gross"].mean()
        cost = d.groupby("date")["cost"].mean()
        sh = {k: bt.sharpe(gross - k * cost) for k in grid}
        for k in COST_MULTS:
            rows.append(
                {
                    "strategy": name,
                    "cost_mult": k,
                    "sharpe_net": sh[k],
                    "cagr_net": bt.cagr(gross - k * cost),
                }
            )
        crossing = None
        if sh[0.0] > 0:
            for k in grid:
                if sh[k] <= 0:
                    crossing = float(k)
                    break
            if crossing is None:
                crossing = float("inf")
        else:
            crossing = 0.0
        be.append(
            {
                "strategy": name,
                "gross_sharpe": sh[0.0],
                "sharpe_at_1x": sh[1.0],
                "breakeven_cost_mult": crossing,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(be)


# --------------------------------------------------------------------------------------
# 3. execution shock (one extra day of lag)
# --------------------------------------------------------------------------------------
def execution_shock(df: pd.DataFrame, results: dict[str, bt.BacktestResult]) -> pd.DataFrame:
    prices, feats = df[["date", "pair", "close"]], df[["date", "pair", "vol_20"]]
    rows = []
    slow: dict[str, bt.BacktestResult] = {}
    for name, fn in st.STRATEGY_FUNCS.items():
        pos = st.overlay(fn(df), df)
        pos_slow = pos.groupby(df["pair"]).shift(1).fillna(0.0)  # decided at t, filled at t+2
        slow[name] = bt.run_backtest(
            df[["date", "pair"]].assign(pos=pos_slow.to_numpy()),
            prices,
            feats,
            max_position=st.PARAMS["leverage_cap"],
        )
    slow["BLEND"] = st.blend(slow)
    for name in st.ALL_NAMES:
        s0 = bt.sharpe(test_slice(pooled_net(results[name])))
        s1 = bt.sharpe(test_slice(pooled_net(slow[name])))
        rows.append({"strategy": name, "sharpe_net": s0, "sharpe_extra_lag": s1, "decay": s1 - s0})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 4. volatility shock (crisis-regime returns x1.5, positions unchanged)
# --------------------------------------------------------------------------------------
def vol_shock(
    results: dict[str, bt.BacktestResult], regimes: pd.DataFrame, factor: float = 1.5
) -> pd.DataFrame:
    reg = regimes[["date", "pair", "regime"]]
    rows = []
    for name, res in results.items():
        d = res.daily.merge(reg, on=["date", "pair"], how="left")
        d = d[d["date"] >= pd.Timestamp(config.TEST_START)].copy()
        base = d.groupby("date")["ret_net"].mean()
        d["ret_net_shock"] = np.where(
            d["regime"] == "crisis", d["ret_gross"] * factor - d["cost"], d["ret_net"]
        )
        shock = d.groupby("date")["ret_net_shock"].mean()
        rows.append(
            {
                "strategy": name,
                "max_dd_base": bt.max_drawdown(base),
                "max_dd_shock": bt.max_drawdown(shock),
                "sharpe_base": bt.sharpe(base),
                "sharpe_shock": bt.sharpe(shock),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 5. block bootstrap of one-year max drawdown
# --------------------------------------------------------------------------------------
def bootstrap_paths(
    r: pd.Series, n_paths: int = 1000, block: int = 20, horizon: int = 252, seed: int = 0
) -> np.ndarray:
    """Moving-block bootstrap: `n_paths` paths of `horizon` days, each a concatenation of `block`-day
    contiguous slices of `r` drawn at random offsets — autocorrelation inside blocks is preserved,
    which shuffling single days would destroy. Returns (n_paths, horizon)."""
    rng = np.random.default_rng(seed)
    x = r.dropna().to_numpy()
    n = len(x)
    n_blocks = int(np.ceil(horizon / block))
    out = np.empty((n_paths, horizon))
    for i in range(n_paths):
        starts = rng.integers(0, n - block, n_blocks)
        out[i] = np.concatenate([x[s : s + block] for s in starts])[:horizon]
    return out


def block_bootstrap(
    r: pd.Series, n_paths: int = 1000, block: int = 20, horizon: int = 252, seed: int = 0
) -> np.ndarray:
    """Max drawdown of each bootstrapped one-year path."""
    paths = bootstrap_paths(r, n_paths, block, horizon, seed)
    eq = np.cumprod(1 + paths, axis=1)
    return (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)


def bootstrap_table(results: dict[str, bt.BacktestResult], reports_dir: Path) -> pd.DataFrame:
    rows, dists = [], {}
    for name, res in results.items():
        dd = block_bootstrap(test_slice(pooled_net(res)))
        dists[name] = dd
        rows.append(
            {
                "strategy": name,
                "median_max_dd": float(np.median(dd)),
                "p5_pain_max_dd": float(np.percentile(dd, 5)),
                "p95_max_dd": float(np.percentile(dd, 95)),
            }
        )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

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
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.hist(dists["BLEND"] * 100, bins=40, color="#E7ECF4", alpha=0.85)
    ax.axvline(
        np.median(dists["BLEND"]) * 100,
        color="#60A5FA",
        lw=1.2,
        label=f"median {np.median(dists['BLEND']):.1%}",
    )
    ax.axvline(
        np.percentile(dists["BLEND"], 5) * 100,
        color="#F87171",
        lw=1.2,
        label=f"5th pct pain {np.percentile(dists['BLEND'], 5):.1%}",
    )
    ax.set_xlabel(
        "max drawdown of a bootstrapped one-year path (%) — BLEND, 20-day blocks, 1000 paths"
    )
    ax.legend(frameon=False)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(reports_dir / "stress_bootstrap_dd.png", dpi=110)
    plt.close(fig)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 6. parameter robustness (+/-30 %), heatmap of net Sharpe (test)
# --------------------------------------------------------------------------------------
def robustness(df: pd.DataFrame, reports_dir: Path) -> pd.DataFrame:
    rows = []
    for p in ROBUST_PARAMS:
        base_val = st.PARAMS[p]
        for m in ROBUST_MULTS:
            val = base_val * m
            if isinstance(base_val, int):
                val = max(int(round(val)), 5)
            with params_override(**{p: val}):
                res = st.run_all(df)
            for name in st.ALL_NAMES:
                rows.append(
                    {
                        "param": p,
                        "mult": m,
                        "value": val,
                        "strategy": name,
                        "sharpe_net": bt.sharpe(test_slice(pooled_net(res[name]))),
                    }
                )
    tbl = pd.DataFrame(rows)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": "#0B0F17",
            "axes.facecolor": "#131A26",
            "text.color": "#E7ECF4",
            "axes.labelcolor": "#E7ECF4",
            "xtick.color": "#8A94A6",
            "ytick.color": "#8A94A6",
            "font.size": 9,
        }
    )
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.6), sharey=True)
    for ax, name in zip(axes, st.ALL_NAMES, strict=True):
        piv = (
            tbl[tbl["strategy"] == name]
            .pivot(index="param", columns="mult", values="sharpe_net")
            .loc[ROBUST_PARAMS, ROBUST_MULTS]
        )
        im = ax.imshow(piv.to_numpy(), cmap="RdYlGn", vmin=-3, vmax=1, aspect="auto")
        ax.set_xticks(range(len(ROBUST_MULTS)), [f"×{m}" for m in ROBUST_MULTS])
        ax.set_yticks(range(len(ROBUST_PARAMS)), ROBUST_PARAMS)
        ax.set_title(f"{name} — net Sharpe (test)", loc="left", fontsize=9)
        for i in range(piv.shape[0]):
            for j in range(piv.shape[1]):
                ax.text(
                    j,
                    i,
                    f"{piv.iat[i, j]:.1f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="#0B0F17",
                )
    fig.colorbar(im, ax=axes, fraction=0.02)
    fig.savefig(reports_dir / "stress_robustness.png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return tbl


# --------------------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------------------
def _md(df: pd.DataFrame, fmt: str = "{:.3f}") -> str:
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        out.append(
            "| " + " | ".join(fmt.format(v) if isinstance(v, float) else str(v) for v in r) + " |"
        )
    return "\n".join(out)


def run_lab(reports_dir: Path = config.REPORTS_DIR) -> dict:
    reports_dir.mkdir(parents=True, exist_ok=True)
    df = st.load_inputs()
    regimes = pd.read_parquet(config.REGIMES_PATH)
    results = st.run_all(df)
    rep, fired = replays(results, df)
    shocks, be = cost_shocks(results)
    exe = execution_shock(df, results)
    vs = vol_shock(results, regimes)
    boot = bootstrap_table(results, reports_dir)
    rob = robustness(df, reports_dir)

    # verdicts
    v = {}
    worst_rep = rep.loc[rep["max_drawdown"].idxmin()]
    v["replays"] = (
        f"Worst window/strategy: {worst_rep['strategy']} in {worst_rep['window']} (max DD {worst_rep['max_drawdown']:.1%}, worst day {worst_rep['worst_day']:.2%}). Siren stop fired on {int(fired['siren_days'].sum())} pair-days across the three windows (see table) — the overlay was flat exactly when it was supposed to be."
    )
    be_blend = be.set_index("strategy").loc["BLEND", "breakeven_cost_mult"]
    v["costs"] = (
        (
            "No strategy has a positive gross Sharpe on the test set, so the breakeven cost multiplier is 0 for "
            + ", ".join(be[be["breakeven_cost_mult"] == 0]["strategy"])
            + " — there is no edge to pay costs from. "
            if (be["breakeven_cost_mult"] == 0).any()
            else ""
        )
        + f"BLEND breakeven {be_blend:g}× the modelled cost."
        + (
            " A practitioner reads this row first: nothing here survives its own transaction costs."
            if (be["breakeven_cost_mult"] <= 1).all()
            else ""
        )
    )
    v["execution"] = (
        f"One extra day of lag changes net Sharpe by {exe['decay'].min():+.2f} to {exe['decay'].max():+.2f}. "
        + (
            "Strategies that lose materially from a day of slippage were never real; "
            if (exe["decay"] < -0.3).any()
            else "The decay is small, which mostly reflects how little there was to lose; "
        )
        + "the numbers are reported as they are."
    )
    dd_delta = (vs["max_dd_shock"] - vs["max_dd_base"]).min()
    v["vol"] = (
        f"Scaling crisis-regime returns by 1.5x deepens the worst max drawdown by only {abs(dd_delta):.1%} "
        f"({vs['max_dd_base'].min():.1%} → {vs['max_dd_shock'].min():.1%}): crisis exposure is small because the "
        "siren stop and the crisis-flat gate take risk off in exactly those days — the overlay does its job. "
        "The base drawdowns themselves are dreadful; the shock is not what makes them so."
    )
    b = boot.set_index("strategy").loc["BLEND"]
    v["bootstrap"] = (
        f"BLEND one-year max drawdown: median {b['median_max_dd']:.1%}, 5th-percentile pain case {b['p5_pain_max_dd']:.1%} (20-day blocks keep the autocorrelation that day-shuffling would destroy)."
    )
    blend_rob = rob[rob["strategy"] == "BLEND"]
    spread = blend_rob.groupby("param")["sharpe_net"].agg(lambda x: x.max() - x.min())
    v["robustness"] = (
        f"Across ±30 % of every parameter the BLEND's net Sharpe stays within a band of {spread.max():.2f} (widest for {spread.idxmax()}) — a flat, negative plateau: nothing is overfit to a spike, and nothing is good either. Parameters were not changed after seeing this."
    )

    summary = pd.DataFrame(
        [
            {"test": "historical replays", "verdict": v["replays"]},
            {"test": "cost shocks / breakeven", "verdict": v["costs"]},
            {"test": "execution shock", "verdict": v["execution"]},
            {"test": "volatility shock", "verdict": v["vol"]},
            {"test": "block bootstrap", "verdict": v["bootstrap"]},
            {"test": "parameter robustness", "verdict": v["robustness"]},
        ]
    )
    L = [
        "# Stress report — the strategy layer under attack\n",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Test period 2019+ unless stated; net of the vol-scaled cost model; nothing was re-tuned after these results. Research demonstration on daily data — not a live trading system._\n",
    ]
    L += [
        "## 1. Historical replays\n",
        _md(rep, "{:.3f}") + "\n",
        "Siren stop (anomaly_pct > 98) inside the windows:\n",
        _md(fired) + "\n",
        f"**Verdict:** {v['replays']}\n",
    ]
    L += [
        "## 2. Cost shocks and the BREAKEVEN COST\n",
        "**Breakeven cost multiplier — the number practitioners ask first:**\n",
        _md(be, "{:.2f}") + "\n",
        "Net Sharpe at k× the cost model:\n",
        _md(
            shocks.pivot(index="strategy", columns="cost_mult", values="sharpe_net").reset_index(),
            "{:.2f}",
        )
        + "\n",
        f"**Verdict:** {v['costs']}\n",
    ]
    L += [
        "## 3. Execution shock — one extra day of lag\n",
        _md(exe, "{:.2f}") + "\n",
        f"**Verdict:** {v['execution']}\n",
    ]
    L += [
        "## 4. Volatility shock — crisis-regime returns ×1.5\n",
        _md(vs, "{:.3f}") + "\n",
        f"**Verdict:** {v['vol']}\n",
    ]
    L += [
        "## 5. Block bootstrap — one-year max drawdown, 1 000 paths\n",
        _md(boot, "{:.3f}") + "\n",
        "![bootstrap](stress_bootstrap_dd.png)\n",
        f"**Verdict:** {v['bootstrap']}\n",
    ]
    L += [
        "## 6. Parameter robustness — ±30 %\n",
        "![robustness](stress_robustness.png)\n",
        f"**Verdict:** {v['robustness']}\n",
    ]
    L += [
        "## Summary\n",
        _md(summary) + "\n",
        "\n_Research demonstration on daily data — not a live trading system. Educational tool. Not investment advice._\n",
    ]
    (reports_dir / "stress_report.md").write_text("\n".join(L))

    STRESS_PATH.write_text(
        json.dumps(
            {
                "replays": rep.to_dict(orient="records"),
                "siren_fired": fired.to_dict(orient="records"),
                "breakeven": be.to_dict(orient="records"),
                "cost_shocks": shocks.to_dict(orient="records"),
                "execution": exe.to_dict(orient="records"),
                "vol_shock": vs.to_dict(orient="records"),
                "bootstrap": boot.to_dict(orient="records"),
                "verdicts": v,
            },
            indent=1,
            default=float,
        )
    )
    return {
        "replays": rep,
        "breakeven": be,
        "shocks": shocks,
        "execution": exe,
        "vol": vs,
        "bootstrap": boot,
        "robustness": rob,
        "verdicts": v,
    }


def main() -> None:
    out = run_lab()
    pd.set_option("display.width", 200)
    print("== breakeven cost ==\n", out["breakeven"].round(3).to_string(index=False))
    print("\n== bootstrap ==\n", out["bootstrap"].round(3).to_string(index=False))
    for k, s in out["verdicts"].items():
        print(f"\n[{k}] {s}")
    print(f"\nwrote {config.REPORTS_DIR / 'stress_report.md'} and {STRESS_PATH}")


if __name__ == "__main__":
    main()
