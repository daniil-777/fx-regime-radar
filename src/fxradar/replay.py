"""Storm replays: the radar re-run day by day through named crises, exactly as it would have seen them.

For every trading day t in a window the raw prices are TRUNCATED at t (nothing after t exists) and
pushed through the SAME loaded-model scoring path the daily pipeline uses — features ->
filtered HMM -> forecaster -> siren (-> BOCPD / conformal when those modules exist). Only day t's
rows are kept. Because every feature and the HMM forward filter are causal, the replayed row at t
must equal the row the full-history artifact holds for t; `tests/test_replay.py` asserts exactly
that against data/regimes.parquet and against the live ledger. Nothing is refit here, ever.

Honesty rules baked in:
* Windows are fixed in advance (the three named crises every Swiss treasurer remembers) — see
  SELECTION_RULE. No window is chosen after seeing the results, and whatever the replay shows is
  what the report says.
* A replay is a causal reconstruction, NOT the live record. The live record is the hash-chained
  ledger (see the Proof page); every replay surface says so.
* Report text is built from templates over the computed numbers: no hindsight adjectives, no
  direction words (regimes, change risk and anomalies — never where the price goes).

Also here: the auto post-mortem stage. When the daily pipeline sees a live entry into `crisis`
for any pair, `stage(ctx)` drafts reports/postmortems/<date>_<pair>.md from the last 30 live rows,
flagged DRAFT for human review.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import config, features, forecaster, siren, tokens
from fxradar import hmm_model as hm

log = logging.getLogger(__name__)

# The ONLY hex literals in this module: report-png palette (phase-31 design tokens, dark variant).
# The orchestrator will move this dict to the shared token file later — keep it one dict.
PALETTE: dict[str, str] = {  # from design/tokens.json (phase 31) — no hex literals here
    "bg": tokens.BG,
    "surface": tokens.SURFACE,
    "text": tokens.TEXT,
    "muted": tokens.MUTED,
    "faint": tokens.DIM,
    "line": tokens.BORDER,
    "accent": tokens.ACCENT,
    **tokens.REGIME_COLORS,
}

REPLAYS_PATH = config.DATA_DIR / "storm_replays.json"
STORMS_DIR = config.REPORTS_DIR / "storms"
POSTMORTEM_DIR = config.REPORTS_DIR / "postmortems"
LIVE_RECORD_PATH = config.DATA_DIR / "live_record.json"
SIREN_LOUD = 98.0  # anomaly percentile we call "loud" (phase-08 validation convention)
POSTMORTEM_DAYS = 30

SELECTION_RULE = (
    "Windows are the three named crises every Swiss treasurer remembers, fixed in advance; "
    "no window was chosen after seeing the results."
)
CAUSAL_NOTE = (
    "Causal reconstruction — not the live record. The live record starts {since}; "
    "see the Proof page."
)

# Fixed in advance. The replay always computes all pairs; `pair` is the one the report tells.
WINDOWS: dict[str, dict] = {
    "covid_2020": {
        "title": "COVID — February to April 2020",
        "pair": "EURUSD",
        "start": "2020-02-03",
        "end": "2020-04-30",
        "event_date": "2020-03-11",
        "event_label": "the WHO pandemic declaration (11 March)",
        "context": "The WHO declared a pandemic on 11 March 2020; the Federal Reserve's emergency "
        "rate decisions came on 3 and 15 March and dollar swap lines were widened on 19 March.",
    },
    "credit_suisse_2023": {
        "title": "Credit Suisse — March 2023",
        "pair": "USDCHF",
        "start": "2023-03-01",
        "end": "2023-03-31",
        "event_date": "2023-03-19",
        "event_label": "the announcement of the UBS takeover (Sunday 19 March; first trading day 20 March)",
        "context": "Silicon Valley Bank failed on Friday 10 March 2023; on 15 March Credit Suisse's "
        "largest shareholder ruled out further capital and the SNB announced a liquidity backstop "
        "that night; UBS's takeover of Credit Suisse was announced on Sunday 19 March.",
    },
    "snb_2015": {
        "title": "SNB floor removal — January 2015",
        "pair": "USDCHF",
        "start": "2015-01-05",
        "end": "2015-01-30",
        "event_date": "2015-01-15",
        "event_label": "the EUR/CHF floor removal (15 January)",
        "context": "The SNB discontinued the EUR/CHF minimum exchange rate of 1.20 on 15 January "
        "2015 at 10:30 CET, without prior signal; its next scheduled policy assessment was "
        "19 March.",
    },
}

REPLAY_COLUMNS: list[str] = [
    "date",
    "pair",
    "regime",
    "regime_prob",
    "hmm_entropy",
    "days_in_regime",
    "p_calm",
    "p_trend",
    "p_chop",
    "p_crisis",
    "change_risk_5d",
    "top_drivers",
    "anomaly_score",
    "anomaly_pct",
    "risk_lo",
    "risk_hi",
    "conformal_q",
    "bocpd_p_change_5d",
    "agreement",
    "consensus_text",
]
EXTRA_COLUMNS = ["risk_lo", "risk_hi", "conformal_q", "bocpd_p_change_5d", "agreement"]

# Optional phase-21/22 modules: present -> their columns are filled; absent -> NaN. Never required.
try:  # pragma: no cover - depends on the orchestrator's progress
    from fxradar import bocpd as _bocpd
except ImportError:  # pragma: no cover
    _bocpd = None
try:  # pragma: no cover
    from fxradar import conformal as _conformal
except ImportError:  # pragma: no cover
    _conformal = None


# --------------------------------------------------------------------------------------
# models (loaded once, never refit)
# --------------------------------------------------------------------------------------
_MODELS: dict | None = None


def load_models(models_dir: Path = config.MODELS_DIR) -> dict:
    """The saved HMM bundles, forecaster (model, meta) and siren bundle — cached per process."""
    global _MODELS
    if _MODELS is None:
        _MODELS = {
            "hmm": hm.load_bundles(models_dir=models_dir),
            "fc": forecaster.load_model(models_dir=models_dir),
            "siren": siren.load_bundle(models_dir=models_dir),
        }
    return _MODELS


def frozen_precision(models: dict | None = None) -> float | None:
    """The forecaster's frozen test-set precision at the threshold (from the meta scoreboard)."""
    models = models or load_models()
    for row in models["fc"][1].get("test_scoreboard", []):
        if str(row.get("model", "")).startswith("XGBoost (ours"):
            return float(row["precision"])
    return None


def threshold(models: dict | None = None) -> float:
    """The forecaster's frozen alarm threshold (chosen on validation, stored in the meta json)."""
    models = models or load_models()
    return float(models["fc"][1].get("threshold", 0.22))


# --------------------------------------------------------------------------------------
# one as-of scoring pass (the daily pipeline's path, on data truncated at t)
# --------------------------------------------------------------------------------------
def _extras(regimes: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    """Conformal band + BOCPD/consensus columns per (date, pair), when those modules exist.

    `regimes` must hold every row <= t (BOCPD is a recursion like the HMM filter). Every call is
    wrapped: a missing module, missing fitted params or a changed signature yields NaN columns,
    never a crash — the replay never depends on phases 21/22.
    """
    reg = regimes
    if _conformal is not None:
        try:
            reg = _conformal.apply(
                reg
            )  # risk_lo / risk_hi / conformal_q from models/conformal_v1.json
        except Exception as exc:  # defensive by design
            log.debug("conformal.apply skipped: %s", exc)
    if _bocpd is not None:
        try:
            if hasattr(_bocpd, "score_all"):  # BOCPD per pair + consensus, params from models/
                reg = _bocpd.score_all(reg, feats)
            else:  # older surface: score_pair + consensus
                parts = []
                for _, g in feats.sort_values("date").groupby("pair", sort=False):
                    b = _bocpd.score_pair(g["ret_1d"]).reset_index(drop=True)
                    parts.append(pd.concat([g[["date", "pair"]].reset_index(drop=True), b], axis=1))
                reg = reg.merge(
                    pd.concat(parts, ignore_index=True), on=["date", "pair"], how="left"
                )
                reg = reg.merge(_bocpd.consensus(reg, feats), on=["date", "pair"], how="left")
        except Exception as exc:
            log.debug("bocpd skipped: %s", exc)
    wanted = [*EXTRA_COLUMNS, "consensus_text"]
    have = [c for c in wanted if c in reg.columns]
    out = regimes[["date", "pair"]].merge(
        reg[["date", "pair", *have]].drop_duplicates(["date", "pair"]),
        on=["date", "pair"],
        how="left",
    )
    for c in wanted:
        if c not in out.columns:
            out[c] = None if c == "consensus_text" else np.nan
    return out


def score_asof(
    prices_t: pd.DataFrame, pairs: list[str] | None = None, models: dict | None = None
) -> pd.DataFrame:
    """Score the newest day of `prices_t` (prices already truncated at t) exactly as run_daily does.

    * features.build_features on everything <= t (all pairs: corr_20 needs the others);
    * hmm_model.score_all with the saved bundles on the full truncated history (the forward filter
      is a recursion, so it is run from the first row — that is the only way to be bit-identical);
    * forecaster.build_matrix + forecaster.score and the siren's reconstruction error + percentile
      on the newest row per pair only — both are row-wise models (XGBoost/Platt, MLP vs a frozen
      train-period reference), so scoring one row gives the same number as scoring the history,
      which tests/test_replay.py proves against data/regimes.parquet.
    Returns one row per pair for the newest date, REPLAY_COLUMNS.
    """
    models = models or load_models()
    pairs = list(pairs or config.PAIRS)
    bundles = {p: models["hmm"][p] for p in pairs}
    fc_model, fc_meta = models["fc"]
    siren_bundle = models["siren"]

    feats = features.build_features(prices_t)
    scored = hm.score_all(feats[feats["pair"].isin(pairs)], bundles)
    regimes = scored[[c for c in scored.columns if c in hm.REGIME_COLUMNS or c.startswith("p_")]]
    feats = feats[feats["pair"].isin(pairs)].merge(
        scored[["date", "pair", *hm.POST_HMM_FEATURES]], on=["date", "pair"], how="left"
    )
    newest = regimes.sort_values(["pair", "date"]).groupby("pair").tail(1)

    matrix = forecaster.build_matrix(feats, regimes).sort_values(["pair", "date"])
    fc_rows = forecaster.score(fc_model, matrix.groupby("pair").tail(1), fc_meta)

    joined = siren.joined(feats, regimes).groupby("pair").tail(1)
    err = siren.reconstruction_errors(siren_bundle, joined)  # same two lines as siren.score
    siren_rows = joined[["date", "pair"]].copy()
    siren_rows["anomaly_score"] = err.mean(axis=1)
    siren_rows["anomaly_pct"] = siren.percentile_of(
        siren_rows["anomaly_score"].to_numpy(), siren_bundle["train_scores"]
    )

    out = (
        newest.merge(fc_rows, on=["date", "pair"], how="left")
        .merge(siren_rows, on=["date", "pair"], how="left")
        .merge(_extras(regimes.merge(fc_rows, on=["date", "pair"], how="left"), feats), how="left")
    )
    for c in REPLAY_COLUMNS:
        if c not in out.columns:
            out[c] = None if c in ("consensus_text", "top_drivers") else np.nan
    return out[REPLAY_COLUMNS].sort_values("pair").reset_index(drop=True)


# --------------------------------------------------------------------------------------
# the replay loop
# --------------------------------------------------------------------------------------
def trading_days(prices: pd.DataFrame, start: str, end: str) -> list[pd.Timestamp]:
    """Every date with at least one price row in [start, end]."""
    d = prices["date"]
    return [
        pd.Timestamp(x)
        for x in sorted(d[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))].unique())
    ]


def replay(
    prices: pd.DataFrame,
    start: str,
    end: str,
    pairs: list[str] | None = None,
    models: dict | None = None,
    warmup_days: int | None = None,
    progress: bool = False,
) -> pd.DataFrame:
    """Day-by-day causal replay of [start, end]: one row per (date, pair), REPLAY_COLUMNS.

    For each trading day t the prices are truncated at t — `prices[date <= t]` — and scored from
    scratch with the saved models. `warmup_days=None` (default) keeps the whole history before t,
    which reproduces the full-history artifact bit-for-bit. A trailing window (e.g. 600 rows per
    pair) is faster but only agrees to ~1e-9: pandas' online rolling std carries ~1e-16 of state
    from earlier rows and the forward filter forgets its prior only asymptotically — float drift,
    not look-ahead; the flagship replays use the exact default. The BOCPD/consensus extras are NOT
    comparable under a trailing window (the run length is capped by it) — use the default for them.
    """
    models = models or load_models()
    pairs = list(pairs or config.PAIRS)
    prices = prices.sort_values(["pair", "date"]).reset_index(drop=True)
    days = trading_days(prices, start, end)
    rows = []
    for i, t in enumerate(days):
        cut = prices[prices["date"] <= t]
        if warmup_days is not None:
            cut = cut[cut.groupby("pair").cumcount(ascending=False) < warmup_days]
        day = score_asof(cut, pairs=pairs, models=models)
        rows.append(day[day["date"] == t])  # a pair without a bar on t contributes nothing
        if progress and (i % 10 == 0 or i == len(days) - 1):
            log.info("replay %s..%s: day %d/%d (%s)", start, end, i + 1, len(days), t.date())
    if not rows:
        return pd.DataFrame(columns=REPLAY_COLUMNS)
    return pd.concat(rows, ignore_index=True).sort_values(["pair", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# storyline: numbers -> named moments (no adjectives, no direction)
# --------------------------------------------------------------------------------------
def _d(ts) -> str | None:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def _runs(labels: pd.Series) -> list[tuple[int, int]]:
    """(start_idx, length) of every run of the value True in a boolean series."""
    runs, start = [], None
    vals = labels.to_numpy()
    for i, v in enumerate(vals):
        if v and start is None:
            start = i
        if (not v or i == len(vals) - 1) and start is not None:
            runs.append((start, (i if not v else i + 1) - start))
            start = None
    return runs


def storyline(rows: pd.DataFrame, thr: float) -> dict:
    """Named moments of one pair's replay rows (sorted by date): first alarm (change risk >= thr),
    first crisis day, peak siren day, lag alarm->flip, crisis length. Everything is a number
    or a date; the prose layer only fills templates."""
    g = rows.sort_values("date").reset_index(drop=True)
    risk = g["change_risk_5d"].astype(float)
    alarm = risk >= thr
    crisis = g["regime"] == "crisis"
    first_alarm = g.loc[alarm.idxmax(), "date"] if alarm.any() else None
    first_crisis = g.loc[crisis.idxmax(), "date"] if crisis.any() else None
    peak_i = (
        int(g["anomaly_pct"].astype(float).idxmax()) if g["anomaly_pct"].notna().any() else None
    )
    crisis_runs = _runs(crisis)
    longest = max((n for _, n in crisis_runs), default=0)
    lag = None
    if first_alarm is not None and first_crisis is not None:
        lag = int((g["date"] > first_alarm).sum() - (g["date"] > first_crisis).sum())
    pre = g[g["date"] < first_crisis] if first_crisis is not None else g
    return {
        "pair": str(g["pair"].iloc[0]),
        "start": _d(g["date"].iloc[0]),
        "end": _d(g["date"].iloc[-1]),
        "n_days": int(len(g)),
        "threshold": float(thr),
        "regime_start": str(g["regime"].iloc[0]),
        "regime_end": str(g["regime"].iloc[-1]),
        "regimes_seen": sorted(set(g["regime"].astype(str))),
        "first_alarm": _d(first_alarm),
        "first_alarm_risk": float(risk[alarm].iloc[0]) if alarm.any() else None,
        "n_alarm_days": int(alarm.sum()),
        "max_risk": float(risk.max()),
        "max_risk_date": _d(g.loc[risk.idxmax(), "date"]),
        "first_crisis": _d(first_crisis),
        "n_crisis_days": int(crisis.sum()),
        "longest_crisis_run": int(longest),
        "last_crisis": _d(g.loc[crisis[crisis].index[-1], "date"]) if crisis.any() else None,
        "alarm_to_flip_days": lag,
        "peak_siren": _d(g.loc[peak_i, "date"]) if peak_i is not None else None,
        "peak_siren_pct": float(g.loc[peak_i, "anomaly_pct"]) if peak_i is not None else None,
        "n_loud_days": int((g["anomaly_pct"].astype(float) >= SIREN_LOUD).sum()),
        "pre_crisis_max_risk": float(pre["change_risk_5d"].max()) if len(pre) else None,
        "pre_crisis_max_siren": float(pre["anomaly_pct"].max()) if len(pre) else None,
        "pre_crisis_days": int(len(pre)),
    }


def _pct(x: float | None) -> str:
    return "–" if x is None or pd.isna(x) else f"{100 * float(x):.0f} %"


def narrative(story: dict, window: dict | None = None) -> dict[str, str]:
    """Buildup / alarm timing / aftermath paragraphs from the storyline numbers. Templates only:
    no hindsight adjectives, no direction words, no advice."""
    thr = story["threshold"]
    pair = story["pair"]
    first_alarm, first_crisis = story["first_alarm"], story["first_crisis"]
    ev = (window or {}).get("event_label")
    ev_date = (window or {}).get("event_date")

    # buildup: what the radar showed before the first crisis day (or over the whole window)
    if story["pre_crisis_days"] == 0:
        buildup = (
            f"{pair} was already in the {story['regime_start']} regime on the first day of the "
            f"window, so there is no buildup inside the window to describe."
        )
    else:
        span = (
            f"From {story['start']} until the day before {first_crisis}"
            if first_crisis
            else f"Over the whole window ({story['start']} to {story['end']})"
        )
        buildup = (
            f"{pair} started the window in the {story['regime_start']} regime. {span}, change risk "
            f"peaked at {_pct(story['pre_crisis_max_risk'])} (alarm threshold {_pct(thr)}) and the "
            f"siren peaked at percentile {story['pre_crisis_max_siren']:.0f}."
        )
    if ev and ev_date:
        buildup += f" The reference event for this window is {ev}."
    if (window or {}).get("context"):
        buildup += f" Context: {window['context']}"

    # alarm timing
    if first_alarm:
        alarm = (
            f"The first alarm — change risk at or above the frozen threshold of {_pct(thr)} — came on "
            f"{first_alarm} ({_pct(story['first_alarm_risk'])}). Change risk was at or above the threshold on "
            f"{story['n_alarm_days']} of {story['n_days']} days, with a maximum of {_pct(story['max_risk'])} "
            f"on {story['max_risk_date']}."
        )
    else:
        alarm = (
            f"Change risk never reached the frozen threshold of {_pct(thr)} in this window "
            f"(maximum {_pct(story['max_risk'])} on {story['max_risk_date']})."
        )
    if first_crisis:
        alarm += f" The regime label first read crisis on {first_crisis}."
        lag = story["alarm_to_flip_days"]
        if lag is not None:
            if lag > 0:
                alarm += (
                    f" That is {lag} trading day{'s' if lag != 1 else ''} after the first alarm."
                )
            elif lag == 0:
                alarm += " The first alarm and the first crisis day coincide."
            else:
                alarm += (
                    f" The first alarm came {-lag} trading day{'s' if lag != -1 else ''} AFTER the "
                    f"regime flip — the change-risk gauge did not warn ahead of this one."
                )
    else:
        alarm += " The regime label never read crisis in this window."
    if story["peak_siren"]:
        alarm += (
            f" The siren peaked on {story['peak_siren']} at percentile {story['peak_siren_pct']:.0f}; "
            f"{story['n_loud_days']} day{'s' if story['n_loud_days'] != 1 else ''} scored at or above "
            f"{SIREN_LOUD:.0f}."
        )

    # aftermath
    if first_crisis:
        aftermath = (
            f"Crisis was the label on {story['n_crisis_days']} of {story['n_days']} days (longest "
            f"unbroken run {story['longest_crisis_run']}, last crisis day {story['last_crisis']}). "
            f"The window ended in the {story['regime_end']} regime."
        )
    else:
        aftermath = (
            f"Regimes seen in the window: {', '.join(story['regimes_seen'])}. "
            f"The window ended in the {story['regime_end']} regime."
        )
    return {"buildup": buildup, "alarm": alarm, "aftermath": aftermath}


# --------------------------------------------------------------------------------------
# rendering: table, png, markdown
# --------------------------------------------------------------------------------------
TABLE_COLUMNS = [
    "date",
    "regime",
    "regime_prob",
    "change_risk_5d",
    "anomaly_pct",
    "risk_lo",
    "risk_hi",
    "consensus_text",
]


def day_table(rows: pd.DataFrame) -> pd.DataFrame:
    """The day-by-day table of one pair: date, regime, confidence, change risk, siren pct,
    interval + consensus when those columns hold values (dropped when entirely empty)."""
    g = rows.sort_values("date")
    t = pd.DataFrame(
        {
            "date": g["date"].dt.strftime("%Y-%m-%d"),
            "regime": g["regime"],
            "confidence": g["regime_prob"].astype(float).round(2),
            "change risk": (100 * g["change_risk_5d"].astype(float)).round(0),
            "siren pct": g["anomaly_pct"].astype(float).round(0),
        }
    )
    if g["risk_lo"].notna().any():
        t["risk lo"] = (100 * g["risk_lo"].astype(float)).round(0)
        t["risk hi"] = (100 * g["risk_hi"].astype(float)).round(0)
    if g["consensus_text"].notna().any():
        t["consensus"] = g["consensus_text"].fillna("–")
    return t.reset_index(drop=True)


def _md_table(t: pd.DataFrame, formats: dict[str, str] | None = None) -> str:
    """Markdown table; floats use `formats[col]` (default whole numbers), NaN prints as –."""
    formats = {"confidence": "{:.2f}", **(formats or {})}
    cols = [str(c) for c in t.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in t.iterrows():
        cells = []
        for c, v in zip(cols, r, strict=True):
            if isinstance(v, float):
                cells.append("–" if pd.isna(v) else formats.get(c, "{:.0f}").format(v))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_png(
    rows: pd.DataFrame, prices: pd.DataFrame, path: Path, title: str, thr: float, event_date=None
) -> Path:
    """Three panels for one pair: close with regime bands, change risk vs threshold, siren pct."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = rows.sort_values("date").reset_index(drop=True)
    pair = str(g["pair"].iloc[0])
    px = prices[(prices["pair"] == pair) & prices["date"].isin(g["date"])].sort_values("date")
    plt.rcParams.update(
        {
            "figure.facecolor": PALETTE["bg"],
            "axes.facecolor": PALETTE["surface"],
            "axes.edgecolor": PALETTE["line"],
            "text.color": PALETTE["text"],
            "axes.labelcolor": PALETTE["muted"],
            "xtick.color": PALETTE["muted"],
            "ytick.color": PALETTE["muted"],
            "grid.color": PALETTE["line"],
            "font.size": 9,
        }
    )
    fig, axes = plt.subplots(
        3, 1, figsize=(11, 7.5), sharex=True, gridspec_kw={"height_ratios": [2.2, 1.3, 1.3]}
    )
    dates = g["date"].to_numpy()
    ends = list(g["date"].iloc[1:]) + [g["date"].iloc[-1] + pd.Timedelta(days=1)]
    for ax in axes:
        for (_, r), end in zip(g.iterrows(), ends, strict=True):  # band t -> next trading day
            ax.axvspan(r["date"], end, color=PALETTE[str(r["regime"])], alpha=0.16, lw=0)
        if event_date is not None:
            ax.axvline(pd.Timestamp(event_date), color=PALETTE["muted"], ls=":", lw=0.9)
        ax.grid(alpha=0.25)
    axes[0].plot(px["date"], px["close"], color=PALETTE["text"], lw=1.4)
    axes[0].set_ylabel(f"{pair} close")
    axes[0].set_title(title, loc="left", fontsize=11, color=PALETTE["text"])
    axes[1].plot(dates, 100 * g["change_risk_5d"].astype(float), color=PALETTE["accent"], lw=1.4)
    axes[1].axhline(100 * thr, color=PALETTE["muted"], ls="--", lw=0.9)
    axes[1].set_ylabel("change risk %")
    axes[1].set_ylim(0, 100)
    axes[2].plot(
        dates, g["anomaly_pct"].astype(float), color=PALETTE["crisis"], lw=1.0, marker="o", ms=3
    )
    axes[2].axhline(SIREN_LOUD, color=PALETTE["muted"], ls="--", lw=0.9)
    axes[2].set_ylabel("siren pct")
    axes[2].set_ylim(0, 103)
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=PALETTE[r], alpha=0.5, label=r) for r in hm.REGIMES
    ]
    fig.legend(
        handles=handles,
        loc="upper right",
        frameon=False,
        ncol=4,
        fontsize=8,
        bbox_to_anchor=(0.99, 1),
    )
    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def live_since(path: Path = LIVE_RECORD_PATH) -> str:
    """Start date of the live ledger (data/live_record.json), or 'not yet' if absent."""
    try:
        return str(json.loads(path.read_text()).get("since") or "not yet")
    except (OSError, ValueError):
        return "not yet"


def causal_note(since: str | None = None) -> str:
    return CAUSAL_NOTE.format(since=since or live_since())


SNB_SIDEBAR = """## Sidebar — what a pegged EUR/CHF looked like

From September 2011 to 15 January 2015 the SNB held EUR/CHF at or above 1.20. A pegged cross has
almost no realised volatility: its 20- and 60-day vol sit near zero, its vol ratio is flat, its
range is narrow. Every input of this radar is a volatility, range or correlation feature, so a
pegged cross reads **calm** — right until the day the peg goes. This project does not carry an
EUR/CHF series at all; the point holds for any vol-based radar looking at a managed rate.

USD/CHF was not pegged, but it inherited the franc's suppressed volatility. **What the radar did
NOT do: warn.** {pre_event} The floor removal was unscheduled — the next SNB policy assessment
was due on 19 March 2015 — so no calendar feature (a `days_to_SNB` count) could have flagged it
either, and a radar that claimed it had would be lying about what was knowable.

What the radar DID do: {event_day} — because the MOVE was unprecedented for the series, not
because it was predicted. This is detection, not forecasting, and it is published here exactly as
the replay computed it. The phase-23 cross-asset context (other currency crosses, rates, equity
volatility) is the response to this blind spot; it widens what the radar can see, it does not make
pegs predictable.

Data note: in the daily bars used here the "close" of 15 January is a start-of-day snapshot (the
data layer documents this), so that bar carries an extreme high–low range but a small close-to-close
return. The range feature is what the siren reacted to on the 15th; the move reached `ret_1d` — the
HMM's main input — on the 16th, which is why the label flipped a day after the siren.
"""


def snb_sidebar(rows: pd.DataFrame, thr: float, event_date: str, precision: float | None) -> str:
    """Report C's honest sidebar with the pre-event numbers filled in from the replay rows."""
    g = rows.sort_values("date")
    ev = pd.Timestamp(event_date)
    pre = g[g["date"] < ev].tail(5)
    risks = ", ".join(
        f"{d:%d %b} {100 * r:.0f} %"
        for d, r in zip(pre["date"], pre["change_risk_5d"].astype(float), strict=True)
    )
    pre_risk = pre["change_risk_5d"].astype(float)
    n_over = int((pre_risk >= thr).sum())
    marginal = n_over > 0 and float(pre_risk.max()) < thr + 0.05  # within 5 points of the line
    prec = (
        f" The gauge's frozen test precision at that threshold is {100 * precision:.0f} %: more than "
        f"half of its alarms are not followed by a change, so a reading a few points over the line "
        f"is a marginal alarm, not a call."
        if marginal and precision is not None and precision < 0.5
        else ""
    )
    labels = sorted(set(pre["regime"].astype(str)))
    label_txt = (
        f"with the regime label {labels[0]} throughout"
        if len(labels) == 1
        else f"with regime labels {', '.join(labels)}"
    )
    pre_event = (
        f"On the five trading days before {ev:%d %B} change risk read {risks} — at or above the "
        f"{100 * thr:.0f} % threshold on {n_over} of them, {label_txt}." + prec
    )
    on = g[g["date"] == ev]
    after = g[g["date"] > ev]
    first_crisis = after[after["regime"] == "crisis"]["date"]
    if len(on):
        siren = float(on["anomaly_pct"].iloc[0])
        label = str(on["regime"].iloc[0])
        event_day = (
            f"the siren scored {ev:%d %B} at percentile {siren:.0f} while the regime label still read "
            f"{label} that evening; the label flipped to crisis on "
            f"{first_crisis.iloc[0]:%d %B}"
            if len(first_crisis)
            else f"the siren scored {ev:%d %B} at percentile {siren:.0f}"
        )
    else:
        event_day = "the siren and the regime label are printed in the table above"
    return SNB_SIDEBAR.format(pre_event=pre_event, event_day=event_day)


def report_markdown(
    key: str,
    window: dict,
    rows: pd.DataFrame,
    thr: float,
    since: str,
    png_name: str,
    all_pairs: pd.DataFrame | None = None,
    precision: float | None = None,
) -> str:
    """reports/storms/<key>.md: banner, selection rule, numbers, png, table, narrative (+SNB sidebar)."""
    story = storyline(rows, thr)
    text = narrative(story, window)
    pair = window["pair"]
    lines = [
        f"# Storm replay — {window['title']} ({pair})\n",
        f"> **{causal_note(since)}**\n>\n> {SELECTION_RULE}\n",
        f"_Window {window['start']} → {window['end']}, {story['n_days']} trading days. For each day t the "
        f"prices were truncated at t and scored with the saved models exactly as the daily pipeline "
        f"does (filtered HMM, forecaster, siren); no refit, no smoothing. Alarm threshold "
        f"{thr:.2f} is the forecaster's frozen validation choice._\n",
        "## The numbers\n",
        f"- First alarm (change risk ≥ {thr:.2f}): **{story['first_alarm'] or 'none in window'}**"
        + (f" at {_pct(story['first_alarm_risk'])}" if story["first_alarm"] else "")
        + "\n"
        f"- First crisis day: **{story['first_crisis'] or 'none in window'}**\n"
        f"- Alarm → regime flip: **{story['alarm_to_flip_days'] if story['alarm_to_flip_days'] is not None else '–'}** trading days\n"
        f"- Peak siren: **{story['peak_siren']}** at percentile **{story['peak_siren_pct']:.0f}** "
        f"({story['n_loud_days']} days ≥ {SIREN_LOUD:.0f})\n"
        f"- Crisis days: **{story['n_crisis_days']}** of {story['n_days']} (longest run {story['longest_crisis_run']}); "
        f"window ended in **{story['regime_end']}**\n",
        f"![{key}]({png_name})\n",
        "## Buildup\n",
        text["buildup"] + "\n",
        "## Alarm timing\n",
        text["alarm"] + "\n",
        "## Aftermath\n",
        text["aftermath"] + "\n",
        "## Day by day\n",
        _md_table(day_table(rows)) + "\n",
    ]
    if all_pairs is not None and all_pairs["pair"].nunique() > 1:
        lines.append("## The other pairs, same days\n")
        for p, g in all_pairs.groupby("pair", sort=True):
            if p == pair:
                continue
            s = storyline(g, thr)
            lines.append(
                f"- **{p}**: first alarm {s['first_alarm'] or 'none'}, first crisis "
                f"{s['first_crisis'] or 'none'}, peak siren {s['peak_siren_pct']:.0f} on {s['peak_siren']}, "
                f"crisis days {s['n_crisis_days']}/{s['n_days']}."
            )
    if key == "snb_2015":
        lines.append(snb_sidebar(rows, thr, window.get("event_date", "2015-01-15"), precision))
    lines.append(
        f"\n_Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from the saved models "
        f"(see data/storm_replays.json). {config.DISCLAIMER}_\n"
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# artifacts: data/storm_replays.json + reports/storms/*
# --------------------------------------------------------------------------------------
def _json_rows(rows: pd.DataFrame) -> list[dict]:
    out = []
    for r in rows.sort_values(["date", "pair"]).to_dict("records"):
        rec = {}
        for k, v in r.items():
            if k == "date":
                rec[k] = pd.Timestamp(v).strftime("%Y-%m-%d")
            elif k == "top_drivers":
                rec[k] = [str(x) for x in v] if isinstance(v, list | np.ndarray) else None
            elif isinstance(v, np.integer | int) and not isinstance(v, bool):
                rec[k] = int(v)
            elif isinstance(v, np.floating | float):
                rec[k] = None if pd.isna(v) else float(v)
            elif v is None or (isinstance(v, float) and pd.isna(v)):
                rec[k] = None
            else:
                rec[k] = None if pd.isna(v) else str(v)
        out.append(rec)
    return out


def rows_from_json(entry: dict) -> pd.DataFrame:
    """Inverse of the json writer: a REPLAY_COLUMNS frame (date as Timestamp) from one window entry."""
    df = pd.DataFrame(entry["rows"])
    if df.empty:
        return pd.DataFrame(columns=REPLAY_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    for c in REPLAY_COLUMNS:
        if c not in df.columns:
            df[c] = None if c in ("consensus_text", "top_drivers") else np.nan
    return df[REPLAY_COLUMNS]


def build_all(
    prices: pd.DataFrame, windows: dict[str, dict] | None = None, progress: bool = True
) -> dict:
    """Replay every window (all pairs) and return the storm_replays.json payload."""
    windows = windows or WINDOWS
    models = load_models()
    thr = threshold(models)
    since = live_since()
    payload: dict = {}
    for key, w in windows.items():
        rows = replay(prices, w["start"], w["end"], models=models, progress=progress)
        told = rows[rows["pair"] == w["pair"]]
        payload[key] = {
            **w,
            "selection_rule": SELECTION_RULE,
            "causal_note": causal_note(since),
            "live_since": since,
            "threshold": thr,
            "test_precision": frozen_precision(models),
            "model_version": _model_version(models),
            "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "storyline": storyline(told, thr) if len(told) else None,
            "rows": _json_rows(rows),
        }
    return payload


def _model_version(models: dict) -> str:
    hmm_v = next(iter(models["hmm"].values())).version
    return f"hmm={hmm_v}|fc={models['fc'][1]['version']}|siren={models['siren']['version']}"


def write_outputs(
    payload: dict,
    prices: pd.DataFrame,
    json_path: Path = REPLAYS_PATH,
    storms_dir: Path = STORMS_DIR,
) -> list[Path]:
    """Write data/storm_replays.json and, per window, reports/storms/<key>.md + .png."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=1))
    written = [json_path]
    storms_dir.mkdir(parents=True, exist_ok=True)
    for key, entry in payload.items():
        rows = rows_from_json(entry)
        told = rows[rows["pair"] == entry["pair"]]
        if told.empty:
            continue
        stem = f"{key}_{entry['pair']}"
        png = render_png(
            told,
            prices,
            storms_dir / f"{stem}.png",
            f"{entry['title']} — {entry['pair']} — causal replay",
            entry["threshold"],
            entry.get("event_date"),
        )
        md = storms_dir / f"{stem}.md"
        md.write_text(
            report_markdown(
                key,
                entry,
                told,
                entry["threshold"],
                entry["live_since"],
                png.name,
                rows,
                precision=entry.get("test_precision"),
            )
        )
        written += [png, md]
    return written


# --------------------------------------------------------------------------------------
# auto post-mortem (daily pipeline stage)
# --------------------------------------------------------------------------------------
def entries_into_crisis(regimes: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    """(date, pair) for every pair whose NEWEST row is crisis and whose previous row was not."""
    out = []
    for pair, g in regimes.sort_values("date").groupby("pair", sort=True):
        if len(g) < 2:
            continue
        last, prev = g.iloc[-1], g.iloc[-2]
        if last["regime"] == "crisis" and prev["regime"] != "crisis":
            out.append((pd.Timestamp(last["date"]), str(pair)))
    return out


def postmortem_markdown(regimes: pd.DataFrame, date: pd.Timestamp, pair: str, thr: float) -> str:
    """DRAFT post-mortem: the last POSTMORTEM_DAYS live rows of `pair`, same template as the storms."""
    g = regimes[(regimes["pair"] == pair) & (regimes["date"] <= date)].sort_values("date")
    g = g.tail(POSTMORTEM_DAYS).copy()
    for c in REPLAY_COLUMNS:
        if c not in g.columns:
            g[c] = None if c in ("consensus_text", "top_drivers") else np.nan
    story = storyline(g, thr)
    text = narrative(story)
    lines = [
        f"# DRAFT — for human review: {pair} entered crisis on {date:%Y-%m-%d}\n",
        f"> Auto-drafted by the daily pipeline from the last {len(g)} live rows of regimes.parquet "
        f"(every row is a causal, filtered score — a replay would show the same numbers). "
        f"Not published until a human has read it. {config.DISCLAIMER}\n",
        "## The numbers\n",
        f"- First alarm (change risk ≥ {thr:.2f}) in the last {len(g)} days: "
        f"**{story['first_alarm'] or 'none'}**\n"
        f"- First crisis day: **{story['first_crisis']}** (alarm → flip: "
        f"{story['alarm_to_flip_days'] if story['alarm_to_flip_days'] is not None else '–'} trading days)\n"
        f"- Peak siren: **{story['peak_siren']}** at percentile **{story['peak_siren_pct']:.0f}**\n",
        "## Buildup\n",
        text["buildup"] + "\n",
        "## Alarm timing\n",
        text["alarm"] + "\n",
        "## Day by day\n",
        _md_table(day_table(g)) + "\n",
        "## For the reviewer\n",
        "- [ ] Is the event behind this entry named correctly? (add one line, no direction words)\n"
        "- [ ] Does the alarm timing read honestly? If the radar did not warn, the report must say so.\n"
        "- [ ] Move to reports/storms/ only after review; the live record stays the ledger.\n",
        f"\n_Drafted {datetime.now(UTC):%Y-%m-%d %H:%M} UTC._\n",
    ]
    return "\n".join(lines)


def stage(ctx: dict) -> None:
    """Daily-pipeline stage: on a live entry into crisis for any pair, register a DRAFT post-mortem
    writer (reports/postmortems/<date>_<pair>.md). Otherwise nothing is written."""
    regimes = ctx["regimes"]
    thr = float(ctx.get("forecaster_meta", {}).get("threshold", 0.22))
    entries = entries_into_crisis(regimes)
    ctx["postmortems"] = []
    if not entries:
        log.info("postmortem: no live entry into crisis today — nothing to draft")
        return
    for date, pair in entries:
        path = POSTMORTEM_DIR / f"{date:%Y-%m-%d}_{pair}.md"
        ctx["postmortems"].append(path)

        def _write(c: dict, path=path, date=date, pair=pair) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(postmortem_markdown(c["regimes"], date, pair, thr))

        ctx.setdefault("extra_writers", {})[f"postmortem {path.name} (DRAFT)"] = _write
        log.info("postmortem: %s entered crisis on %s — drafting %s", pair, date.date(), path.name)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def main() -> None:
    """`python -m fxradar.replay`: replay the three windows from the committed prices, write
    data/storm_replays.json and reports/storms/*.md + .png."""
    parser = argparse.ArgumentParser(description="FX Regime Radar — storm replays")
    parser.add_argument("--window", choices=list(WINDOWS), default=None, help="one window only")
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="re-render reports + pngs from the existing data/storm_replays.json (no replay)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    prices = pd.read_parquet(config.PRICES_PATH)
    if args.render_only:
        payload = json.loads(REPLAYS_PATH.read_text())
        for key, e in payload.items():
            e.update(WINDOWS.get(key, {}))  # refresh the static window text (titles, context)
            e.setdefault("test_precision", frozen_precision())
        REPLAYS_PATH.write_text(json.dumps(payload, indent=1))
    else:
        windows = {args.window: WINDOWS[args.window]} if args.window else WINDOWS
        payload = build_all(prices, windows)
        if args.window and REPLAYS_PATH.exists():  # keep the other windows' entries
            payload = {**json.loads(REPLAYS_PATH.read_text()), **payload}
    written = write_outputs(payload, prices)
    for p in written:
        print("wrote", p.relative_to(config.ROOT))
    for key, e in payload.items():
        s = e["storyline"]
        print(
            f"{key:20s} {e['pair']} first alarm {s['first_alarm']} · first crisis {s['first_crisis']} · "
            f"peak siren {s['peak_siren_pct']:.0f} on {s['peak_siren']} · crisis days "
            f"{s['n_crisis_days']}/{s['n_days']}"
        )


if __name__ == "__main__":
    main()
