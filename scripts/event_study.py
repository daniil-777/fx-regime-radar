"""Event study (phase 23): what does the radar do around scheduled macro events?

For each event type in data/events.csv and each relative trading day k in -10..+10 (k = 0 is the
event day, k < 0 the run-up, k > 0 the aftermath), pooled across pairs:
* mean change_risk_5d (the shipped forecaster's calibrated 5-day regime-change risk);
* regime-flip frequency: share of rows whose filtered regime label differs from the previous day.

Placebo band: the same statistic for >= 1000 seeded draws of random NON-event anchors (any day that is not
an event day of that type and has a full window), each draw the size of the real event sample;
the 5th/95th percentiles per relative day are the band. A curve that leaves the band is a
pattern the calendar explains; one that stays inside is indistinguishable from luck.

Outputs: reports/event_study_<TYPE>.png, reports/event_study.md. Reads artifacts only (rule 8):
data/regimes.parquet + data/events.csv. Run: .venv/bin/python scripts/event_study.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxradar import calendar_ext, config  # noqa: E402
from fxradar import tokens as tk  # noqa: E402

WINDOW = 10
N_PLACEBO = 1000
SEED = 23
COLORS = tk.REGIME_COLORS


def _per_pair_arrays(regimes: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """{pair: (dates, change_risk, flip)} sorted by date."""
    out = {}
    for pair, g in regimes.sort_values("date").groupby("pair"):
        risk = g["change_risk_5d"].to_numpy(dtype=float)
        flip = g["regime"].ne(g["regime"].shift(1)).to_numpy(dtype=float)
        flip[0] = np.nan
        out[pair] = (g["date"].to_numpy(dtype="datetime64[ns]"), risk, flip)
    return out


def _anchor_indices(dates: np.ndarray, event_dates: np.ndarray) -> np.ndarray:
    """Index of the first trading day >= each event date (events on non-trading days roll
    forward); only anchors with a full -W..+W window are kept."""
    idx = np.searchsorted(dates, event_dates, side="left")
    ok = (idx >= WINDOW) & (idx < len(dates) - WINDOW)
    return idx[ok]


def _window_matrix(values: np.ndarray, anchors: np.ndarray) -> np.ndarray:
    """(n_anchors, 2W+1) matrix of `values` around each anchor."""
    offs = np.arange(-WINDOW, WINDOW + 1)
    return values[anchors[:, None] + offs[None, :]]


def study_type(
    arrays: dict, events: pd.DataFrame, etype: str, rng: np.random.Generator
) -> dict | None:
    ev = events.loc[events["type"] == etype, "date"].to_numpy(dtype="datetime64[ns]")
    risk_rows, flip_rows, placebo_risk, placebo_flip = [], [], [], []
    n_events = 0
    for _pair, (dates, risk, flip) in arrays.items():
        anchors = _anchor_indices(dates, ev)
        if len(anchors) == 0:
            continue
        n_events += len(anchors)
        risk_rows.append(_window_matrix(risk, anchors))
        flip_rows.append(_window_matrix(flip, anchors))
        # eligible placebo anchors: any non-event day with a full window. Deliberately NOT
        # "far from every event" — that would make the placebo a mid-cycle day, a biased
        # comparison; a random day is the right null for "is an event day special?"
        eligible = np.setdiff1d(np.arange(WINDOW, len(dates) - WINDOW), anchors)
        draws = rng.choice(eligible, size=(N_PLACEBO, len(anchors)), replace=True)
        placebo_risk.append(
            np.nanmean(risk[draws[:, :, None] + np.arange(-WINDOW, WINDOW + 1)], axis=1)
        )
        placebo_flip.append(
            np.nanmean(flip[draws[:, :, None] + np.arange(-WINDOW, WINDOW + 1)], axis=1)
        )
    if not risk_rows:
        return None
    risk_m = np.vstack(risk_rows)
    flip_m = np.vstack(flip_rows)
    # pooled placebo: weight each pair's draw means by its anchor count (same pooling as the real)
    weights = np.array([m.shape[0] for m in risk_rows], dtype=float)
    pr = sum(w * p for w, p in zip(weights, placebo_risk, strict=True)) / weights.sum()
    pf = sum(w * p for w, p in zip(weights, placebo_flip, strict=True)) / weights.sum()
    return {
        "type": etype,
        "n_events": int(n_events),
        "risk_mean": np.nanmean(risk_m, axis=0),
        "flip_mean": np.nanmean(flip_m, axis=0),
        "risk_band": np.nanpercentile(pr, [5, 95], axis=0),
        "flip_band": np.nanpercentile(pf, [5, 95], axis=0),
        "placebo_risk_median": np.nanmedian(pr, axis=0),
        "placebo_flip_median": np.nanmedian(pf, axis=0),
    }


def plot(res: dict, reports_dir: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": tk.BG,
            "axes.facecolor": tk.SURFACE,
            "axes.edgecolor": tk.BORDER,
            "text.color": tk.TEXT,
            "axes.labelcolor": tk.TEXT,
            "xtick.color": tk.MUTED,
            "ytick.color": tk.MUTED,
            "grid.color": tk.BORDER,
        }
    )
    k = np.arange(-WINDOW, WINDOW + 1)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.8))
    for ax, key, band, title, color in [
        (axes[0], "risk_mean", "risk_band", "mean 5-day change risk", tk.REGIME_COLORS["trend"]),
        (axes[1], "flip_mean", "flip_band", "regime-flip frequency", tk.REGIME_COLORS["chop"]),
    ]:
        lo, hi = res[band]
        ax.fill_between(k, lo, hi, color=tk.MUTED, alpha=0.25, lw=0, label="placebo 5–95%")
        ax.plot(k, res[key], color=color, marker="o", ms=3, lw=1.5, label=f"{res['type']} events")
        ax.axvline(0, color=tk.TEXT, lw=0.8, ls="--", alpha=0.6)
        ax.set_title(f"{res['type']} — {title}", loc="left", fontsize=10)
        ax.set_xlabel("trading days relative to event (0 = event day)")
        ax.grid(alpha=0.3)
        ax.legend(frameon=False, fontsize=8)
    fig.suptitle(
        f"{res['n_events']} pooled event windows, placebo = {N_PLACEBO} random non-event draws (seed {SEED})",
        fontsize=9,
        color=tk.MUTED,
        x=0.01,
        ha="left",
    )
    fig.tight_layout()
    path = reports_dir / f"event_study_{res['type']}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def main() -> None:
    regimes = pd.read_parquet(config.REGIMES_PATH)
    events = calendar_ext.load_events()
    events = events[events["date"] <= regimes["date"].max()]
    arrays = _per_pair_arrays(regimes)
    rng = np.random.default_rng(SEED)
    reports_dir = config.REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows, summary = [], []
    for etype in calendar_ext.EVENT_TYPES:
        res = study_type(arrays, events, etype, rng)
        if res is None:
            continue
        plot(res, reports_dir)
        k = np.arange(-WINDOW, WINDOW + 1)
        out_r = (res["risk_mean"] > res["risk_band"][1]) | (res["risk_mean"] < res["risk_band"][0])
        out_f = (res["flip_mean"] > res["flip_band"][1]) | (res["flip_mean"] < res["flip_band"][0])
        summary.append(
            {
                "type": etype,
                "n_events": res["n_events"],
                "risk_day0": res["risk_mean"][WINDOW],
                "risk_placebo_median_day0": res["placebo_risk_median"][WINDOW],
                "flip_day0": res["flip_mean"][WINDOW],
                "flip_day+1": res["flip_mean"][WINDOW + 1],
                "flip_placebo_median_day0": res["placebo_flip_median"][WINDOW],
                "days_outside_band_risk": int(out_r.sum()),
                "days_outside_band_flip": int(out_f.sum()),
                "outside_days_flip": ",".join(str(int(x)) for x in k[out_f]) or "-",
            }
        )
        for i, kk in enumerate(k):
            rows.append(
                {
                    "type": etype,
                    "k": int(kk),
                    "risk_mean": res["risk_mean"][i],
                    "risk_lo": res["risk_band"][0][i],
                    "risk_hi": res["risk_band"][1][i],
                    "flip_mean": res["flip_mean"][i],
                    "flip_lo": res["flip_band"][0][i],
                    "flip_hi": res["flip_band"][1][i],
                }
            )
    table = pd.DataFrame(summary)
    full = pd.DataFrame(rows)
    full.to_csv(reports_dir / "event_study_curves.csv", index=False)

    def md(df: pd.DataFrame) -> str:
        cols = list(df.columns)
        out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
        for r in df.itertuples(index=False):
            out.append(
                "| " + " | ".join(f"{v:.3f}" if isinstance(v, float) else str(v) for v in r) + " |"
            )
        return "\n".join(out)

    text = [
        "# Event study — the radar around scheduled macro events\n",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Window -{WINDOW}..+{WINDOW} trading days, pooled across {len(arrays)} pairs; data/regimes.parquet through {regimes['date'].max().date()}; events from data/events.csv (scheduled dates only). Placebo band = 5th/95th percentile of the same statistic over {N_PLACEBO} seeded draws of random non-event anchors (any non-event day with a full window), each the size of the real sample._\n",
        "## Summary\n",
        md(table) + "\n",
        "`flip_day0` = share of event days on which the filtered regime label differs from the day before (flips happen at +1..+5 too, so see the figures); `days_outside_band_*` counts relative days whose mean leaves the placebo band (21 days per curve; ~2 would leave it by chance at 90% coverage).\n",
        "## Figures\n",
        *[f"![{t}](event_study_{t}.png)\n" for t in table["type"]],
        "## How to read it\n",
        "The placebo separates signal from luck: if the event curve sits inside the grey band, an event day is statistically indistinguishable from a random day for this radar. Flip frequency is the honest metric — it is what the forecaster's label actually measures; change risk is the model's opinion. A bump at k = 0 / +1 says the HMM's label reacts to the event day's move (events are scheduled, the move is not); a lead BEFORE k = 0 would say the forecaster partly conditions on the run-up already (via vol_ratio, entropy) — and the challenger's days_to_* features make that explicit. No price direction is studied here.\n",
        "\n_Educational tool. Not investment advice._\n",
    ]
    (reports_dir / "event_study.md").write_text("\n".join(text))
    print(table.round(3).to_string(index=False))
    print(f"\nwrote {reports_dir / 'event_study.md'} + {len(table)} figures")


if __name__ == "__main__":
    main()
