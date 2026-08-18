"""Backtest engine tests (phase 14): toy exactness, THE FORESIGHT TEST, cost monotonicity, contract."""

import numpy as np
import pandas as pd
import pytest

from fxradar import backtest as bt


def _toy(
    n: int = 300, seed: int = 0, pairs=("EURUSD", "GBPUSD", "USDCHF")
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    px, ft = [], []
    for p in pairs:
        close = 1.0 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
        px.append(pd.DataFrame({"date": dates, "pair": p, "close": close}))
        ft.append(
            pd.DataFrame({"date": dates, "pair": p, "vol_20": 0.10})
        )  # flat vol -> cost 1 + 80*0.1 = 9 bp
    return pd.concat(px, ignore_index=True), pd.concat(ft, ignore_index=True)


def test_constant_long_equals_asset_return_minus_one_entry_cost() -> None:
    prices, feats = _toy()
    pos = prices[["date", "pair"]].assign(pos=1.0)
    res = bt.run_backtest(pos, prices, feats, bt.CostConfig(base_bps=1.0, vol_mult=80.0))
    for pair, g in res.daily.groupby("pair"):
        asset = prices[prices["pair"] == pair]["close"].pct_change().fillna(0.0).to_numpy()
        # lag law: day 0 earns nothing (no position yet); from day 1 on, +1 x asset return
        np.testing.assert_allclose(g["ret_gross"].to_numpy()[1:], asset[1:], atol=1e-15)
        assert g["ret_gross"].iloc[0] == 0.0
        assert g["turnover"].sum() == pytest.approx(1.0)  # exactly one entry
        assert g["cost"].sum() == pytest.approx(9.0 / 1e4)  # exactly one entry cost of 9 bp
        np.testing.assert_allclose(g["ret_net"].sum(), g["ret_gross"].sum() - 9.0 / 1e4, atol=1e-15)


def test_daily_sign_flip_cost_bleed_to_the_cent() -> None:
    prices, feats = _toy(n=100, pairs=("EURUSD",))
    n = len(prices)
    pos = prices[["date", "pair"]].assign(pos=np.where(np.arange(n) % 2 == 0, 1.0, -1.0))
    res = bt.run_backtest(pos, prices, feats, bt.CostConfig(base_bps=1.0, vol_mult=80.0))
    d = res.daily
    # held positions: 0 on day 0, then +1,-1,+1,...  -> turnover 1 on day 1, then 2 every day
    assert d["turnover"].iloc[0] == 0.0 and d["turnover"].iloc[1] == 1.0
    assert (d["turnover"].iloc[2:] == 2.0).all()
    expected_cost = (1.0 + 2.0 * (n - 2)) * 9.0 / 1e4
    assert d["cost"].sum() == pytest.approx(expected_cost, abs=1e-12)


def test_foresight_signal_is_neutralised_by_the_lag_law() -> None:
    """THE FORESIGHT TEST. The classic backtest sin: build a position from day t's close and let it
    earn day t's own return (pos_t = sign(ret_t) — 'perfect foresight' by one day). With the lag
    disabled that shows an enormous Sharpe; with the lag enforced the same series earns t+1 and is
    noise. This proves the engine cannot be fooled by contemporaneous lookahead."""
    prices, feats = _toy(n=1500, seed=3)
    r_same_day = prices.groupby("pair")["close"].pct_change()
    pos = prices[["date", "pair"]].assign(pos=np.sign(r_same_day.fillna(0.0)))
    zero_cost = bt.CostConfig(base_bps=0.0, vol_mult=0.0)
    cheat = bt.run_backtest(pos, prices, feats, zero_cost, _disable_lag_for_tests=True)
    honest = bt.run_backtest(pos, prices, feats, zero_cost)
    s_cheat = cheat.metrics.query("scope == 'ALL' and kind == 'net'")["sharpe"].iloc[0]
    s_honest = honest.metrics.query("scope == 'ALL' and kind == 'net'")["sharpe"].iloc[0]
    assert s_cheat > 10.0, s_cheat  # |ret| every day: impossible in reality
    assert abs(s_honest) < 1.0, s_honest  # lagged one day, the same signal is noise


def test_cost_monotonicity() -> None:
    prices, feats = _toy(n=400, seed=5)
    rng = np.random.default_rng(1)
    pos = prices[["date", "pair"]].assign(pos=rng.uniform(-1, 1, len(prices)))
    prev = None
    for vm in [0.0, 20.0, 80.0, 200.0]:
        res = bt.run_backtest(pos, prices, feats, bt.CostConfig(base_bps=1.0, vol_mult=vm))
        net = res.metrics.query("scope == 'ALL' and kind == 'net'")["cagr"].iloc[0]
        if prev is not None:
            assert net <= prev + 1e-12
        prev = net


def test_positions_are_clipped_and_metrics_gross_and_net() -> None:
    prices, feats = _toy(n=120)
    pos = prices[["date", "pair"]].assign(pos=3.0)  # illegal leverage requested
    res = bt.run_backtest(pos, prices, feats)
    assert res.daily["pos_held"].abs().max() <= 1.0
    assert set(res.metrics["kind"]) == {"gross", "net"} and "ALL" in set(res.metrics["scope"])
    tbl = bt.metrics_table(res)
    assert list(tbl.columns) == ["gross", "net"]
    frame = bt.to_backtests_frame(res, "toy")
    assert list(frame.columns) == [
        "date",
        "strategy",
        "pair",
        "pos",
        "ret_gross",
        "ret_net",
        "cost_bps",
    ]


def test_cost_scales_with_volatility() -> None:
    cfg = bt.CostConfig(base_bps=1.0, vol_mult=80.0)
    c = cfg.cost_bps(pd.Series([0.05, 0.15]))
    assert c.iloc[0] == pytest.approx(5.0) and c.iloc[1] == pytest.approx(13.0)
    assert bt.max_drawdown(pd.Series([0.1, -0.5, 0.2])) == pytest.approx(-0.5)
    assert bt.cagr(pd.Series([0.0] * 252)) == pytest.approx(0.0)
