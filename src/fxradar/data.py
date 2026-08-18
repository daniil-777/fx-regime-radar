"""Price data layer: download daily FX prices, validate against ECB, write data/prices.parquet.

Contract (CLAUDE.md): long/tidy format with columns date, pair, open, high, low, close;
one row per trading day per pair; holidays stay MISSING (never forward-filled), so no
downstream feature ever sees a fabricated price.

Known source quirks (Yahoo Finance FX), kept honest rather than "repaired":
* The daily "close" is effectively a start-of-day snapshot (close_t ~ open_t), so a shock
  that happens during day t shows in the close of t+1 while high/low of day t already carry
  it (SNB 2015-01-15: low 0.73, close 1.02; the 01-16 close is 0.85). About 100 rows per pair
  therefore have close outside [low, high]. Returns are simply one day "late" — harmless for
  regime modelling as long as every feature at t uses rows <= t (CLAUDE.md rule 1).
* The bar dated today is IN PROGRESS when the pipeline runs; we only keep completed days
  (date < as_of), so re-running later the same day gives identical output.
* A handful of corrupted prints exist: whole bars displaced ~6% that revert next day
  (EURUSD, several "8th of the month" days in 2008), one close pinned to a bogus low
  (USDCHF 2009-02-06) and reciprocal-quoted lows (EURUSD/GBPUSD 2012-01-27, low ~ 1/price).
  `clean_prices` DROPS such rows (never fills them) and logs every drop with its reason.
* Genuine source holes remain holes (e.g. EURUSD has no bars 2008-08-01..25 except 08-08).
  The CLI prints the largest calendar gap per pair so nobody is surprised later.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from fxradar import config

log = logging.getLogger(__name__)

RETRIES = 3  # total attempts
BACKOFF_SECONDS = 2.0  # waits between attempts: 2s, 4s
OHLC = ["open", "high", "low", "close"]


# --------------------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------------------
def _fetch_one(ticker: str, start: str) -> pd.DataFrame:
    """Download one Yahoo ticker with retries + exponential backoff. Returns wide OHLC."""
    import yfinance as yf  # imported lazily so tests never touch the network

    last_err: Exception | None = None
    for attempt in range(RETRIES):
        try:
            raw = yf.download(
                ticker,
                start=start,
                progress=False,
                auto_adjust=False,
                multi_level_index=False,
                threads=False,
            )
            if raw is not None and not raw.empty:
                return raw
            last_err = RuntimeError(f"empty download for {ticker}")
        except Exception as exc:  # network hiccups, rate limits, ...
            last_err = exc
        if attempt == RETRIES - 1:
            break
        wait = BACKOFF_SECONDS * (2**attempt)
        log.warning(
            "download %s failed (attempt %d/%d): %s — retry in %.0fs",
            ticker,
            attempt + 1,
            RETRIES,
            last_err,
            wait,
        )
        time.sleep(wait)
    raise RuntimeError(f"could not download {ticker} after {RETRIES} attempts") from last_err


def tidy_prices(raw: pd.DataFrame, pair: str, as_of: date | None = None) -> pd.DataFrame:
    """Turn one wide Yahoo frame into the tidy contract rows for `pair`.

    Keeps completed trading days only: rows without a close are dropped (never filled) and
    the in-progress bar dated `as_of` (default: today, UTC) or later is excluded.
    """
    cutoff = pd.Timestamp(as_of or datetime.now(UTC).date())
    df = raw.rename(columns=str.lower)[OHLC].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    df = df.dropna(subset=["close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index < cutoff]
    df = df.reset_index()
    df.insert(1, "pair", pair)
    df[OHLC] = df[OHLC].astype("float64")
    return df[config.PRICE_COLUMNS]


def download_prices(
    pairs: list[str] | None = None, start: str = config.START_DATE, as_of: date | None = None
) -> pd.DataFrame:
    """Download daily prices for `pairs` since `start` in tidy long format (raw, uncleaned).

    Fails loudly if any pair comes back empty (a silently missing pair would poison
    every downstream artifact).
    """
    pairs = list(pairs or config.PAIRS)
    frames = []
    for pair in pairs:
        ticker = config.YF_TICKERS[pair]
        tidy = tidy_prices(_fetch_one(ticker, start), pair, as_of=as_of)
        if tidy.empty:
            raise RuntimeError(f"no rows for {pair} ({ticker}) — refusing to continue")
        frames.append(tidy)
    return pd.concat(frames, ignore_index=True).sort_values(["pair", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# corrupted-print filters (data quality, not modelling)
# --------------------------------------------------------------------------------------
def _per_pair(prices: pd.DataFrame):
    """Yield (index, sorted group) per pair; refuse ambiguous frames."""
    if not prices.index.is_unique:
        raise ValueError("prices must have a unique index")
    for _, g in prices.groupby("pair", sort=False):
        yield g.sort_values("date", kind="stable")


def flag_bad_ticks(
    prices: pd.DataFrame,
    jump: float = config.BAD_TICK_JUMP,
    jump_bar: float = config.BAD_TICK_JUMP_BAR,
    revert: float = config.BAD_TICK_REVERT,
) -> pd.Series:
    """Boolean mask of single-day corrupted prints that REVERT the next day, per pair.

    Core condition — a round trip: the close jumps in and back out with opposite signs while
    the two-day through-move stays below `revert` (the market did not actually go anywhere).
    On top of that, one of two shapes must hold:
      (a) both legs exceed `jump` and the close sits outside BOTH neighbouring bars' ranges
          (EURUSD "8th of the month" 2008 bars; USDCHF 2009-02-06 whose close == bogus low), or
      (b) both legs exceed the smaller `jump_bar` and the WHOLE bar is disjoint from both
          neighbouring bars (EURUSD 2008-07-08).
    Real shocks (SNB 2015-01-15, Brexit 2016-06-24, March 2020) do not revert: never flagged.
    Judging day t needs day t+1, so the newest row can never be flagged — this is cleaning
    at ingest, not a feature (CLAUDE.md rule 1 is about features).
    """
    flags = pd.Series(False, index=prices.index)
    for g in _per_pair(prices):
        c = g["close"]
        r_in = np.log(c / c.shift(1))
        r_out = np.log(c.shift(-1) / c)
        through = np.log(c.shift(-1) / c.shift(1))
        round_trip = (np.sign(r_in) != np.sign(r_out)) & (through.abs() < revert)
        hi_nb = np.maximum(g["high"].shift(1), g["high"].shift(-1))
        lo_nb = np.minimum(g["low"].shift(1), g["low"].shift(-1))
        close_displaced = (c > hi_nb) | (c < lo_nb)
        bar_disjoint = (g["low"] > hi_nb) | (g["high"] < lo_nb)
        shape_a = (r_in.abs() > jump) & (r_out.abs() > jump) & close_displaced
        shape_b = (r_in.abs() > jump_bar) & (r_out.abs() > jump_bar) & bar_disjoint
        bad = round_trip & (shape_a | shape_b)
        flags.loc[g.index] = bad.fillna(False).astype(bool)
    return flags


def flag_bad_extremes(prices: pd.DataFrame, tol: float = config.BAD_EXTREME_TOL) -> pd.Series:
    """Boolean mask of bars whose high or low is absurd (e.g. a reciprocal-quoted low).

    A low (high) is absurd when it is more than `tol` (log) below (above) EVERYTHING the
    market printed around it: yesterday's, today's and tomorrow's close and the neighbouring
    bars' lows (highs). SNB 2015-01-15 (low 0.73) is confirmed by the 01-16 bar and survives.
    """
    flags = pd.Series(False, index=prices.index)
    for g in _per_pair(prices):
        c = g["close"]
        ref_lo = pd.concat(
            [c.shift(1), c, c.shift(-1), g["low"].shift(1), g["low"].shift(-1)], axis=1
        ).min(axis=1)
        ref_hi = pd.concat(
            [c.shift(1), c, c.shift(-1), g["high"].shift(1), g["high"].shift(-1)], axis=1
        ).max(axis=1)
        bad = (np.log(g["low"] / ref_lo) < -tol) | (np.log(g["high"] / ref_hi) > tol)
        flags.loc[g.index] = bad.fillna(False).astype(bool)
    return flags


def flag_out_of_bounds(prices: pd.DataFrame) -> pd.Series:
    """Boolean mask of rows where any OHLC value leaves the pair's plausible range."""
    flags = pd.Series(False, index=prices.index)
    for pair, (lo, hi) in config.PRICE_BOUNDS.items():
        g = prices.loc[prices["pair"] == pair, OHLC]
        flags.loc[g.index] = ((g < lo) | (g > hi)).any(axis=1)
    return flags


def clean_prices(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop corrupted bars (never fill them). Returns (clean, dropped-with-reason); logs each drop."""
    reasons = {
        "reverting bad tick": flag_bad_ticks(prices),
        "absurd high/low": flag_bad_extremes(prices),
        "out of bounds": flag_out_of_bounds(prices),
    }
    reason = pd.Series("", index=prices.index, dtype=object)
    for name, mask in reasons.items():
        reason[mask & (reason == "")] = name
    mask = reason != ""
    dropped = (
        prices.loc[mask, ["date", "pair", "close"]]
        .assign(reason=reason[mask])
        .reset_index(drop=True)
    )
    for row in dropped.itertuples(index=False):
        log.warning(
            "dropped %s %s close=%.4f (%s)", row.pair, row.date.date(), row.close, row.reason
        )
    clean = prices.loc[~mask].reset_index(drop=True)
    return clean, dropped


# --------------------------------------------------------------------------------------
# validation against an independent official source
# --------------------------------------------------------------------------------------
def fetch_ecb_rates(base: str, quote: str, start: date, end: date) -> pd.Series:
    """ECB reference rate for base/quote from frankfurter (free, no key). Indexed by date."""
    url = f"{config.FRANKFURTER_URL}/{start.isoformat()}..{end.isoformat()}"
    resp = requests.get(url, params={"from": base, "to": quote}, timeout=30)
    resp.raise_for_status()
    rates = resp.json().get("rates", {})
    s = pd.Series({pd.Timestamp(d): float(v[quote]) for d, v in rates.items()}, dtype="float64")
    s.index.name = "date"
    return s.sort_index()


def validate_against_ecb(
    prices: pd.DataFrame,
    years: int = config.ECB_LOOKBACK_YEARS,
    warn_pct: float = config.ECB_WARN_MEAN_PCT,
    fail_pct: float = config.ECB_FAIL_MEAN_PCT,
) -> dict[str, dict[str, float]]:
    """Compare our closes with ECB reference rates for EURUSD and USDCHF over the last `years`.

    Reference rates are daily fixings (set ~14:15 CET, published ~16:00 CET) while Yahoo's
    daily close is effectively a start-of-day snapshot (see module docstring), so small
    deviations — about the size of a one-day move — are expected. Returns per pair:
    n_compared, mean_abs_pct, max_abs_pct. Logs a WARNING above `warn_pct` mean deviation;
    raises above `fail_pct`.
    """
    end = pd.Timestamp(prices["date"].max()).date()
    start = end - timedelta(days=365 * years)
    checks = {"EURUSD": ("EUR", "USD"), "USDCHF": ("USD", "CHF")}
    results: dict[str, dict[str, float]] = {}
    for pair, (base, quote) in checks.items():
        ours = prices.loc[prices["pair"] == pair].set_index("date")["close"]
        ecb = fetch_ecb_rates(base, quote, start, end)
        joined = pd.concat([ours.rename("ours"), ecb.rename("ecb")], axis=1, join="inner").dropna()
        if joined.empty:
            raise RuntimeError(f"ECB validation: no overlapping dates for {pair}")
        dev_pct = ((joined["ours"] - joined["ecb"]).abs() / joined["ecb"] * 100.0).astype("float64")
        stats = {
            "n_compared": int(len(joined)),
            "mean_abs_pct": float(dev_pct.mean()),
            "max_abs_pct": float(dev_pct.max()),
        }
        results[pair] = stats
        if stats["mean_abs_pct"] > fail_pct:
            raise ValueError(
                f"{pair}: mean deviation from ECB {stats['mean_abs_pct']:.2f}% > {fail_pct}%"
            )
        if stats["mean_abs_pct"] > warn_pct:
            log.warning(
                "%s: mean deviation from ECB %.2f%% > %.1f%%", pair, stats["mean_abs_pct"], warn_pct
            )
    return results


# --------------------------------------------------------------------------------------
# I/O and reporting
# --------------------------------------------------------------------------------------
def save_prices(df: pd.DataFrame, path: Path = config.PRICES_PATH) -> None:
    """Write the tidy price frame to parquet (contract columns, in contract order)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df[config.PRICE_COLUMNS].to_parquet(path, index=False)


def load_prices(path: Path = config.PRICES_PATH) -> pd.DataFrame:
    """Read data/prices.parquet."""
    return pd.read_parquet(path)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Per pair: rows, date range, largest calendar gap, and closes outside the day's high/low."""
    rows = []
    for pair, g in df.groupby("pair", sort=True):
        g = g.sort_values("date")
        gaps = g["date"].diff().dt.days
        rows.append(
            {
                "pair": pair,
                "rows": int(len(g)),
                "first": g["date"].min().date(),
                "last": g["date"].max().date(),
                "max_gap_days": int(gaps.max()),
                "gaps_gt_5d": int((gaps > 5).sum()),
                "close_outside_hl": int(((g["close"] > g["high"]) | (g["close"] < g["low"])).sum()),
            }
        )
    return pd.DataFrame(rows)


def plot_overview(
    df: pd.DataFrame, path: Path = config.REPORTS_DIR / "prices_overview.png"
) -> None:
    """Quick sanity plot of the close series (one panel per pair)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pairs = sorted(df["pair"].unique())
    fig, axes = plt.subplots(
        len(pairs), 1, figsize=(11, 2.6 * len(pairs)), sharex=True, squeeze=False
    )
    for ax, pair in zip(axes[:, 0], pairs, strict=True):
        g = df[df["pair"] == pair]
        ax.plot(g["date"], g["close"], lw=0.8, color="#60A5FA")
        ax.set_title(pair, loc="left", fontsize=10)
        ax.grid(alpha=0.25)
    fig.suptitle("Daily closes (Yahoo Finance, cleaned)", fontsize=11)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    """CLI: download → clean → validate → save → summary + sanity plot."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    prices, dropped = clean_prices(download_prices())
    stats = validate_against_ecb(prices)
    save_prices(prices)
    plot_overview(prices)
    print("\n== prices summary ==")
    print(summarize(prices).to_string(index=False))
    print(f"\n== corrupted bars dropped: {len(dropped)} ==")
    if len(dropped):
        print(dropped.assign(date=dropped["date"].dt.date).to_string(index=False))
    print(
        f"\n== ECB cross-check (last {config.ECB_LOOKBACK_YEARS} years; fixings vs closes, small deviations expected) =="
    )
    for pair, s in stats.items():
        print(
            f"{pair}: compared {s['n_compared']} days, mean |dev| {s['mean_abs_pct']:.3f}%, max |dev| {s['max_abs_pct']:.3f}%"
        )
    print(
        f"\nwrote {config.PRICES_PATH} ({len(prices)} rows) and {config.REPORTS_DIR / 'prices_overview.png'}"
    )


if __name__ == "__main__":
    main()
