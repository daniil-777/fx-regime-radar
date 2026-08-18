"""Tests for the validation helpers (phase 04): financial calcs, causality of the naive rule."""

import numpy as np
import pandas as pd
import pytest

from fxradar import validate as v


def test_max_drawdown() -> None:
    r = pd.Series(
        np.log([1.0, 1.1, 0.99, 1.2]) - np.log([0.9, 1.0, 1.1, 0.99])
    )  # equity 1.0->1.1->0.99->1.2 (from 0.9)
    equity = np.exp(r.cumsum())
    expected = (equity / equity.cummax() - 1).min()
    assert v.max_drawdown(r) == pytest.approx(expected)
    assert v.max_drawdown(pd.Series([0.01, 0.02])) == 0.0
    assert np.isnan(v.max_drawdown(pd.Series([], dtype=float)))


def test_sharpe() -> None:
    r = pd.Series([0.01, -0.005, 0.02, 0.0, 0.003])
    assert v.sharpe(r) == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(252))
    assert np.isnan(v.sharpe(pd.Series([0.0, 0.0, 0.0])))


def test_run_lengths() -> None:
    runs = v.run_lengths(pd.Series(["a", "a", "b", "c", "c", "c"]))
    assert runs["label"].tolist() == ["a", "b", "c"]
    assert runs["length"].tolist() == [2, 1, 3]
    assert runs["start"].tolist() == [0, 2, 3] and runs["end"].tolist() == [1, 2, 5]


def test_naive_stress_is_causal() -> None:
    rng = np.random.default_rng(0)
    vol = pd.Series(np.abs(rng.normal(0.08, 0.02, 400)))
    full = v.naive_stress(vol)
    part = v.naive_stress(vol.iloc[:300])
    pd.testing.assert_series_equal(full.iloc[:300], part)
    assert full.dtype == bool and not full.iloc[:59].any()  # min_periods=60 -> no flags before


def test_episode_starts_and_lead_lag() -> None:
    dates = pd.Series(pd.bdate_range("2020-01-01", periods=30))
    hmm = pd.Series([False] * 5 + [True] * 5 + [False] * 20)
    naive = pd.Series([False] * 8 + [True] * 4 + [False] * 18)
    assert v.episode_starts(hmm).tolist() == [5] and v.episode_starts(naive).tolist() == [8]
    ex = v.lead_lag_examples(dates, hmm, naive)
    assert len(ex) == 1 and ex.iloc[0]["lead_days"] == 3  # HMM flagged 3 rows earlier


def test_ma_trend_returns_uses_lagged_position() -> None:
    n = 300
    close = pd.Series(np.linspace(1.0, 2.0, n))  # steady uptrend -> MA50 > MA200 -> long
    ret = np.log(close / close.shift(1))
    strat = v.ma_trend_returns(close, ret)
    assert strat.iloc[:200].isna().all()  # MA200 warm-up (+1 lag)
    pd.testing.assert_series_equal(
        strat.iloc[201:], ret.iloc[201:], check_names=False
    )  # long x ret
    # causality: position at t is decided from closes <= t-1 for the return at t
    strat_cut = v.ma_trend_returns(close.iloc[:250], ret.iloc[:250])
    pd.testing.assert_series_equal(strat.iloc[:250], strat_cut, check_names=False)


def test_regime_anatomy_and_economic_check_shapes() -> None:
    rng = np.random.default_rng(1)
    n = 600
    dates = pd.bdate_range("2015-01-01", periods=n)
    rows = []
    for pair in ["EURUSD", "GBPUSD", "USDCHF"]:
        ret = rng.normal(0, 0.005, n)
        rows.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "pair": pair,
                    "ret_1d": ret,
                    "vol_20": np.abs(rng.normal(0.08, 0.02, n)),
                    "close": np.exp(np.cumsum(ret)),
                    "regime": rng.choice(["calm", "trend", "chop", "crisis"], n),
                    "regime_prob": 0.9,
                }
            )
        )
    df = pd.concat(rows, ignore_index=True)
    df["period"] = np.where(df["date"] < pd.Timestamp("2016-06-01"), "train", "oos")
    an = v.regime_anatomy(df)
    assert (
        len(an) == 3 * 2 * 4
        and an.groupby(["pair", "period"])["freq_pct"].sum().round(6).eq(100).all()
    )
    econ = v.economic_check(df)
    assert set(econ["regime"]) == {"calm", "trend", "chop", "crisis", "ALL"}
    agree, ex = v.baseline_comparison(df)
    assert (
        set(agree["pair"]) == {"EURUSD", "GBPUSD", "USDCHF"}
        and agree["agreement_pct"].between(0, 100).all()
    )
