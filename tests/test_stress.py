"""Stress-lab tests (phase 16): bootstrap mechanics, breakeven search, params override safety."""

import numpy as np
import pandas as pd
import pytest

from fxradar import backtest as bt
from fxradar import strategies as st
from fxradar import stress


def test_block_bootstrap_preserves_autocorrelation_and_shape() -> None:
    """An AR(1)-like series has lag-1 autocorrelation ~0.8; 20-day blocks keep most of it,
    a day-shuffle would destroy it. Drawdowns are non-positive and one per path."""
    rng = np.random.default_rng(0)
    x = np.zeros(3000)
    for i in range(1, 3000):
        x[i] = 0.8 * x[i - 1] + rng.normal(0, 0.005)
    r = pd.Series(x)
    paths = stress.bootstrap_paths(r, n_paths=300, block=20, horizon=252, seed=1)
    assert paths.shape == (300, 252)
    ac = np.mean([np.corrcoef(p[:-1], p[1:])[0, 1] for p in paths])
    shuffled = np.mean(
        [np.corrcoef(q[:-1], q[1:])[0, 1] for q in [rng.permutation(p) for p in paths]]
    )
    assert ac > 0.6 and abs(shuffled) < 0.15, (ac, shuffled)
    dd = stress.block_bootstrap(r, n_paths=300, block=20, horizon=252, seed=1)
    assert dd.shape == (300,) and (dd <= 0).all()


def test_params_override_restores() -> None:
    before = dict(st.PARAMS)
    with stress.params_override(mom_scale=999.0):
        assert st.PARAMS["mom_scale"] == 999.0
    assert st.PARAMS == before


def test_breakeven_semantics_on_toy_results(prices_sample: pd.DataFrame) -> None:
    """A strategy with positive gross Sharpe on 'test' rows must get a positive breakeven multiplier;
    one with negative gross Sharpe gets 0."""
    prices = prices_sample.copy()
    prices["date"] = prices["date"] + pd.DateOffset(
        years=5
    )  # push the fixture into the test period
    feats = prices[["date", "pair"]].assign(vol_20=0.08)
    up = prices[["date", "pair"]].assign(pos=1.0)
    trend_up = prices.groupby("pair")["close"].transform(lambda s: s.iloc[-1] > s.iloc[0])
    pos_win = up.assign(
        pos=np.where(trend_up, 1.0, -1.0)
    )  # long the pairs that rose, short the ones that fell (hindsight, deliberately)
    win = bt.run_backtest(pos_win, prices, feats)
    lose = bt.run_backtest(pos_win.assign(pos=-pos_win["pos"]), prices, feats)
    _, be = stress.cost_shocks({"WIN": win, "LOSE": lose})
    be = be.set_index("strategy")
    assert be.loc["WIN", "gross_sharpe"] > 0 and be.loc["WIN", "breakeven_cost_mult"] > 0
    assert be.loc["LOSE", "gross_sharpe"] < 0 and be.loc["LOSE", "breakeven_cost_mult"] == 0.0


def test_window_stats() -> None:
    r = pd.Series([0.01, -0.02, 0.005])
    w = stress.window_stats(r)
    assert w["days"] == 3 and w["worst_day"] == -0.02
    assert w["return"] == pytest.approx((1.01 * 0.98 * 1.005) - 1)
    assert w["max_drawdown"] == pytest.approx(-0.02)
