"""Tests for the price data layer (phase 01). No network: fixture parquet + monkeypatched I/O."""

import logging
from datetime import date

import numpy as np
import pandas as pd
import pytest

from fxradar import config, data


# --------------------------------------------------------------------------------------
# contract
# --------------------------------------------------------------------------------------
def test_schema_matches_contract(prices_sample: pd.DataFrame) -> None:
    assert list(prices_sample.columns) == config.PRICE_COLUMNS
    assert str(prices_sample["date"].dtype) == "datetime64[ns]"
    assert prices_sample["pair"].dtype == object
    for col in data.OHLC:
        assert prices_sample[col].dtype == np.float64
    assert set(prices_sample["pair"].unique()) == set(config.PAIRS)


def test_dates_strictly_increasing_per_pair(prices_sample: pd.DataFrame) -> None:
    for _, g in prices_sample.groupby("pair"):
        assert g["date"].is_monotonic_increasing
        assert g["date"].is_unique


def test_prices_positive_and_plausible(prices_sample: pd.DataFrame) -> None:
    assert (prices_sample[data.OHLC] > 0).all().all()
    for pair, (lo, hi) in config.PRICE_BOUNDS.items():
        g = prices_sample.loc[prices_sample["pair"] == pair, data.OHLC]
        for col in data.OHLC:
            assert g[col].between(lo, hi).all(), (pair, col)


def test_no_weekend_rows(prices_sample: pd.DataFrame) -> None:
    assert not prices_sample["date"].dt.dayofweek.isin([5, 6]).any()


# --------------------------------------------------------------------------------------
# tidy_prices: completed trading days only, no filling
# --------------------------------------------------------------------------------------
def _fake_yahoo_frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    raw = pd.DataFrame(
        {
            "Adj Close": [1.10, np.nan, 1.12, 1.13],
            "Close": [1.10, np.nan, 1.12, 1.13],
            "High": [1.11, np.nan, 1.13, 1.14],
            "Low": [1.09, np.nan, 1.11, 1.12],
            "Open": [1.10, np.nan, 1.11, 1.12],
            "Volume": [0, 0, 0, 0],
        },
        index=idx,
    )
    raw.index.name = "Date"
    return raw


def test_tidy_prices_drops_missing_days_and_never_fills() -> None:
    tidy = data.tidy_prices(_fake_yahoo_frame(), "EURUSD", as_of=date(2024, 2, 1))
    assert list(tidy.columns) == config.PRICE_COLUMNS
    assert len(tidy) == 3  # the NaN day is gone, not filled
    assert pd.Timestamp("2024-01-02") not in set(tidy["date"])
    assert (tidy["pair"] == "EURUSD").all()
    assert tidy["date"].is_monotonic_increasing


def test_tidy_prices_excludes_in_progress_bar() -> None:
    """The bar dated `as_of` (today) is still being written by the market: never keep it."""
    tidy = data.tidy_prices(_fake_yahoo_frame(), "EURUSD", as_of=date(2024, 1, 4))
    assert tidy["date"].max() == pd.Timestamp("2024-01-03")
    later = data.tidy_prices(_fake_yahoo_frame(), "EURUSD", as_of=date(2024, 1, 5))
    assert later["date"].max() == pd.Timestamp("2024-01-04")


def test_download_prices_fails_loudly_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data, "_fetch_one", lambda _t, _s: _fake_yahoo_frame().iloc[0:0])
    with pytest.raises(RuntimeError):
        data.download_prices(["EURUSD"])


def test_fetch_one_retries_with_backoff_and_no_final_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    import yfinance as yf

    calls: list[int] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        yf, "download", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(OSError("boom"))
    )
    monkeypatch.setattr(data.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(RuntimeError):
        data._fetch_one("EURUSD=X", "2020-01-01")
    assert len(calls) == data.RETRIES
    assert sleeps == [2.0, 4.0]  # backoff between attempts only, no sleep after the last one


# --------------------------------------------------------------------------------------
# corrupted-print filters
# --------------------------------------------------------------------------------------
def _row(df: pd.DataFrame, pair: str, pos: int) -> int:
    return int(df.index[df["pair"] == pair][pos])


def test_bad_tick_filter_catches_displaced_bar(prices_sample: pd.DataFrame) -> None:
    df = prices_sample.copy()
    idx = _row(df, "EURUSD", 100)
    df.loc[idx, data.OHLC] *= 1.06  # whole bar displaced, reverts next day
    flags = data.flag_bad_ticks(df)
    assert flags.sum() == 1 and flags.loc[idx]
    clean, dropped = data.clean_prices(df)
    assert len(clean) == len(df) - 1 and len(dropped) == 1
    assert dropped.iloc[0]["date"] == df.loc[idx, "date"]
    assert dropped.iloc[0]["reason"] == "reverting bad tick"


def test_bad_tick_filter_catches_close_only_print(prices_sample: pd.DataFrame) -> None:
    """USDCHF 2009-02-06 shape: open/high normal, close pinned to a bogus low, reverts next day."""
    df = prices_sample.copy()
    idx = _row(df, "USDCHF", 150)
    df.loc[idx, "close"] = df.loc[idx, "low"] = df.loc[idx, "close"] * 0.93
    flags = data.flag_bad_ticks(df)
    assert flags.sum() == 1 and flags.loc[idx]


def test_bad_tick_filter_catches_small_disjoint_bar(prices_sample: pd.DataFrame) -> None:
    """EURUSD 2008-07-08 shape: whole bar 2.5% away from both neighbours, reverts."""
    df = prices_sample.copy()
    idx = _row(df, "GBPUSD", 120)
    df.loc[idx, data.OHLC] *= 0.975
    flags = data.flag_bad_ticks(df)
    assert flags.sum() == 1 and flags.loc[idx]


def test_bad_tick_filter_keeps_real_shocks(prices_sample: pd.DataFrame) -> None:
    """The SNB floor removal (2015-01-15) is a >10% move that did NOT revert: must survive.

    Yahoo quirk (documented in data.py): the daily "close" is a start-of-day snapshot, so the
    shock shows up in the 2015-01-16 close while the 2015-01-15 bar carries the 0.73 low.
    """
    assert data.flag_bad_ticks(prices_sample).sum() == 0
    assert data.flag_bad_extremes(prices_sample).sum() == 0
    assert data.flag_out_of_bounds(prices_sample).sum() == 0
    usdchf = prices_sample[prices_sample["pair"] == "USDCHF"].set_index("date")
    assert abs(np.log(usdchf.loc["2015-01-16", "close"] / usdchf.loc["2015-01-15", "close"])) > 0.10
    assert usdchf.loc["2015-01-15", "low"] < 0.80


def test_bad_tick_filter_never_flags_last_row(prices_sample: pd.DataFrame) -> None:
    df = prices_sample.copy()
    last = _row(df, "GBPUSD", -1)
    df.loc[last, data.OHLC] *= 1.10  # looks like a spike, but there is no tomorrow yet
    assert not data.flag_bad_ticks(df).loc[last]


def test_bad_tick_filter_is_row_order_invariant(prices_sample: pd.DataFrame) -> None:
    df = prices_sample.copy()
    idx = _row(df, "EURUSD", 100)
    df.loc[idx, data.OHLC] *= 1.06
    shuffled = df.sample(frac=1, random_state=0)
    a = data.flag_bad_ticks(df)
    b = data.flag_bad_ticks(shuffled).sort_index()
    assert a.equals(b) and a.sum() == 1
    with pytest.raises(ValueError):
        data.flag_bad_ticks(pd.concat([df, df.iloc[:5]]))  # duplicate index -> refuse


def test_bad_extremes_catches_reciprocal_low(prices_sample: pd.DataFrame) -> None:
    """GBPUSD 2012-01-27 shape: low = 1/price (0.637 on a 1.57 day); the rest of the bar is fine."""
    df = prices_sample.copy()
    idx = _row(df, "GBPUSD", 60)
    df.loc[idx, "low"] = 1.0 / df.loc[idx, "close"]
    flags = data.flag_bad_extremes(df)
    assert flags.sum() == 1 and flags.loc[idx]
    assert not data.flag_bad_ticks(df).loc[idx]  # not a close problem, so the tick rule stays quiet
    clean, dropped = data.clean_prices(df)
    assert dropped.iloc[0]["reason"] == "absurd high/low" and len(clean) == len(df) - 1


def test_out_of_bounds_is_dropped(prices_sample: pd.DataFrame) -> None:
    df = prices_sample.copy()
    idx = _row(df, "EURUSD", 30)
    df.loc[idx, "high"] = 5.0
    flags = data.flag_out_of_bounds(df)
    assert flags.sum() == 1 and flags.loc[idx]
    _, dropped = data.clean_prices(df)
    assert set(dropped["reason"]) <= {"absurd high/low", "out of bounds"} and len(dropped) == 1


# --------------------------------------------------------------------------------------
# ECB cross-check (network replaced by a fake)
# --------------------------------------------------------------------------------------
def _fake_ecb(offset_pct: float):
    def fetch(base: str, quote: str, start, end) -> pd.Series:
        pair = {"EUR": "EURUSD", "USD": "USDCHF"}[base]
        sample = pd.read_parquet(config.ROOT / "tests" / "fixtures" / "prices_sample.parquet")
        s = sample[sample["pair"] == pair].set_index("date")["close"] * (1 + offset_pct / 100)
        return s.iloc[::2]  # every other day, like a fixing calendar that differs from ours

    return fetch


def test_validate_against_ecb_reports_stats(
    monkeypatch: pytest.MonkeyPatch, prices_sample: pd.DataFrame
) -> None:
    monkeypatch.setattr(data, "fetch_ecb_rates", _fake_ecb(0.1))
    stats = data.validate_against_ecb(prices_sample)
    assert set(stats) == {"EURUSD", "USDCHF"}
    for s in stats.values():
        assert s["n_compared"] > 100
        assert s["mean_abs_pct"] == pytest.approx(0.1 / 1.001, rel=1e-6)
        assert s["max_abs_pct"] >= s["mean_abs_pct"]


def test_validate_against_ecb_warns_and_raises(
    monkeypatch: pytest.MonkeyPatch, prices_sample: pd.DataFrame, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(data, "fetch_ecb_rates", _fake_ecb(1.0))
    with caplog.at_level(logging.WARNING, logger="fxradar.data"):
        data.validate_against_ecb(prices_sample)
    assert any("deviation from ECB" in r.message for r in caplog.records)

    monkeypatch.setattr(data, "fetch_ecb_rates", _fake_ecb(3.0))
    with pytest.raises(ValueError):
        data.validate_against_ecb(prices_sample)


def test_validate_against_ecb_no_overlap_raises(
    monkeypatch: pytest.MonkeyPatch, prices_sample: pd.DataFrame
) -> None:
    monkeypatch.setattr(data, "fetch_ecb_rates", lambda *a, **k: pd.Series(dtype="float64"))
    with pytest.raises(RuntimeError):
        data.validate_against_ecb(prices_sample)


# --------------------------------------------------------------------------------------
# I/O, summary, plot
# --------------------------------------------------------------------------------------
def test_save_and_load_roundtrip(tmp_path, prices_sample: pd.DataFrame) -> None:
    path = tmp_path / "prices.parquet"
    data.save_prices(prices_sample, path)
    back = data.load_prices(path)
    pd.testing.assert_frame_equal(back, prices_sample[config.PRICE_COLUMNS])


def test_summarize_and_plot(tmp_path, prices_sample: pd.DataFrame) -> None:
    summary = data.summarize(prices_sample)
    assert list(summary["pair"]) == sorted(config.PAIRS)
    assert (summary["rows"] == 327).all()
    one_pair = prices_sample[prices_sample["pair"] == "EURUSD"]
    out = tmp_path / "plot.png"
    data.plot_overview(one_pair, out)  # single panel must not break (squeeze=False)
    assert out.exists() and out.stat().st_size > 1000
