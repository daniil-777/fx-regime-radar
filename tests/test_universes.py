"""Universe registry tests: FX defaults are unchanged; crypto is a complete, consistent record."""

from fxradar import config, universes


def test_fx_universe_matches_shipped_defaults() -> None:
    fx = universes.get("fx")
    assert fx.pairs == ["EURUSD", "USDCHF", "GBPUSD"] and fx.tickers["USDCHF"] == "CHF=X"
    assert (fx.train_end, fx.val_start, fx.val_end, fx.test_start) == (
        "2016-12-31",
        "2017-01-01",
        "2018-12-31",
        "2019-01-01",
    )
    assert fx.trading_days == 252 and fx.pair_dummies == ["pair_GBPUSD", "pair_USDCHF"]
    assert (fx.bad_tick_jump, fx.bad_tick_jump_bar, fx.bad_tick_revert, fx.bad_extreme_tol) == (
        0.04,
        0.02,
        0.02,
        0.20,
    )
    assert (fx.cost_base_bps, fx.cost_vol_mult) == (1.0, 80.0) and fx.subdir == ""
    assert config.universe_dirs("fx")["data"] == config.ROOT / "data"


def test_crypto_universe_is_consistent() -> None:
    c = universes.get("crypto")
    assert set(c.tickers) == set(c.pairs) == set(c.price_bounds)
    assert (
        all(d.removeprefix("pair_") in c.pairs for d in c.pair_dummies)
        and len(c.pair_dummies) == len(c.pairs) - 1
    )
    assert c.trading_days == 365 and c.ecb_checks == {} and c.bad_tick_jump > 0.2
    assert c.train_end < c.val_start <= c.val_end < c.test_start
    assert config.universe_dirs("crypto")["data"] == config.ROOT / "data" / "crypto"
    assert c.display("BTC-USD") == "BTC/USD" and universes.get("fx").display("EURUSD") == "EUR/USD"
    for pair in c.known_events:
        assert pair in c.pairs
