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


def test_g10_universe_is_consistent_and_free_floating() -> None:
    g = universes.get("g10")
    assert len(g.pairs) == 10 and set(g.tickers) == set(g.pairs) == set(g.price_bounds)
    assert len(g.pair_dummies) == 9 and all(
        d.removeprefix("pair_") in g.pairs for d in g.pair_dummies
    )
    # same splits / day-count / cleaning / costs as the frozen fx universe (fx itself untouched)
    fx = universes.get("fx")
    for attr in (
        "train_end",
        "val_start",
        "val_end",
        "test_start",
        "trading_days",
        "bad_tick_jump",
        "cost_base_bps",
        "cost_vol_mult",
    ):
        assert getattr(g, attr) == getattr(fx, attr)
    assert set(fx.pairs) <= set(g.pairs)  # the three frozen pairs are inside the ten
    # no managed / pegged currencies: a vol-regime model is blind to them by construction
    for banned in ("CNY", "CNH", "HKD", "SGD", "INR", "EURCHF"):
        assert not any(banned in p for p in g.pairs)
    assert g.usd_base_pairs == frozenset({"USDJPY", "USDCAD", "USDCHF", "USDSEK"})
    for pair in g.known_events:
        assert pair in g.pairs
    assert g.display("USDSEK") == "USD/SEK"


def test_crypto_universe_five_majors_with_enough_training_history() -> None:
    c = universes.get("crypto")
    assert c.pairs == ["BTC-USD", "ETH-USD", "XRP-USD", "BNB-USD", "ADA-USD"]
    assert c.start_date == "2017-11-09" and c.train_end == "2020-12-31"
    assert "SOL-USD" not in c.pairs  # listed 2020-04: too little pre-split history (documented)
