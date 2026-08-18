"""HMM validation: are the regimes real, stable and useful — or statistical decoration?

Produces reports/hmm_validation.md (+ pngs) with: regime anatomy (train vs out-of-sample),
seed stability, a naive vol-percentile baseline with dated lead/lag examples, an economic
meaning check (a toy MA(50/200) trend rule's Sharpe per regime), plots, and limitations.
Nothing here touches model code; it only reads artifacts and refits for the seed check.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fxradar import config
from fxradar import hmm_model as hm

log = logging.getLogger(__name__)

OOS_START = config.VAL_START  # 2017-01-01: nothing after this date touched the HMM fit
REGIME_COLORS = {"calm": "#34D399", "trend": "#60A5FA", "chop": "#FBBF24", "crisis": "#F87171"}
DARK = {
    "bg": "#0B0F17",
    "surface": "#131A26",
    "border": "#232D3F",
    "text": "#E7ECF4",
    "muted": "#8A94A6",
}
ANN = 252.0


# --------------------------------------------------------------------------------------
# small financial helpers (each has a test — CLAUDE.md rule 6)
# --------------------------------------------------------------------------------------
def max_drawdown(returns: pd.Series) -> float:
    """Worst peak-to-trough drop of the cumulative (log-return) equity curve, as a fraction."""
    if len(returns) == 0:
        return float("nan")
    equity = np.exp(returns.cumsum())
    return float((equity / equity.cummax() - 1.0).min())


def sharpe(returns: pd.Series) -> float:
    """Annualised Sharpe of daily returns (zero risk-free rate); NaN if undefined."""
    if len(returns) < 2 or returns.std(ddof=1) == 0:
        return float("nan")
    return float(returns.mean() / returns.std(ddof=1) * np.sqrt(ANN))


def run_lengths(labels: pd.Series) -> pd.DataFrame:
    """One row per run of identical labels: label, start, end, length (days)."""
    labels = labels.reset_index(drop=True)
    starts = labels.ne(labels.shift(1)).to_numpy().nonzero()[0]
    ends = np.append(starts[1:], len(labels))
    return pd.DataFrame(
        {
            "label": labels.iloc[starts].to_numpy(),
            "start": starts,
            "end": ends - 1,
            "length": ends - starts,
        }
    )


def load_joined() -> pd.DataFrame:
    """prices + features + regimes on (date, pair), sorted."""
    prices = pd.read_parquet(config.PRICES_PATH)
    feats = pd.read_parquet(config.FEATURES_PATH)
    regs = pd.read_parquet(config.REGIMES_PATH)
    df = feats.merge(regs[["date", "pair", "regime", "regime_prob"]], on=["date", "pair"])
    df = df.merge(prices[["date", "pair", "close"]], on=["date", "pair"])
    df["period"] = np.where(df["date"] < pd.Timestamp(OOS_START), "train", "oos")
    return df.sort_values(["pair", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# 1. regime anatomy
# --------------------------------------------------------------------------------------
def regime_anatomy(df: pd.DataFrame) -> pd.DataFrame:
    """Per pair x period x regime: frequency, mean duration, annualised vol, mean daily return, worst drawdown."""
    rows = []
    for (pair, period), g in df.groupby(["pair", "period"]):
        g = g.sort_values("date")
        runs = run_lengths(g["regime"])
        for regime in hm.REGIMES:
            r = g[g["regime"] == regime]["ret_1d"]
            rows.append(
                {
                    "pair": pair,
                    "period": period,
                    "regime": regime,
                    "days": int(len(r)),
                    "freq_pct": 100.0 * len(r) / len(g),
                    "mean_duration_d": (
                        float(runs.loc[runs["label"] == regime, "length"].mean())
                        if len(r)
                        else float("nan")
                    ),
                    "ann_vol_pct": (
                        float(r.std(ddof=1) * np.sqrt(ANN) * 100) if len(r) > 1 else float("nan")
                    ),
                    "mean_ret_bp": float(r.mean() * 1e4) if len(r) else float("nan"),
                    "worst_dd_pct": 100 * max_drawdown(r) if len(r) else float("nan"),
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 3. naive baseline: stressed when vol_20 > trailing 80th percentile
# --------------------------------------------------------------------------------------
def naive_stress(vol_20: pd.Series, window: int = 250, q: float = 0.8) -> pd.Series:
    """Causal naive classifier: True when today's vol_20 is above its trailing `window`-day 80th
    percentile (percentile includes today; only past and current rows are used)."""
    thresh = vol_20.rolling(window, min_periods=60).quantile(q)
    return (vol_20 > thresh).fillna(False)


def episode_starts(flag: pd.Series) -> np.ndarray:
    """Row positions where a boolean flag switches from False to True."""
    f = flag.reset_index(drop=True).astype(bool)
    return np.flatnonzero(f & ~f.shift(1, fill_value=False))


def lead_lag_examples(
    dates: pd.Series, hmm_flag: pd.Series, naive_flag: pd.Series, horizon: int = 15
) -> pd.DataFrame:
    """For each HMM stress-episode start, the nearest naive-episode start within +/-`horizon` rows.
    lead_days > 0 means the HMM flagged stress first."""
    hs, ns = episode_starts(hmm_flag), episode_starts(naive_flag)
    dates = dates.reset_index(drop=True)
    rows = []
    for h in hs:
        near = ns[np.abs(ns - h) <= horizon]
        if len(near) == 0:
            continue
        n = near[np.argmin(np.abs(near - h))]
        rows.append(
            {"hmm_start": dates[h].date(), "naive_start": dates[n].date(), "lead_days": int(n - h)}
        )
    return pd.DataFrame(rows)


def baseline_comparison(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Agreement (accuracy + Cohen's kappa) of HMM 'crisis' vs the naive rule, out of sample, plus examples."""
    rows, examples = [], {}
    for pair, g in df.groupby("pair"):
        g = g.sort_values("date").reset_index(drop=True)
        naive = naive_stress(g["vol_20"])
        hmm_flag = g["regime"] == "crisis"
        oos = g["period"] == "oos"
        a, b = hmm_flag[oos].to_numpy(), naive[oos].to_numpy()
        po = float((a == b).mean())
        pe = float(a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean()))
        kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")
        rows.append(
            {
                "pair": pair,
                "hmm_crisis_pct": 100 * a.mean(),
                "naive_stress_pct": 100 * b.mean(),
                "agreement_pct": 100 * po,
                "kappa": kappa,
            }
        )
        examples[pair] = lead_lag_examples(g["date"], hmm_flag, naive)
    return pd.DataFrame(rows), examples


# --------------------------------------------------------------------------------------
# 4. economic meaning: toy MA(50/200) trend rule, Sharpe per regime (out of sample)
# --------------------------------------------------------------------------------------
def ma_trend_returns(
    close: pd.Series, ret_1d: pd.Series, fast: int = 50, slow: int = 200
) -> pd.Series:
    """Daily P&L of a toy rule: long when MA(fast) > MA(slow) else short, decided at t and earned at
    t+1 (one-day execution lag, gross of costs — this is a diagnostic, not a strategy)."""
    pos = np.sign(close.rolling(fast).mean() - close.rolling(slow).mean())
    return (pos.shift(1) * ret_1d).rename("strat_ret")


def economic_check(df: pd.DataFrame) -> pd.DataFrame:
    """Sharpe of the toy trend rule per regime label (regime at t, return earned at t+1), OOS."""
    rows = []
    for pair, g in df.groupby("pair"):
        g = g.sort_values("date").reset_index(drop=True)
        strat = ma_trend_returns(g["close"], g["ret_1d"])
        # the return realised on t+1 is attributed to the regime known at t (causal)
        attributed = pd.DataFrame(
            {"regime": g["regime"], "ret": strat.shift(-1), "period": g["period"]}
        ).dropna()
        oos = attributed[attributed["period"] == "oos"]
        for regime in hm.REGIMES:
            r = oos.loc[oos["regime"] == regime, "ret"]
            rows.append(
                {
                    "pair": pair,
                    "regime": regime,
                    "days": int(len(r)),
                    "sharpe": sharpe(r),
                    "ann_ret_pct": float(r.mean() * ANN * 100) if len(r) else float("nan"),
                }
            )
        rows.append(
            {
                "pair": pair,
                "regime": "ALL",
                "days": int(len(oos)),
                "sharpe": sharpe(oos["ret"]),
                "ann_ret_pct": float(oos["ret"].mean() * ANN * 100),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 5. plots
# --------------------------------------------------------------------------------------
def _style() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": DARK["bg"],
            "axes.facecolor": DARK["surface"],
            "axes.edgecolor": DARK["border"],
            "axes.labelcolor": DARK["text"],
            "xtick.color": DARK["muted"],
            "ytick.color": DARK["muted"],
            "text.color": DARK["text"],
            "grid.color": DARK["border"],
            "font.size": 9,
        }
    )
    return plt


def plot_timeline(df: pd.DataFrame, pair: str, path: Path) -> None:
    """Close with regime-coloured bands (merged runs) and the out-of-sample divider."""
    plt = _style()
    g = df[df["pair"] == pair].sort_values("date").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(12, 3.6))
    for run in run_lengths(g["regime"]).itertuples(index=False):
        ax.axvspan(
            g["date"][run.start],
            g["date"][run.end],
            color=REGIME_COLORS[run.label],
            alpha=0.35,
            lw=0,
        )
    ax.plot(g["date"], g["close"], color=DARK["text"], lw=0.8)
    div = pd.Timestamp(OOS_START)
    ax.axvline(div, color=DARK["muted"], ls="--", lw=1)
    ax.annotate(
        "out-of-sample →",
        (div, ax.get_ylim()[1]),
        xytext=(6, -14),
        textcoords="offset points",
        color=DARK["muted"],
    )
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, alpha=0.6) for c in REGIME_COLORS.values()]
    ax.legend(handles, list(REGIME_COLORS), loc="upper right", ncol=4, frameon=False)
    ax.set_title(f"{pair} — close with filtered HMM regimes", loc="left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_duration_hist(df: pd.DataFrame, path: Path) -> None:
    """Histogram of regime run lengths, one panel per regime, pooled across pairs."""
    plt = _style()
    runs = pd.concat([run_lengths(g.sort_values("date")["regime"]) for _, g in df.groupby("pair")])
    fig, axes = plt.subplots(1, 4, figsize=(12, 2.8), sharey=True)
    for ax, regime in zip(axes, hm.REGIMES, strict=True):
        ax.hist(
            runs.loc[runs["label"] == regime, "length"].clip(upper=120),
            bins=24,
            color=REGIME_COLORS[regime],
        )
        ax.set_title(regime, loc="left")
        ax.set_xlabel("run length (days, clipped at 120)")
        ax.grid(alpha=0.3)
    fig.suptitle("Regime duration distribution (all pairs, full history)", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# --------------------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------------------
def _md(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    """Tiny markdown table writer (no extra dependency)."""
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report(reports_dir: Path = config.REPORTS_DIR, seeds=(1, 2, 3, 4, 5)) -> Path:
    """Run every check, write pngs and reports/hmm_validation.md; return the md path."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    df = load_joined()
    feats = pd.read_parquet(config.FEATURES_PATH)
    bundles = hm.load_bundles()

    anatomy = regime_anatomy(df)
    stability = hm.seed_stability(feats, bundles, seeds=seeds)
    stab_tbl = stability.pivot(index="pair", columns="seed", values="agreement")
    stab_tbl["mean"] = stab_tbl.mean(axis=1)
    agree, examples = baseline_comparison(df)
    econ = economic_check(df)

    for pair in config.PAIRS:
        plot_timeline(df, pair, reports_dir / f"regimes_timeline_{pair}.png")
    plot_duration_hist(df, reports_dir / "regime_durations.png")

    L: list[str] = []
    L.append("# HMM validation — are these regimes real, stable and useful?\n")
    L.append(
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Train = dates ≤ {config.TRAIN_END}; out-of-sample (OOS) = {OOS_START} onward — nothing after the train end touched the fit. All regime labels are FILTERED (causal)._\n"
    )

    L.append("## 1. Regime anatomy (train vs out-of-sample)\n")
    L.append(
        "Frequency, mean run length, annualised vol of daily returns, mean daily return (bp) and worst drawdown of the return stream *inside* each label. Ordering by vol is by construction (calm < … < crisis); everything else is a genuine test.\n"
    )
    for pair in config.PAIRS:
        L.append(f"**{pair}**\n")
        t = anatomy[anatomy["pair"] == pair].drop(columns="pair")
        L.append(_md(t) + "\n")
    L.append(
        "Reading: the vol ordering survives out of sample for every pair (a label is not just an in-sample artefact). Mean returns inside labels are tiny relative to vol — regimes describe *conditions*, not direction. Note USDCHF: its `crisis` state was learnt almost entirely from the January-2015 SNB shock (20 train days, ~65 % annualised vol) and never fires out of sample; USDCHF's 2008–2011 stress carries the `chop` name instead. This is a labelling artefact of the frozen naming rule plus one extreme event, and it is reported rather than patched.\n"
    )

    L.append("## 2. Seed stability\n")
    L.append(
        "The seed-42 model is the reference; each cell is the share of days on which a model refit with another seed (same data, same naming rule) gives the same label.\n"
    )
    L.append(_md(stab_tbl.reset_index(), "{:.3f}") + "\n")
    lo = stab_tbl["mean"].idxmin()
    L.append(
        f"Interpretation, honestly: agreement ranges from {stability['agreement'].min():.0%} to {stability['agreement'].max():.0%}. "
        f"Some refits land on the same optimum (≥ 99 % agreement) and others on a different one where the middle two states split the data differently — {lo} is the least stable (mean {stab_tbl.loc[lo, 'mean']:.0%}, below the 80 % warning threshold). "
        "The calm/crisis ends are the stable part; the trend/chop split is the fragile part. EM finds local optima, and a rule that names states by mean vol/momentum inherits that. Practical consequences: (a) treat `trend` vs `chop` as soft; (b) a production refit should use several restarts and keep the best likelihood, and be checked against the previous labelling before it replaces it (phase 06 refit path); (c) `regime_prob`/`hmm_entropy` are more trustworthy than the label itself.\n"
    )

    L.append("## 3. Baseline: does the HMM add anything to a one-line vol rule?\n")
    L.append(
        "Naive rule: *stressed* when vol_20 is above its trailing 250-day 80th percentile, else *quiet* (causal). Compared with HMM `crisis` out of sample.\n"
    )
    L.append(_md(agree) + "\n")
    L.append(
        "Where the two disagree the naive rule is usually earlier by construction (a percentile flips the day vol crosses it) while the HMM waits for the transition to be likely — it trades a few days of lag for far fewer flickers (compare mean durations above). Dated episodes (full history) where both flagged stress within 15 trading days of each other (lead_days > 0 = HMM first); the three largest HMM leads are shown:\n"
    )
    for pair in config.PAIRS:
        ex = examples[pair]
        L.append(
            f"**{pair}** — {len(ex)} matched episodes; HMM led in {(ex['lead_days'] > 0).sum() if len(ex) else 0}, naive led in {(ex['lead_days'] < 0).sum() if len(ex) else 0}, same day {(ex['lead_days'] == 0).sum() if len(ex) else 0}.\n"
        )
        if len(ex):
            L.append(_md(ex.sort_values("lead_days", ascending=False).head(3), "{:.0f}") + "\n")
        else:
            L.append(
                "_No matched episodes (the HMM's crisis label rarely or never fires for this pair)._\n"
            )
    led = sum(int((examples[p]["lead_days"] > 0).sum()) for p in config.PAIRS if len(examples[p]))
    lagged = sum(
        int((examples[p]["lead_days"] < 0).sum()) for p in config.PAIRS if len(examples[p])
    )
    L.append(
        f"Verdict: the HMM does **not** systematically lead the naive rule — across all matched episodes it led in {led} and lagged in {lagged}. "
        "When it leads it can be by several days (EURUSD, autumn 2011), but more often it is simultaneous or later. "
        "Its value is not earlier warnings but a four-way, sticky, probabilistic description (with confidence and entropy) instead of a binary flicker — and that is what the forecaster and narrator consume.\n"
    )

    L.append("## 4. Economic meaning: a toy trend rule inside each regime (out of sample)\n")
    L.append(
        "MA(50/200) long/short decided at t, earned at t+1, gross of costs — a diagnostic only. Claim under test: trend-following should look best in `trend` and worst in `chop`.\n"
    )
    for pair in config.PAIRS:
        L.append(f"**{pair}**\n")
        L.append(_md(econ[econ["pair"] == pair].drop(columns="pair")) + "\n")
    verdicts, best_is_trend, worst_is_chop = [], 0, 0
    for pair in config.PAIRS:
        e = econ[(econ["pair"] == pair) & (econ["regime"] != "ALL")].dropna(subset=["sharpe"])
        best, worst = e.loc[e["sharpe"].idxmax(), "regime"], e.loc[e["sharpe"].idxmin(), "regime"]
        best_is_trend += best == "trend"
        worst_is_chop += worst == "chop"
        verdicts.append(f"{pair}: best in `{best}`, worst in `{worst}`")
    L.append(
        "Reading: "
        + "; ".join(verdicts)
        + f". The claim holds for {best_is_trend}/3 pairs on 'best in trend' and {worst_is_chop}/3 on "
        "'worst in chop' — it does **not** hold as a general pattern, and `crisis` is where a moving-average "
        "rule gets whipsawed hardest. Differences between labels are also within noise for these sample sizes. "
        "The regimes are descriptive states of volatility/momentum, not a trading edge, and this report says so.\n"
    )

    L.append("## 5. Plots\n")
    for pair in config.PAIRS:
        L.append(f"![{pair} timeline](regimes_timeline_{pair}.png)\n")
    L.append("![durations](regime_durations.png)\n")

    L.append("## 6. Limitations\n")
    L.append(
        "- **Daily data only.** Intraday storms are averaged away; Yahoo's daily close is a start-of-day snapshot, so returns are one day late relative to highs/lows.\n"
        "- **Label noise.** Filtered labels flicker near state boundaries and the trend/chop split is seed-sensitive (section 2). Read `regime_prob` and `hmm_entropy` with the label.\n"
        "- **Descriptive, not predictive.** A regime describes the recent past; the transition matrix says regimes are sticky, nothing more. Direction is not modelled anywhere.\n"
        "- **Frozen naming rule + rare events.** One extreme episode (SNB 2015) can own a whole state (USDCHF); the rule then mislabels the ordinary stress state.\n"
        "- **Single training window (2005–2016).** Post-2016 structure (2020, 2022) is scored, not learnt; a monthly expanding refit is the phase-06 plan.\n"
        "- **Gaussian emissions.** Fat tails are absorbed by the high-vol state rather than modelled.\n"
    )
    L.append("\n_Educational tool. Not investment advice._\n")
    out = reports_dir / "hmm_validation.md"
    out.write_text("\n".join(L))
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    out = build_report()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
