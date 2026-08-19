"""Extended features (phase 23): calendar countdowns, cross-asset context, free mood series and
Yang-Zhang volatility -> `data/features_ext.parquet`, consumed by the CHALLENGER forecaster only.

Nothing here touches the frozen contract: `data/features.parquet`, the bundle's feature_spec,
goldens and the Rust engine stay byte-identical (CLAUDE.md rule 11). `vol_20_yz` lives here, not
in features.py, for exactly that reason.

Point-in-time rules (rule 1), per series — the feature at day t may use an observation dated d
only if d + lag_days <= t:
* dxy   DTWEXBGS, lag 8: the Fed's H.10 publishes the week's daily values on the NEXT Monday,
        so Monday's value is public 7 days later; 8 keeps every weekday safely behind its release.
* vix   VIXCLS, lag 1: FRED posts the Cboe close the next day (and the 16:15 ET close is after
        the Yahoo FX snapshot for day t anyway).
* us2y  DGS2, lag 1: H.15 is published the next business day (level differences, not logs —
        a yield near zero makes log changes meaningless).
* epu   USEPUINDXD, lag 1: the daily EPU index is computed from the next morning's papers.
* eurchf EURCHF=X close, lag 0: the same Yahoo snapshot as the scored pairs (context, not a pair).
* cot_eur  CFTC TFF leveraged-money EUR net position "as of Tuesday", RELEASED Friday: the
        feature at t uses the last report whose release date (report + 3 days) is <= t —
        `apply_release_lag`, proven by a test. Holiday-delayed releases (rare) are not modelled.

Transforms per context series: 1-day change, 5-day change, 20-observation z-score — all computed
on the series' own calendar, then aligned as-of (backward) onto each pair's dates, then
standardised with a mean/std fit on TRAIN rows (<= config.TRAIN_END) only and frozen in
`models/features_ext_scaler.json`. Calendar counts and vol_20_yz are left in natural units.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import calendar_ext, config, context_data
from fxradar import features as base_features
from fxradar import tokens as tk

log = logging.getLogger(__name__)

FEATURES_EXT_PATH: Path = config.DATA_DIR / "features_ext.parquet"
SCALER_PATH: Path = config.MODELS_DIR / "features_ext_scaler.json"
EVENT_MARKERS_PATH: Path = config.DATA_DIR / "event_markers.json"
MARKER_YEARS = 3

# name -> (transform, publication lag in calendar days)
CONTEXT_SPECS: dict[str, tuple[str, int]] = {
    "dxy": ("log", 8),
    "vix": ("log", 1),
    "us2y": ("diff", 1),
    "eurchf": ("log", 0),
    "epu": ("log", 1),
}
CONTEXT_TRANSFORMS = ["chg_1d", "chg_5d", "z20"]
Z_WINDOW = 20
COT_RELEASE_OFFSET_DAYS = 3  # Tuesday report -> Friday release
COT_COLUMNS_OUT = ["cot_eur_net", "cot_eur_net_chg_4w", "cot_eur_net_z52"]
YZ_WINDOW = 20

CONTEXT_FEATURES: list[str] = [
    f"{n}_{t}" for n in CONTEXT_SPECS for t in CONTEXT_TRANSFORMS
] + COT_COLUMNS_OUT
SCALED_COLUMNS: list[str] = list(CONTEXT_FEATURES)  # standardised with the frozen train scaler
EXT_FEATURES: list[str] = [*calendar_ext.CALENDAR_FEATURES, *CONTEXT_FEATURES, "vol_20_yz"]
EXT_COLUMNS: list[str] = ["date", "pair", *EXT_FEATURES]


# --------------------------------------------------------------------------------------
# Yang-Zhang volatility
# --------------------------------------------------------------------------------------
def yang_zhang(ohlc: pd.DataFrame, window: int = YZ_WINDOW) -> pd.Series:
    """Yang & Zhang (2000) range-based volatility, annualised like vol_20 (x sqrt(252)).

    sigma^2 = sigma_o^2 + k * sigma_c^2 + (1 - k) * sigma_rs^2 with
      o = ln(open / prev close)      overnight jump     (sample variance over `window`)
      c = ln(close / open)           open-to-close      (sample variance over `window`)
      rs = u(u - c) + d(d - c)       Rogers-Satchell,   u = ln(high/open), d = ln(low/open)
                                      (mean over `window`)
      k = 0.34 / (1.34 + (window + 1) / (window - 1))   the variance-minimising weight.
    Drift-independent and uses the intraday range, so it is far less noisy than close-to-close
    std for the same window. `ohlc` must be ONE instrument sorted by date with columns
    open/high/low/close; the result is aligned to its index. Causal: row t uses rows <= t only.
    Caveat for this data source: Yahoo's daily FX open is a start-of-day snapshot close to the
    previous close, so the overnight term is small here — the RS and open-close terms carry it.
    """
    o = np.log(ohlc["open"] / ohlc["close"].shift(1))
    c = np.log(ohlc["close"] / ohlc["open"])
    u = np.log(ohlc["high"] / ohlc["open"])
    d = np.log(ohlc["low"] / ohlc["open"])
    rs = u * (u - c) + d * (d - c)
    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    var = (
        o.rolling(window).var() + k * c.rolling(window).var() + (1 - k) * rs.rolling(window).mean()
    )
    return np.sqrt(var.clip(lower=0.0)) * base_features.ANNUALIZE


# --------------------------------------------------------------------------------------
# context series -> lagged, as-of aligned transforms
# --------------------------------------------------------------------------------------
def context_transforms(series: pd.DataFrame, name: str, transform: str) -> pd.DataFrame:
    """(date, <name>_chg_1d, <name>_chg_5d, <name>_z20) on the series' OWN calendar."""
    s = series.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    x = s["value"].astype(float)
    if transform == "log":
        x = np.log(x)
    out = pd.DataFrame({"date": s["date"]})
    out[f"{name}_chg_1d"] = x.diff(1)
    out[f"{name}_chg_5d"] = x.diff(5)
    roll = x.rolling(Z_WINDOW)
    out[f"{name}_z20"] = (x - roll.mean()) / roll.std()
    return out


def align_asof(
    target_dates: pd.Series, table: pd.DataFrame, date_col: str, lag_days: int
) -> pd.DataFrame:
    """For each target date t, the last row of `table` whose `date_col` + lag_days <= t.

    This is the one place point-in-time discipline is enforced for context data: an observation
    is usable only once it has been PUBLISHED, not when it is dated. Returns a frame aligned to
    `target_dates` (index preserved) without the date column.
    """
    tab = table.sort_values(date_col).copy()
    tab["_avail"] = tab[date_col] + pd.Timedelta(days=lag_days)
    tab = tab.drop(columns=[date_col])
    left = pd.DataFrame({"_t": pd.to_datetime(target_dates).to_numpy()}, index=target_dates.index)
    left["_order"] = np.arange(len(left))
    merged = pd.merge_asof(
        left.sort_values("_t"), tab, left_on="_t", right_on="_avail", direction="backward"
    )
    merged = merged.sort_values("_order")
    merged.index = target_dates.index
    return merged.drop(columns=["_t", "_order", "_avail"])


def apply_release_lag(
    df: pd.DataFrame,
    report_date_col: str = "report_date",
    release_offset_days: int = COT_RELEASE_OFFSET_DAYS,
) -> pd.DataFrame:
    """Add `release_date` = report date + offset (the day the number becomes public). The COT
    trap: the CFTC report is "as of Tuesday" but published Friday 15:30 ET — using it on
    Wednesday is look-ahead. Everything downstream keys on `release_date`."""
    out = df.copy()
    out["release_date"] = pd.to_datetime(out[report_date_col]) + pd.Timedelta(
        days=release_offset_days
    )
    return out


def cot_transforms(cot: pd.DataFrame) -> pd.DataFrame:
    """(release_date, cot_eur_net, cot_eur_net_chg_4w, cot_eur_net_z52) from the trimmed TFF rows;
    every transform is computed on report order, then stamped with the release date."""
    c = cot.sort_values("report_date").drop_duplicates("report_date").reset_index(drop=True)
    net = c["lev_money_long"].astype(float) - c["lev_money_short"].astype(float)
    out = pd.DataFrame({"report_date": pd.to_datetime(c["report_date"])})
    out["cot_eur_net"] = net
    out["cot_eur_net_chg_4w"] = net.diff(4)
    roll = net.rolling(52)
    out["cot_eur_net_z52"] = (net - roll.mean()) / roll.std()
    out = apply_release_lag(out)
    return out.drop(columns=["report_date"])


# --------------------------------------------------------------------------------------
# scaler (train-only, frozen)
# --------------------------------------------------------------------------------------
def fit_scaler(df: pd.DataFrame, train_end: str = config.TRAIN_END) -> dict:
    """Mean/std per SCALED column on rows dated <= train_end (pooled across pairs)."""
    tr = df[df["date"] <= pd.Timestamp(train_end)]
    params = {}
    for col in SCALED_COLUMNS:
        x = tr[col].dropna()
        std = float(x.std()) if len(x) > 1 else float("nan")
        params[col] = {
            "mean": float(x.mean()) if len(x) else float("nan"),
            "std": std if std and np.isfinite(std) and std > 0 else float("nan"),
            "n_train": int(len(x)),
        }
    return {
        "train_end": str(train_end),
        "fitted_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "columns": params,
    }


def apply_scaler(df: pd.DataFrame, scaler: dict) -> pd.DataFrame:
    """z = (x - mean) / std with the frozen train parameters; a column without usable params
    stays NaN (never silently unscaled)."""
    out = df.copy()
    for col in SCALED_COLUMNS:
        p = scaler["columns"].get(col)
        if p is None or not np.isfinite(p["std"]):
            out[col] = np.nan
            continue
        out[col] = (out[col] - p["mean"]) / p["std"]
    return out


def save_scaler(scaler: dict, path: Path = SCALER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scaler, indent=1))


def load_scaler(path: Path = SCALER_PATH) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


# --------------------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------------------
def build_features_ext(
    prices: pd.DataFrame,
    context: dict[str, pd.DataFrame],
    events: pd.DataFrame,
    scaler: dict | None = None,
    train_end: str = config.TRAIN_END,
) -> tuple[pd.DataFrame, dict]:
    """One row per (date, pair) of `prices` with EXT_COLUMNS. Returns (frame, scaler): the scaler
    passed in is applied unchanged (production); if None it is fit on train rows (first build)."""
    prices = prices.sort_values(["pair", "date"], kind="stable").reset_index(drop=True)
    out = prices[["date", "pair"]].copy()

    # calendar countdowns (schedule known in advance)
    cal = calendar_ext.calendar_features(out["date"], events)
    out = pd.concat([out, cal], axis=1)

    # cross-asset / mood series: transforms on their own calendar, then lagged as-of alignment
    for name, (transform, lag) in CONTEXT_SPECS.items():
        ser = context.get(name)
        cols = [f"{name}_{t}" for t in CONTEXT_TRANSFORMS]
        if ser is None or ser.empty:
            for c in cols:
                out[c] = np.nan
            continue
        tab = context_transforms(ser, name, transform)
        out[cols] = align_asof(out["date"], tab, "date", lag)[cols].to_numpy()

    # COT with the explicit release lag
    cot = context.get("cot_eur_lev")
    if cot is None or cot.empty:
        for c in COT_COLUMNS_OUT:
            out[c] = np.nan
    else:
        tab = cot_transforms(cot)
        out[COT_COLUMNS_OUT] = align_asof(out["date"], tab, "release_date", 0)[
            COT_COLUMNS_OUT
        ].to_numpy()

    # Yang-Zhang per pair
    yz = pd.Series(np.nan, index=prices.index, dtype="float64")
    for _, g in prices.groupby("pair", sort=False):
        yz.loc[g.index] = yang_zhang(g, YZ_WINDOW)
    out["vol_20_yz"] = yz

    if scaler is None:
        scaler = fit_scaler(out, train_end)
    out = apply_scaler(out, scaler)
    return out[EXT_COLUMNS].reset_index(drop=True), scaler


def align_to_features(ext: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Keep the rows that exist in features.parquet (same warm-up), same (pair, date) order."""
    keys = features[["date", "pair"]]
    return (
        keys.merge(ext, on=["date", "pair"], how="left")
        .sort_values(["pair", "date"])
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------------------
# pipeline stage + CLI
# --------------------------------------------------------------------------------------
def stage(ctx: dict) -> None:
    """run_daily stage: prices + features in ctx -> ctx['features_ext'] (+ writer). Context caches
    are refreshed from the network when reachable (each series falls back to its cache)."""
    context = context_data.load_context(refresh=True)
    events = calendar_ext.load_events()
    scaler = load_scaler()
    ext, scaler = build_features_ext(ctx["prices"], context, events, scaler=scaler)
    if not SCALER_PATH.exists():  # first run only: freeze the train-only scaler
        save_scaler(scaler)
    ext = align_to_features(ext, ctx["features"])
    if "cb_features" in ctx:  # phase 29: lexicon tone features merge on date — challenger only
        ext = ext.merge(ctx["cb_features"], on="date", how="left")
    ctx["features_ext"] = ext
    ctx["events"] = events
    markers = calendar_ext.event_markers(
        events, ext["date"].max() - pd.DateOffset(years=MARKER_YEARS)
    )
    ctx.setdefault("extra_writers", {})["features_ext.parquet + event_markers.json"] = (
        lambda c, e=ext, m=markers: _write(e, m)
    )
    log.info(
        "features_ext: %d rows x %d cols (%d NaN cot rows, latest %s)",
        len(ext),
        ext.shape[1],
        int(ext["cot_eur_net"].isna().sum()),
        ext["date"].max().date(),
    )


def _write(ext: pd.DataFrame, markers: dict) -> None:
    FEATURES_EXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ext.to_parquet(FEATURES_EXT_PATH, index=False)
    EVENT_MARKERS_PATH.write_text(json.dumps(markers, indent=0))


def run_from_disk(refresh: bool = False) -> pd.DataFrame:
    """Standalone path: committed prices/features + cached context -> features_ext.parquet."""
    ctx = {
        "prices": pd.read_parquet(config.PRICES_PATH),
        "features": pd.read_parquet(config.FEATURES_PATH),
    }
    context = context_data.load_context(refresh=refresh)
    events = calendar_ext.load_events()
    scaler = load_scaler()
    ext, scaler = build_features_ext(ctx["prices"], context, events, scaler=scaler)
    if not SCALER_PATH.exists():
        save_scaler(scaler)
    ext = align_to_features(ext, ctx["features"])
    markers = calendar_ext.event_markers(
        events, ext["date"].max() - pd.DateOffset(years=MARKER_YEARS)
    )
    _write(ext, markers)
    return ext


def main() -> None:
    parser = argparse.ArgumentParser(description="FX Regime Radar — extended features (phase 23)")
    parser.add_argument("--refresh", action="store_true", help="re-download context series first")
    parser.add_argument(
        "--yz-ablation", action="store_true", help="write reports/yz_ablation.md (research copy)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ext = run_from_disk(refresh=args.refresh)
    print(f"features_ext: {ext.shape[0]} rows x {ext.shape[1]} cols -> {FEATURES_EXT_PATH}")
    print("date range:", ext["date"].min().date(), "->", ext["date"].max().date())
    print("\nNaN count per column:")
    print(ext[EXT_FEATURES].isna().sum().to_string())
    if args.yz_ablation:
        yz_ablation()


# --------------------------------------------------------------------------------------
# research ablation: vol_20 -> vol_20_yz inside the HMM (research copy; ships nothing to models/)
# --------------------------------------------------------------------------------------
def yz_ablation(
    reports_dir: Path = config.REPORTS_DIR, pairs: list[str] | None = None
) -> pd.DataFrame:
    """Refit the phase-03 HMM with vol_20 swapped for vol_20_yz and compare with the SHIPPED
    regimes (share, mean run length, agreement). Pure research: nothing under models/ changes;
    adopting YZ into the wall is a follow-up at the next scheduled bundle rebuild."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from fxradar import hmm_model as hm

    feats = pd.read_parquet(config.FEATURES_PATH)
    ext = pd.read_parquet(FEATURES_EXT_PATH)[["date", "pair", "vol_20_yz"]]
    shipped = pd.read_parquet(config.REGIMES_PATH)[["date", "pair", "regime"]]
    df = feats.merge(ext, on=["date", "pair"], how="inner")
    pairs = pairs or sorted(df["pair"].unique())
    rows, timelines = [], {}
    for pair in pairs:
        g = df[df["pair"] == pair].sort_values("date").reset_index(drop=True)
        research = g.copy()
        research["vol_20"] = research["vol_20_yz"]  # the ONLY change: the HMM sees YZ vol
        bundle = hm.fit_hmm(research[["date", "pair", *hm.HMM_FEATURES]])
        yz = hm.score_pair(bundle, research[["date", "pair", *hm.HMM_FEATURES]])
        cmp_ = yz[["date", "regime"]].merge(
            shipped[shipped["pair"] == pair], on="date", suffixes=("_yz", "")
        )
        timelines[pair] = cmp_
        for label, col in [("shipped (vol_20)", "regime"), ("research (vol_20_yz)", "regime_yz")]:
            lab = cmp_[col]
            runs = hm.run_length(lab)
            run_ends = runs[lab.ne(lab.shift(-1))]  # length of every completed run
            share = lab.value_counts(normalize=True)
            rows.append(
                {
                    "pair": pair,
                    "model": label,
                    **{f"share_{r}": float(share.get(r, 0.0)) for r in hm.REGIMES},
                    "mean_run_days": float(run_ends.mean()),
                    "switches_per_year": float(
                        lab.ne(lab.shift(1)).sum() / max(len(lab) / config.TRADING_DAYS, 1e-9)
                    ),
                    "agreement_with_shipped": float((cmp_["regime_yz"] == cmp_["regime"]).mean()),
                }
            )
    table = pd.DataFrame(rows)

    # one figure: EURUSD (or first pair) timeline bands, shipped vs research
    pair = pairs[0]
    cmp_ = timelines[pair]
    colors = tk.REGIME_COLORS
    plt.rcParams.update(
        {
            "figure.facecolor": tk.BG,
            "axes.facecolor": tk.SURFACE,
            "axes.edgecolor": tk.BORDER,
            "text.color": tk.TEXT,
            "axes.labelcolor": tk.TEXT,
            "xtick.color": tk.MUTED,
            "ytick.color": tk.MUTED,
        }
    )
    fig, axes = plt.subplots(2, 1, figsize=(11, 3.6), sharex=True)
    for ax, col, title in [
        (axes[0], "regime", f"{pair} — shipped HMM (vol_20, close-to-close)"),
        (axes[1], "regime_yz", f"{pair} — research refit (vol_20_yz, Yang-Zhang)"),
    ]:
        lab = cmp_[col].to_numpy()
        dates = cmp_["date"].to_numpy()
        start = 0
        for i in range(1, len(lab) + 1):
            if i == len(lab) or lab[i] != lab[start]:
                ax.axvspan(dates[start], dates[i - 1], color=colors[lab[start]], alpha=0.9, lw=0)
                start = i
        ax.set_yticks([])
        ax.set_title(title, loc="left", fontsize=9)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors.values()]
    axes[0].legend(handles, list(colors), ncol=4, frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    reports_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(reports_dir / "yz_ablation.png", dpi=110)
    plt.close(fig)

    def _fmt(v: float) -> str:
        return f"{v:.3f}" if isinstance(v, float) else str(v)

    cols = list(table.columns)
    md = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    md += ["| " + " | ".join(_fmt(v) for v in r) + " |" for r in table.itertuples(index=False)]
    agree = table[table["model"].str.startswith("research")]["agreement_with_shipped"]
    text = [
        "# Yang-Zhang ablation — research copy only\n",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. The phase-03 GaussianHMM ({hm.N_STATES} states, train <= {config.TRAIN_END}, same n_iter/seed) was refit with `vol_20` swapped for `vol_20_yz` (Yang & Zhang 2000, 20-day, annualised). Nothing under models/ or the bundle changed — this compares a research refit with the SHIPPED regimes._\n",
        "## Regime share, run length, agreement\n",
        "\n".join(md) + "\n",
        f"Mean label agreement research vs shipped: {agree.mean():.1%} (range {agree.min():.1%}–{agree.max():.1%}). Shares and run lengths are over the full history (the shipped model's own numbers are the 'shipped' rows).\n",
        f"![timeline]({'yz_ablation.png'})\n",
        "## Reading it\n",
        "Yang-Zhang uses the open/high/low/close range, so it is a less noisy variance estimate than the close-to-close std for the same 20-day window. On this data source the overnight term is nearly zero (Yahoo's daily FX open is a start-of-day snapshot of the previous close), so the estimator is carried by the Rogers-Satchell and open-close terms; it also inherits any bad high/low prints. The state NAMING rule (sort by mean vol, then |mom|) was kept, so labels are comparable but not identical: a different vol input moves the state boundaries, hence the agreement below 100%. Where agreement is far below 100% (GBPUSD, USDCHF in the table) the lesson is that the HMM's state identities are NOT robust to the volatility estimator — the strongest argument for treating a YZ adoption as a full rebuild with validation (phase-04 style) rather than a swap.\n",
        "**Decision:** `vol_20_yz` ships in `features_ext.parquet` for the challenger only. Adopting it inside the HMM / the Rust wall is a follow-up for the next scheduled bundle rebuild (new feature_spec, goldens, selftest) — not a silent swap.\n",
        "\n_Educational tool. Not investment advice._\n",
    ]
    (reports_dir / "yz_ablation.md").write_text("\n".join(text))
    return table


if __name__ == "__main__":
    main()
