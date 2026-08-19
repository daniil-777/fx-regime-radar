"""Point-in-time daily features from the lexicon scores (phase 29, part B -> data/cb_features.parquet).

For each bank B in {fomc, ecb, snb, boe} and each trading date t:
    cb_B_tone           lexicon tone of the latest statement KNOWN by the close of t
    cb_B_uncert         its LM uncertainty rate
    cb_B_tone_surprise  tone minus the mean tone of that bank's previous K=4 statements (causal:
                        only statements published before this one enter the mean)
    cb_B_days_since     calendar days from that statement's publication date to t
All four are NaN before the bank's first stored statement and forward-filled afterwards.

"Known by the close of t" — the publication-time rule. The FX day ends at 17:00 New York.
A statement is attributed to the trading day of its New-York-local publication date if it was
published BEFORE 17:00 New York; at or after 17:00 it belongs to the next calendar day, and a
weekend/holiday publication rolls to the next trading date in the price calendar. With the fixed
release times (ECB 14:15 CET, SNB 09:30 CET, BoE 12:00 London, FOMC 14:00 ET) every scheduled
statement is same-day. This is the only place the rule lives; `effective_date` implements it.

The whole transform is causal by construction, so computing it on a truncated history must
reproduce the overlapping rows bit-for-bit (tested).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from fxradar import config
from fxradar.cb_lexicon import score_docs
from fxradar.cb_text import BANKS, load_docs

log = logging.getLogger(__name__)

K_SURPRISE = 4  # statements in the rolling mean
FX_CLOSE_ZONE = "America/New_York"
FX_CLOSE_HOUR = 17
CB_FEATURES_PATH = config.DATA_DIR / "cb_features.parquet"
SUFFIXES = ("tone", "uncert", "tone_surprise", "days_since")
COLUMNS = ["date"] + [f"cb_{b.lower()}_{s}" for b in BANKS for s in SUFFIXES]


def effective_date(published_at: str | datetime) -> pd.Timestamp:
    """The first calendar date whose FX close (17:00 New York) comes AFTER publication."""
    ts = (
        published_at if isinstance(published_at, datetime) else datetime.fromisoformat(published_at)
    )
    if ts.tzinfo is None:
        raise ValueError("published_at must be timezone-aware")
    ny = ts.astimezone(ZoneInfo(FX_CLOSE_ZONE))
    day = pd.Timestamp(ny.date())
    if (ny.hour, ny.minute, ny.second) >= (FX_CLOSE_HOUR, 0, 0):
        day += pd.Timedelta(days=1)
    return day


def add_surprise(scores: pd.DataFrame, k: int = K_SURPRISE) -> pd.DataFrame:
    """Per bank: tone_surprise = tone - mean(tone of the previous k statements); NaN for the first."""
    out = scores.sort_values(["bank", "published_at"]).copy()
    prev_mean = (
        out.groupby("bank")["tone"]
        .transform(lambda s: s.shift(1).rolling(k, min_periods=1).mean())
        .astype(float)
    )
    out["tone_surprise"] = out["tone"] - prev_mean
    out["effective_date"] = [effective_date(p) for p in out["published_at"]]
    return out


def build_cb_features(scores: pd.DataFrame, dates: Iterable, k: int = K_SURPRISE) -> pd.DataFrame:
    """Daily point-in-time frame (one row per date in `dates`, contract: COLUMNS)."""
    days = pd.DatetimeIndex(sorted(set(pd.to_datetime(list(dates)).normalize())))
    base = pd.DataFrame({"date": days})
    if scores.empty:
        for c in COLUMNS[1:]:
            base[c] = np.nan
        return base
    s = add_surprise(scores, k)
    for bank in BANKS:
        p = bank.lower()
        b = s[s["bank"] == bank].sort_values(["effective_date", "published_at"])
        b = b.drop_duplicates("effective_date", keep="last")
        right = pd.DataFrame(
            {
                "effective_date": b["effective_date"].values,
                f"cb_{p}_tone": b["tone"].astype(float).values,
                f"cb_{p}_uncert": b["uncertainty"].astype(float).values,
                f"cb_{p}_tone_surprise": b["tone_surprise"].astype(float).values,
                f"cb_{p}_pub_date": b["date"].values,
            }
        )
        merged = pd.merge_asof(
            base[["date"]], right, left_on="date", right_on="effective_date", direction="backward"
        )
        days_since = (merged["date"] - merged[f"cb_{p}_pub_date"]).dt.days.astype(float)
        merged[f"cb_{p}_days_since"] = days_since
        for col in (
            f"cb_{p}_tone",
            f"cb_{p}_uncert",
            f"cb_{p}_tone_surprise",
            f"cb_{p}_days_since",
        ):
            base[col] = merged[col].values
    return base[COLUMNS]


def build_from_docs(docs: list[dict], dates: Iterable, k: int = K_SURPRISE) -> pd.DataFrame:
    return build_cb_features(score_docs(docs), dates, k)


# --------------------------------------------------------------------------------------
# pipeline stage + standalone main
# --------------------------------------------------------------------------------------
def stage(ctx: dict) -> None:
    """Pipeline stage: lexicon-score data/cb/, build the daily frame, register the writer.

    Reads ctx["features"] for the trading calendar; touches nothing else in ctx. If no statements
    are stored the artifact is still written (all-NaN columns) so downstream merges never break.
    """
    docs = load_docs()
    dates = ctx["features"]["date"].unique()
    frame = build_from_docs(docs, dates)
    ctx["cb_features"] = frame
    ctx.setdefault("extra_writers", {})["cb_features"] = lambda c: write_cb_features(
        c["cb_features"]
    )
    log.info("cb_features: %d docs -> %d rows x %d cols", len(docs), len(frame), frame.shape[1])


def write_cb_features(frame: pd.DataFrame, path: Path = CB_FEATURES_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    features = pd.read_parquet(config.FEATURES_PATH, columns=["date"])
    ctx = {"features": features}
    stage(ctx)
    ctx["extra_writers"]["cb_features"](ctx)
    frame = ctx["cb_features"]
    last = frame.dropna(how="all", subset=COLUMNS[1:]).tail(1).T
    print(last.to_string())
    print(f"wrote {CB_FEATURES_PATH} ({len(frame)} rows)")


if __name__ == "__main__":
    main()
