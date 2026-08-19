"""Scheduled macro-event calendar -> countdown features (phase 23).

`data/events.csv` (date, type, source) holds SCHEDULED decision / release dates only:
FOMC (scheduled meetings, decision = last meeting day), ECB monetary-policy meetings, SNB
quarterly assessments, BoE MPC decisions, NFP (Employment Situation) and CPI releases, built
from the official published calendars (the source column names each one).

Why these features are leakage-safe (CLAUDE.md rule 1): central banks and statistical agencies
publish their schedules a year or more ahead, so "days until the next FOMC decision" is known at
every day t — it uses the calendar, never the outcome. What is NOT known in advance is anything
unscheduled: the 2020-03-15 emergency FOMC cut, the 2008-10-08 coordinated cuts, the
2015-01-15 SNB floor removal. Those are deliberately absent, so `days_to_SNB` was ~9 weeks on
2015-01-15 — the honest limit of a calendar feature. Realised values / surprises are out of
scope (they would need point-in-time consensus data).

Counts are CALENDAR days (not trading days): unambiguous across pairs and holidays, and what a
reader means by "the Fed decides in 3 days".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import config

EVENTS_PATH: Path = config.DATA_DIR / "events.csv"
EVENT_TYPES: list[str] = ["FOMC", "ECB", "SNB", "BOE", "NFP", "CPI"]
CALENDAR_FEATURES: list[str] = [f"days_to_{t}" for t in EVENT_TYPES] + [
    f"days_since_{t}" for t in EVENT_TYPES
]


def load_events(path: Path = EVENTS_PATH) -> pd.DataFrame:
    """Read events.csv -> (date, type, source), sorted, types upper-cased, duplicates dropped."""
    ev = pd.read_csv(path)
    ev["date"] = pd.to_datetime(ev["date"])
    ev["type"] = ev["type"].str.upper().str.strip()
    ev = ev.drop_duplicates(["date", "type"]).sort_values(["type", "date"]).reset_index(drop=True)
    return ev


def days_to_next(dates: pd.Series, event_dates: pd.Series) -> pd.Series:
    """Calendar days from each date to the next scheduled event on or after it (0 on the event
    day); NaN once the known schedule runs out (never a guess)."""
    d = pd.to_datetime(dates).to_numpy(dtype="datetime64[ns]")
    ev = np.sort(pd.to_datetime(event_dates).to_numpy(dtype="datetime64[ns]"))
    idx = np.searchsorted(ev, d, side="left")  # first event >= date
    out = np.full(len(d), np.nan)
    ok = idx < len(ev)
    out[ok] = (ev[idx[ok]] - d[ok]) / np.timedelta64(1, "D")
    return pd.Series(out, index=dates.index, dtype="float64")


def days_since_last(dates: pd.Series, event_dates: pd.Series) -> pd.Series:
    """Calendar days since the last event on or before each date (0 on the event day); NaN before
    the first known event."""
    d = pd.to_datetime(dates).to_numpy(dtype="datetime64[ns]")
    ev = np.sort(pd.to_datetime(event_dates).to_numpy(dtype="datetime64[ns]"))
    idx = np.searchsorted(ev, d, side="right") - 1  # last event <= date
    out = np.full(len(d), np.nan)
    ok = idx >= 0
    out[ok] = (d[ok] - ev[idx[ok]]) / np.timedelta64(1, "D")
    return pd.Series(out, index=dates.index, dtype="float64")


def calendar_features(dates: pd.Series, events: pd.DataFrame) -> pd.DataFrame:
    """days_to_<TYPE> / days_since_<TYPE> for every row of `dates` (index preserved).

    Every value at date t is a function of the published schedule and t only — the same on a
    truncated history (the truncation-invariance test asserts it).
    """
    out = pd.DataFrame(index=dates.index)
    for t in EVENT_TYPES:
        ev = events.loc[events["type"] == t, "date"]
        out[f"days_to_{t}"] = days_to_next(dates, ev)
        out[f"days_since_{t}"] = days_since_last(dates, ev)
    return out[CALENDAR_FEATURES]


def event_markers(events: pd.DataFrame, start: pd.Timestamp | str) -> dict[str, list[str]]:
    """{type: [ISO dates]} from `start` onward (small; the app draws these on the timeline)."""
    start = pd.Timestamp(start)
    return {
        t: [
            d.strftime("%Y-%m-%d")
            for d in events.loc[(events["type"] == t) & (events["date"] >= start), "date"]
        ]
        for t in EVENT_TYPES
    }
