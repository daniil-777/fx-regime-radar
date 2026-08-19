"""Event study (phase 29, part D): lexicon tone SURPRISE vs subsequent FX volatility and regime flips.

Question: after a central-bank statement whose tone is unusually far from that bank's recent
tone, is EUR/USD or USD/CHF more volatile over the next five trading days, and does the filtered
regime flip more often over the next ten? Never direction — only |moves| and regime changes.

Design
* Anchor = the trading day on which the statement became known (cb_features.effective_date).
* vol_change   = log( mean |ret_1d| over t+1..t+5  /  mean |ret_1d| over t-20..t-1 )
* flip_10      = 1 if the filtered regime at any of t+1..t+10 differs from the regime at t
* Statements are split at the median |tone_surprise| (high vs low surprise).
* Placebo band: 1000 random anchors that are not within +-1 day of any statement; the band is
  the 2.5-97.5 percentile of the mean statistic over random samples the same size as ours.
Word lists have no memory of outcomes, so running them on history is legitimate; FinBERT/LLM
scores are NOT used here (live-only).

Outputs: reports/cb_event_study_vol.png, reports/cb_event_study_flips.png, reports/cb_index.md
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from fxradar import cb_features, cb_lexicon, cb_text, config  # noqa: E402
from fxradar import tokens as tk  # noqa: E402

PAIRS = ["EURUSD", "USDCHF"]
PRE, POST_VOL, POST_FLIP = 20, 5, 10
PATH_LO, PATH_HI = -5, 10
N_PLACEBO = 1000
SEED = 29
REPORTS = config.REPORTS_DIR
# phase-31 design tokens (docs/report surfaces)
BG, CARD, TEXT, MUTED = tk.BG, tk.SURFACE, tk.TEXT, tk.MUTED
CALM, TREND, CHOP, CRISIS, BEACON = (
    tk.REGIME_COLORS["calm"],
    tk.REGIME_COLORS["trend"],
    tk.REGIME_COLORS["chop"],
    tk.REGIME_COLORS["crisis"],
    tk.ACCENT,
)


def _series(frame: pd.DataFrame, pair: str, col: str) -> pd.Series:
    s = frame[frame["pair"] == pair].set_index("date")[col].sort_index()
    return s[~s.index.duplicated()]


def event_stats(absret: pd.Series, regime: pd.Series, anchors: list[int]) -> pd.DataFrame:
    """Per anchor index: vol_change, flip_10 and the |ret| path (normalised by the pre-window)."""
    a = absret.to_numpy()
    r = regime.to_numpy()
    rows = []
    for i in sorted(set(anchors)):
        if i - PRE < 0 or i + max(POST_FLIP, PATH_HI) >= len(a):
            continue
        pre = a[i - PRE : i].mean()
        post = a[i + 1 : i + 1 + POST_VOL].mean()
        if pre <= 0 or post <= 0:
            continue
        path = a[i + PATH_LO : i + PATH_HI + 1] / pre
        flips = np.array([int(r[i + h] != r[i]) for h in range(1, POST_FLIP + 1)])
        rows.append(
            {
                "i": i,
                "vol_change": float(np.log(post / pre)),
                "flip_10": int(flips.any()),
                "flip_curve": np.maximum.accumulate(flips),
                "path": path,
            }
        )
    return pd.DataFrame(rows)


def placebo_band(ev: pd.DataFrame, n_sample: int, rng: np.random.Generator) -> dict:
    """2.5/97.5 percentiles of the mean statistic over N_PLACEBO random samples of size n_sample."""
    idx = np.arange(len(ev))
    vol, flip, path, curve = [], [], [], []
    for _ in range(N_PLACEBO):
        take = rng.choice(idx, size=min(n_sample, len(idx)), replace=False)
        sub = ev.iloc[take]
        vol.append(sub["vol_change"].mean())
        flip.append(sub["flip_10"].mean())
        path.append(np.vstack(sub["path"]).mean(axis=0))
        curve.append(np.vstack(sub["flip_curve"]).mean(axis=0))
    return {
        "vol": np.percentile(vol, [2.5, 97.5]),
        "flip": np.percentile(flip, [2.5, 97.5]),
        "path": np.percentile(np.vstack(path), [2.5, 97.5], axis=0),
        "curve": np.percentile(np.vstack(curve), [2.5, 97.5], axis=0),
        "vol_mean": float(np.mean(vol)),
        "flip_mean": float(np.mean(flip)),
    }


def permutation_band(values: np.ndarray, n_high: int, rng: np.random.Generator) -> np.ndarray:
    """2.5/97.5 pct of mean(high) - mean(low) when the high/low labels are shuffled N_PLACEBO times."""
    diffs = []
    for _ in range(N_PLACEBO):
        perm = rng.permutation(values)
        diffs.append(perm[:n_high].mean() - perm[n_high:].mean())
    return np.percentile(diffs, [2.5, 97.5])


def _style(ax, title: str) -> None:
    ax.set_facecolor(CARD)
    ax.set_title(title, color=TEXT, fontsize=11, loc="left")
    ax.tick_params(colors=MUTED, labelsize=8)
    for sp in ax.spines.values():
        sp.set_color(tk.BORDER)
    ax.grid(True, color=tk.BORDER, lw=0.5, alpha=0.6)


def main() -> None:
    docs = cb_text.load_docs()
    if not docs:
        print("no documents in data/cb/ — run `python -m fxradar.cb_text --backfill --since 2020`")
        return
    scores = cb_features.add_surprise(cb_lexicon.score_docs(docs))
    feats = pd.read_parquet(config.FEATURES_PATH, columns=["date", "pair", "ret_1d"])
    regs = pd.read_parquet(config.REGIMES_PATH, columns=["date", "pair", "regime"])
    rng = np.random.default_rng(SEED)

    results: dict[str, dict] = {}
    fig_v, axes_v = plt.subplots(1, 2, figsize=(11, 4), facecolor=BG)
    fig_f, axes_f = plt.subplots(1, 2, figsize=(11, 4), facecolor=BG)
    offsets = np.arange(PATH_LO, PATH_HI + 1)
    horizons = np.arange(1, POST_FLIP + 1)
    for pair, ax_v, ax_f in zip(PAIRS, axes_v, axes_f, strict=True):
        absret = _series(feats, pair, "ret_1d").abs()
        regime = _series(regs, pair, "regime").reindex(absret.index).ffill()
        dates = absret.index
        st = scores.dropna(subset=["tone_surprise"]).copy()
        st["i"] = dates.searchsorted(st["effective_date"].to_numpy())
        st = st[st["i"] < len(dates)]
        ev = event_stats(absret, regime, st["i"].tolist())
        st = st.merge(ev, on="i", how="inner")
        if len(st) < 10:
            print(f"{pair}: only {len(st)} usable statements — skipping")
            continue
        st["abs_surprise"] = st["tone_surprise"].abs()
        med = st["abs_surprise"].median()
        hi, lo = st[st["abs_surprise"] > med], st[st["abs_surprise"] <= med]
        # placebo anchors: not within +-1 day of any statement anchor
        banned = set()
        for i in st["i"]:
            banned.update({i - 1, i, i + 1})
        pool = [i for i in range(PRE, len(dates) - PATH_HI - 1) if i not in banned]
        pool = [i for i in pool if dates[i] >= st["effective_date"].min()]
        placebo_ev = event_stats(
            absret, regime, list(rng.choice(pool, size=min(4000, len(pool)), replace=False))
        )
        band = placebo_band(placebo_ev, len(hi), rng)
        vol_diff_band = permutation_band(st["vol_change"].to_numpy(), len(hi), rng)
        flip_diff_band = permutation_band(st["flip_10"].to_numpy().astype(float), len(hi), rng)
        rho = float(pd.Series(st["abs_surprise"]).corr(st["vol_change"], method="spearman"))
        rho_flip = float(pd.Series(st["abs_surprise"]).corr(st["flip_10"], method="spearman"))
        results[pair] = {
            "n_statements": int(len(st)),
            "n_high": int(len(hi)),
            "median_abs_surprise": float(med),
            "vol_change_high": float(hi["vol_change"].mean()),
            "vol_change_low": float(lo["vol_change"].mean()),
            "vol_change_all": float(st["vol_change"].mean()),
            "vol_band": [float(x) for x in band["vol"]],
            "vol_placebo_mean": band["vol_mean"],
            "vol_diff": float(hi["vol_change"].mean() - lo["vol_change"].mean()),
            "vol_diff_band": [float(x) for x in vol_diff_band],
            "flip_diff": float(hi["flip_10"].mean() - lo["flip_10"].mean()),
            "flip_diff_band": [float(x) for x in flip_diff_band],
            "flip_high": float(hi["flip_10"].mean()),
            "flip_low": float(lo["flip_10"].mean()),
            "flip_all": float(st["flip_10"].mean()),
            "flip_band": [float(x) for x in band["flip"]],
            "flip_placebo_mean": band["flip_mean"],
            "spearman_abs_surprise_vs_vol_change": rho,
            "spearman_abs_surprise_vs_flip10": rho_flip,
            "by_bank": {
                b: {
                    "n": int((st["bank"] == b).sum()),
                    "vol_change": float(st.loc[st["bank"] == b, "vol_change"].mean()),
                    "flip_10": float(st.loc[st["bank"] == b, "flip_10"].mean()),
                }
                for b in cb_text.BANKS
                if (st["bank"] == b).sum() > 0
            },
        }
        # --- figures
        _style(ax_v, f"{pair}: |daily move| around statements (÷ pre-20d mean)")
        ax_v.fill_between(
            offsets,
            band["path"][0],
            band["path"][1],
            color=MUTED,
            alpha=0.25,
            label="placebo 95% band",
        )
        ax_v.plot(
            offsets,
            np.vstack(hi["path"]).mean(axis=0),
            color=CRISIS,
            lw=2,
            label=f"high |surprise| (n={len(hi)})",
        )
        ax_v.plot(
            offsets,
            np.vstack(lo["path"]).mean(axis=0),
            color=TREND,
            lw=2,
            label=f"low |surprise| (n={len(lo)})",
        )
        ax_v.axvline(0, color=BEACON, lw=1, ls="--")
        ax_v.set_xlabel("trading days from statement", color=MUTED, fontsize=8)
        ax_v.legend(fontsize=7, facecolor=CARD, labelcolor=TEXT, edgecolor=tk.BORDER)
        _style(ax_f, f"{pair}: P(regime flipped by day h)")
        ax_f.fill_between(
            horizons,
            band["curve"][0],
            band["curve"][1],
            color=MUTED,
            alpha=0.25,
            label="placebo 95% band",
        )
        ax_f.plot(
            horizons,
            np.vstack(hi["flip_curve"]).mean(axis=0),
            color=CRISIS,
            lw=2,
            marker="o",
            ms=3,
            label="high |surprise|",
        )
        ax_f.plot(
            horizons,
            np.vstack(lo["flip_curve"]).mean(axis=0),
            color=TREND,
            lw=2,
            marker="o",
            ms=3,
            label="low |surprise|",
        )
        ax_f.set_xlabel("trading days after statement", color=MUTED, fontsize=8)
        ax_f.set_ylim(0, 1)
        ax_f.legend(fontsize=7, facecolor=CARD, labelcolor=TEXT, edgecolor=tk.BORDER)
    REPORTS.mkdir(parents=True, exist_ok=True)
    for fig, name in ((fig_v, "cb_event_study_vol.png"), (fig_f, "cb_event_study_flips.png")):
        fig.tight_layout()
        fig.savefig(REPORTS / name, dpi=130, facecolor=BG)
        plt.close(fig)
    write_report(docs, scores, results)


def write_report(docs: list[dict], scores: pd.DataFrame, results: dict) -> None:
    per_bank = scores.groupby("bank").agg(
        n=("tone", "size"),
        first=("date", "min"),
        last=("date", "max"),
        tone_mean=("tone", "mean"),
        tone_sd=("tone", "std"),
        uncert_mean=("uncertainty", "mean"),
        surprise_sd=("tone_surprise", "std"),
    )
    live = cb_lexicon.live_tracking_summary(docs)
    lines = [
        "# Central-bank communication index — Stage 1 event study (lexicon leg)",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · lexicon {cb_lexicon.LEXICON_VERSION} · "
        f"{len(docs)} statements on disk · {config.DISCLAIMER}",
        "",
        "## Corpus (official statements only, fetched from the four banks' own sites)",
        "",
        "| bank | n | first | last | mean tone | sd tone | mean uncertainty | sd surprise |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b, r in per_bank.iterrows():
        lines.append(
            f"| {b} | {int(r['n'])} | {r['first'].date()} | {r['last'].date()} | {r['tone_mean']:+.3f} | "
            f"{r['tone_sd']:.3f} | {r['uncert_mean']:.4f} | {r['surprise_sd']:.3f} |"
        )
    lines += [
        "",
        f"Statements since the deploy date ({live['deploy_date']}): **{live['n_since_deploy']}** — "
        + ", ".join(f"{b} {v['n_since_deploy']}" for b, v in live["banks"].items())
        + ". FinBERT / LLM scores exist only for these (none yet if 0).",
        "",
        "## Event study: |tone surprise| vs what followed (no direction, ever)",
        "",
        "Design: anchor = trading day the statement became known; vol_change = log(mean |ret| t+1..t+5 / "
        "mean |ret| t-20..t-1); flip_10 = filtered regime differs from day-t regime at any of t+1..t+10; "
        "statements split at the median |tone_surprise|; placebo band = 2.5-97.5 pct of the mean over "
        f"{N_PLACEBO} random non-statement samples of the same size.",
        "",
        "| pair | n | vol_change high | vol_change low | placebo band (vol) | flip_10 high | flip_10 low | placebo band (flip) | Spearman(|surprise|, vol_change) | Spearman(|surprise|, flip_10) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for pair, r in results.items():
        lines.append(
            f"| {pair} | {r['n_statements']} | {r['vol_change_high']:+.3f} | {r['vol_change_low']:+.3f} | "
            f"[{r['vol_band'][0]:+.3f}, {r['vol_band'][1]:+.3f}] | {r['flip_high']:.2f} | {r['flip_low']:.2f} | "
            f"[{r['flip_band'][0]:.2f}, {r['flip_band'][1]:.2f}] | {r['spearman_abs_surprise_vs_vol_change']:+.3f} | "
            f"{r['spearman_abs_surprise_vs_flip10']:+.3f} |"
        )
    lines += [
        "",
        "Does the SURPRISE matter beyond 'a statement happened'? High-minus-low difference with a "
        f"{N_PLACEBO}-shuffle permutation band (labels reshuffled among the statements):",
        "",
        "| pair | vol_change high−low | permutation band | flip_10 high−low | permutation band |",
        "|---|---|---|---|---|",
    ]
    for pair, r in results.items():
        lines.append(
            f"| {pair} | {r['vol_diff']:+.3f} | [{r['vol_diff_band'][0]:+.3f}, {r['vol_diff_band'][1]:+.3f}] | "
            f"{r['flip_diff']:+.2f} | [{r['flip_diff_band'][0]:+.2f}, {r['flip_diff_band'][1]:+.2f}] |"
        )
    lines += ["", "Per bank (all statements of that bank, both pairs):", ""]
    lines += ["| pair | bank | n | vol_change | flip_10 |", "|---|---|---|---|---|"]
    for pair, r in results.items():
        for b, v in r["by_bank"].items():
            lines.append(
                f"| {pair} | {b} | {v['n']} | {v['vol_change']:+.3f} | {v['flip_10']:.2f} |"
            )
    verdicts = []
    for pair, r in results.items():
        vol_out = not (r["vol_band"][0] <= r["vol_change_high"] <= r["vol_band"][1])
        flip_out = not (r["flip_band"][0] <= r["flip_high"] <= r["flip_band"][1])
        vd_out = not (r["vol_diff_band"][0] <= r["vol_diff"] <= r["vol_diff_band"][1])
        fd_out = not (r["flip_diff_band"][0] <= r["flip_diff"] <= r["flip_diff_band"][1])
        verdicts.append(
            f"* **{pair}** (n = {r['n_statements']}): after ANY statement the next five days are more volatile than "
            f"random days (all-statement vol_change {r['vol_change_all']:+.3f} vs placebo mean {r['vol_placebo_mean']:+.3f}, "
            f"band [{r['vol_band'][0]:+.3f}, {r['vol_band'][1]:+.3f}]) — that is the calendar. The SURPRISE split adds "
            f"{r['vol_diff']:+.3f} (high − low), which is {'OUTSIDE' if vd_out else 'INSIDE'} its permutation band "
            f"[{r['vol_diff_band'][0]:+.3f}, {r['vol_diff_band'][1]:+.3f}]; the ten-day flip-rate difference is "
            f"{r['flip_diff']:+.2f} ({'OUTSIDE' if fd_out else 'INSIDE'} its band). High-surprise vol_change "
            f"{r['vol_change_high']:+.3f} is {'outside' if vol_out else 'inside'} the random-day band; its flip rate "
            f"{r['flip_high']:.0%} is {'outside' if flip_out else 'inside'}. Spearman(|surprise|, vol_change) = "
            f"{r['spearman_abs_surprise_vs_vol_change']:+.2f}."
        )
    lines += [
        "",
        "## Honest reading",
        "",
        *verdicts,
        "",
        "* Four high−low differences are tested (2 pairs × vol/flip); one outside its band at the 5% level is "
        "what chance alone produces, and a difference in the counter-intuitive sense (FEWER flips after high "
        "surprise) is read as noise — most likely the tone ratio saturating at ±1 on short statements, which "
        "inflates |surprise| for the briefest (often calm-period) releases. We do not claim an effect from it.",
        "* Verdict for the Stage-2 gate: a credible live effect means the high−low SURPRISE difference outside "
        "its permutation band, on LIVE (post-2026-08-17) statements. The historical lexicon result above is "
        "the benchmark the live record will be held to — it is not itself evidence for opening the gate.",
        "* The corpus is small (a few dozen statements per bank since 2020), the tone ratio saturates at ±1 on "
        "very short statements (two or three hits), and the lexicon is a deliberately simple frozen word "
        "list, so single-pair, single-split numbers like these are noisy; a point estimate inside a band is "
        "'no detectable effect', not 'no effect'.",
        "* Statement days cluster with other scheduled macro events, so some of any excess volatility is the "
        "calendar, not the words; the phase-23 `days_to_*` features carry that part.",
        "* Nothing here is a trading signal. The lexicon features may join the CHALLENGER forecaster only "
        "(volatility / regime targets), and Stage 2 (LLM) stays gated — see docs/stage2-decision.md.",
        "",
        "Figures: `reports/cb_event_study_vol.png`, `reports/cb_event_study_flips.png`.",
        "",
        f"*{config.DISCLAIMER}*",
    ]
    out = REPORTS / "cb_index.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
