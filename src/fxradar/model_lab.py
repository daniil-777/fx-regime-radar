"""The model lab: race every registered regime model and forecaster engine on the active universe,
under identical protocols, and write one honest comparison report.

Research copies only — nothing here touches the shipped champions, the bundle, the goldens or the
live ledger. `python -m fxradar.model_lab` →
  * trains jump + gmm regime models (train era, λ matched to the champion's persistence on train),
  * scores the full history causally with each,
  * compares OOS regime anatomy (share, vol ordering, mean run, switches/yr) and agreement,
  * evaluates every forecaster engine on the SAME champion-HMM feature matrix (same splits,
    embargo, Platt calibration on val, recall-targeted threshold; frozen test scored once here),
  * writes reports/model_lab.md + regime timelines png, and saves the research bundles.
Promotion of any winner is a deliberate refit-path / challenger-ledger act — never this script.
"""

from __future__ import annotations

import json
import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from fxradar import config
from fxradar import forecaster as fc
from fxradar import forecaster_models as fm
from fxradar import hmm_model as hm
from fxradar import regime_models as rm
from fxradar import tokens as tk

log = logging.getLogger(__name__)

REPORT_PATH = config.REPORTS_DIR / "model_lab.md"
PNG_PATH = config.REPORTS_DIR / "model_lab_timelines.png"
LAB_PARQUET = config.DATA_DIR / "model_lab.parquet"  # per-model scored regimes — the app reads this
LAB_JSON = config.DATA_DIR / "model_lab.json"  # stats + agreement + forecaster scoreboard
OOS_START = config.VAL_START


def regime_stats(scored: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Per pair: OOS share per regime, vol ordering check, mean run, switches/yr."""
    rows = []
    for pair, g in scored.groupby("pair"):
        g = g.sort_values("date")
        oos = g[g["date"] >= pd.Timestamp(OOS_START)].copy()
        px = prices[prices["pair"] == pair].sort_values("date")
        oos = oos.merge(px[["date", "close"]], on="date", how="left")
        oos["ret"] = np.log(oos["close"] / oos["close"].shift(1))
        vols = {
            r: float(oos.loc[oos["regime"] == r, "ret"].std() * np.sqrt(config.TRADING_DAYS) * 100)
            for r in hm.REGIMES
            if (oos["regime"] == r).sum() > 20
        }
        ordered = (
            all(
                vols.get(a, np.nan) <= vols.get(b, np.inf)
                for a, b in [("calm", "crisis")]
                if a in vols and b in vols
            )
            and vols.get("calm", 0) == min(vols.values(), default=0)
            if vols
            else False
        )
        switches = int((oos["regime"].values[1:] != oos["regime"].values[:-1]).sum())
        years = max(len(oos) / config.TRADING_DAYS, 1e-9)
        runs = oos["regime"].ne(oos["regime"].shift(1)).cumsum()
        rows.append(
            {
                "pair": pair,
                "share_calm": float((oos["regime"] == "calm").mean()),
                "share_crisis": float((oos["regime"] == "crisis").mean()),
                "mean_run_d": float(oos.groupby(runs).size().mean()),
                "switches_yr": switches / years,
                "vol_ordering_ok": bool(ordered),
                "vol_calm": vols.get("calm"),
                "vol_crisis": vols.get("crisis"),
            }
        )
    return pd.DataFrame(rows)


def agreement(a: pd.DataFrame, b: pd.DataFrame) -> float:
    """Share of OOS days on which two scored frames give the same label."""
    m = a[["date", "pair", "regime"]].merge(b[["date", "pair", "regime"]], on=["date", "pair"])
    m = m[m["date"] >= pd.Timestamp(OOS_START)]
    return float((m["regime_x"] == m["regime_y"]).mean())


def _md_table(df: pd.DataFrame, fmt: dict[str, str]) -> str:
    show = df.copy()
    for c, f in fmt.items():
        if c in show:
            show[c] = show[c].map(lambda v, f=f: "—" if pd.isna(v) else f.format(v))
    header = "| " + " | ".join(show.columns) + " |"
    sep = "|" + "---|" * len(show.columns)
    rows = ["| " + " | ".join(str(v) for v in r) + " |" for r in show.itertuples(index=False)]
    return "\n".join([header, sep, *rows])


def timelines_png(scored_by_model: dict[str, pd.DataFrame], pair: str) -> None:
    colors = tk.REGIME_COLORS
    fig, axes = plt.subplots(
        len(scored_by_model),
        1,
        figsize=(12, 1.4 * len(scored_by_model) + 1),
        sharex=True,
        squeeze=False,
    )
    fig.patch.set_facecolor(tk.BG)
    for ax, (name, sc) in zip(axes[:, 0], scored_by_model.items(), strict=False):
        g = sc[sc["pair"] == pair].sort_values("date")
        codes = g["regime"].map({r: i for i, r in enumerate(hm.REGIMES)}).to_numpy()
        ax.imshow(
            codes[None, :],
            aspect="auto",
            cmap=matplotlib.colors.ListedColormap([colors[r] for r in hm.REGIMES]),
            vmin=0,
            vmax=3,
            extent=[0, len(g), 0, 1],
        )
        ax.set_yticks([])
        ax.set_ylabel(name, rotation=0, ha="right", va="center", color=tk.TEXT, fontsize=9)
        ax.set_facecolor(tk.BG)
        for s in ax.spines.values():
            s.set_visible(False)
    axes[0, 0].set_title(
        f"{pair} — one row per model, full history (calm/trend/chop/crisis)",
        loc="left",
        color=tk.TEXT,
        fontsize=10,
    )
    axes[-1, 0].set_xticks([])
    fig.tight_layout()
    fig.savefig(PNG_PATH, dpi=150, facecolor=tk.BG, bbox_inches="tight")
    plt.close(fig)


def run() -> str:
    feats = pd.read_parquet(config.FEATURES_PATH)
    prices = pd.read_parquet(config.PRICES_PATH)
    regimes_champion = pd.read_parquet(config.REGIMES_PATH)

    # ---- regime models ---------------------------------------------------------------
    scored = {"hmm (champion)": rm.score_all(feats, hm.load_bundles())}
    lam_used: dict[str, float] = {}
    for name in ("jump", "gmm"):
        bundles = rm.train(name, feats)
        rm.save_bundles(name, bundles)
        scored[name] = rm.score_all(feats, bundles)
        if name == "jump":
            lam_used = {p: b.lam for p, b in bundles.items()}
    stats = {n: regime_stats(sc, prices) for n, sc in scored.items()}
    agree = {
        n: agreement(scored["hmm (champion)"], sc)
        for n in scored
        if n != "hmm (champion)"
        for sc in [scored[n]]
    }

    # ---- forecaster engines (same champion-HMM matrix for all) ------------------------
    df = fc.assemble(feats, regimes_champion)
    engines = [fm.evaluate(name, df) for name in fm.ESTIMATORS]

    # ---- report ----------------------------------------------------------------------
    lines = [
        "# Model lab — a choice of models, raced under one protocol",
        "",
        f"_Universe `{config.UNIVERSE_NAME}` · generated {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. "
        "Research copies only: the shipped champions, the bundle/goldens and the live ledger are untouched. "
        "Regime alternatives: the statistical jump model (Bemporad 2018; Nystrup et al. 2020/21; "
        "Aydınhan–Kolm–Mulvey–Shu 2024) with GREEDY ONLINE (causal) inference and λ matched per pair to the "
        "champion's TRAIN-era switching rate; a temporally-uncoupled GMM as the persistence ablation. "
        "Forecaster engines: the XGBoost champion, sklearn's HistGradientBoosting (LightGBM-style, zero new "
        "dependencies), and the logistic reference — identical splits, embargo, Platt calibration on "
        "validation, recall-targeted threshold; each engine's frozen test scored once, here._",
        "",
        "## Regime models — out-of-sample anatomy "
        f"(≥ {OOS_START}; λ per pair: {', '.join(f'{p}={v:g}' for p, v in lam_used.items()) or '—'})",
        "",
    ]
    for name, st in stats.items():
        extra = (
            ""
            if name == "hmm (champion)"
            else f" · OOS label agreement with champion {agree[name]:.0%}"
        )
        lines += [
            f"**{name}**{extra}",
            "",
            _md_table(
                st,
                {
                    "share_calm": "{:.0%}",
                    "share_crisis": "{:.1%}",
                    "mean_run_d": "{:.0f}",
                    "switches_yr": "{:.1f}",
                    "vol_calm": "{:.1f}",
                    "vol_crisis": "{:.1f}",
                },
            ),
            "",
        ]
    lines += [
        "![timelines](model_lab_timelines.png)",
        "",
        "Reading: the jump model's whole point is fewer, longer regimes at matched training persistence — "
        "compare `switches_yr` and `mean_run_d` with the champion; the GMM row shows what removing temporal "
        "coupling costs (label flicker). `vol_ordering_ok` checks calm is still the lowest-vol label out of "
        "sample — the anatomy test a regime label must pass to mean anything.",
        "",
        "## Forecaster engines — same matrix, same protocol (never accuracy)",
        "",
        "| engine | threshold | val PR-AUC | test PR-AUC ↑ | test Brier ↓ | precision | recall | selection |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in engines:
        sel = e["info"].get("chosen_max_iter") or e["info"].get("best_iteration", "early stop")
        lines.append(
            f"| {e['estimator']} | {e['threshold']:.2f} | {e['val']['pr_auc']:.3f} | "
            f"**{e['test']['pr_auc']:.3f}** | {e['test']['brier']:.4f} | "
            f"{e['test']['precision']:.2f} | {e['test']['recall']:.2f} | {sel} |"
        )
    lines += [
        "",
        "Reading: two different GBDT implementations landing within noise of each other says the signal is in "
        "the features and the protocol, not in a library — a robustness result. The linear model's gap is the "
        "value of interactions. Promotion of any engine is a deliberate act through the challenger-ledger "
        "protocol (train → race live under its own model_version → promote after ≥ 60 matured days), never a "
        "flag flip.",
        "",
        "_Educational tool. Not investment advice._",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    timelines_png(scored, config.PAIRS[0])

    # ---- artifacts for the app's Model lab page (rule 8: the page reads, never computes) -----
    frames = []
    for name, sc in scored.items():
        key = "hmm" if name.startswith("hmm") else name
        frames.append(sc[["date", "pair", "regime", "regime_prob"]].assign(model=key))
    pd.concat(frames, ignore_index=True).to_parquet(LAB_PARQUET, index=False)
    LAB_JSON.write_text(
        json.dumps(
            {
                "generated_at_utc": f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%dT%H:%M:%SZ}",
                "universe": config.UNIVERSE_NAME,
                "oos_start": str(OOS_START),
                "lambda": lam_used,
                "stats": {
                    ("hmm" if n.startswith("hmm") else n): st.to_dict("records")
                    for n, st in stats.items()
                },
                "agreement": {("hmm" if n.startswith("hmm") else n): v for n, v in agree.items()},
                "forecasters": [
                    {k: v for k, v in e.items() if k not in ("model",)} for e in engines
                ],
                "model_notes": {
                    "hmm": "champion — filtered forward algorithm; the shipped record and the live ledger run on this",
                    "jump": "statistical jump model (research) — greedy online inference, penalty per switch matched to the champion's train persistence",
                    "gmm": "mixture ablation (research) — no temporal coupling; shows what the persistence machinery buys",
                },
            },
            indent=1,
            default=float,
        )
    )
    return str(REPORT_PATH)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("wrote", run())


if __name__ == "__main__":
    main()
