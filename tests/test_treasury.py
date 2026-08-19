"""Treasury mode (phase 25): risk engine, rule table, conversions, lint, artifact sanity. Offline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fxradar import config, treasury

TH = {"high_risk": 0.30, "low_risk": 0.10, "wide": 0.25, "narrow": 0.12, "event_window_days": 5}


# ---- synthetic artifacts ---------------------------------------------------------------------
def _frames(n_days: int = 700, seed: int = 0, crisis_share: float = 0.25):
    """Three pairs of random-walk closes (2015 -> 2017-09) with regimes; returns (prices, regimes)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_days)
    prices, regimes = [], []
    for pair, start in [("EURUSD", 1.1), ("USDCHF", 0.95), ("GBPUSD", 1.5)]:
        close = start * np.exp(np.cumsum(rng.normal(0, 0.005, n_days)))
        prices.append(pd.DataFrame({"date": dates, "pair": pair, "close": close}))
        p = [0.35, 0.25, 0.40 - crisis_share, crisis_share]
        reg = rng.choice(treasury.REGIMES, size=n_days, p=p)
        regimes.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "pair": pair,
                    "regime": reg,
                    "regime_prob": 0.9,
                    "days_in_regime": 3,
                    "change_risk_5d": rng.uniform(0, 0.6, n_days),
                }
            )
        )
    return pd.concat(prices, ignore_index=True), pd.concat(regimes, ignore_index=True)


# ---- rule table: every branch -------------------------------------------------------------------
def test_decide_hedge_branches() -> None:
    light, reason = treasury.decide("crisis", 0.01, None, None, None, None, TH)
    assert light == "hedge" and "Crisis" in reason
    light, reason = treasury.decide("calm", 0.35, 0.10, 0.40, None, None, TH)  # width 0.30 >= wide
    assert light == "hedge" and "80th percentile" in reason
    # high risk but narrow interval, or unknown interval, is NOT a hedge
    assert treasury.decide("calm", 0.35, 0.30, 0.35, None, None, TH)[0] == "ladder"
    assert treasury.decide("trend", 0.35, None, None, None, None, TH)[0] == "ladder"


def test_decide_wait_branches() -> None:
    assert treasury.decide("calm", 0.05, 0.02, 0.08, None, None, TH)[0] == "wait"  # narrow band
    light, reason = treasury.decide("calm", 0.05, None, None, None, None, TH)  # band unknown
    assert light == "wait" and "no interval available" in reason
    light, reason = treasury.decide("calm", 0.05, None, None, None, 9, TH, next_event="FOMC")
    assert light == "wait" and "FOMC" in reason and "9 trading days" in reason
    assert "no scheduled event" in treasury.decide("calm", 0.05, None, None, None, None, TH)[1]
    assert treasury.decide("calm", None, None, None, None, None, TH)[0] == "wait"  # risk missing


def test_decide_ladder_branches_name_the_failed_condition() -> None:
    light, reason = treasury.decide("trend", 0.05, None, None, None, None, TH)
    assert light == "ladder" and "regime is trend" in reason
    light, reason = treasury.decide("calm", 0.20, None, None, None, None, TH)
    assert light == "ladder" and "not below the 40th percentile" in reason
    light, reason = treasury.decide("calm", 0.05, 0.0, 0.20, None, None, TH)  # width 0.20 >= narrow
    assert light == "ladder" and "not narrow" in reason
    light, reason = treasury.decide("calm", 0.05, None, None, None, 3, TH, next_event="ECB")
    assert light == "ladder" and "ECB is 3 trading days away" in reason
    assert (
        treasury.decide("calm", 0.05, None, None, None, 5, TH)[0] == "ladder"
    )  # boundary: 5 is within
    assert treasury.decide("calm", 0.05, None, None, None, 6, TH)[0] == "wait"
    # agreement/consensus are appended as context, never change the light
    light, reason = treasury.decide(
        "chop", 0.05, None, None, 3, None, TH, consensus_text="all agree"
    )
    assert light == "ladder" and "agreement 3/3" in reason and "all agree" in reason


# ---- risk engine --------------------------------------------------------------------------------
def test_var_es_monotone_and_levels() -> None:
    x = np.abs(np.random.default_rng(1).standard_t(4, 5000)) * 0.01
    v95, e95 = treasury.var_es(x, 0.95)
    v99, e99 = treasury.var_es(x, 0.99)
    assert e95 >= v95 and e99 >= v99 and v99 >= v95 and e99 >= e95
    assert np.isnan(treasury.var_es(np.array([]), 0.95)[0])


def test_weekly_moves_label_at_window_start_no_lookahead() -> None:
    prices, regimes = _frames(120)
    one = prices[prices.pair == "EURUSD"].reset_index(drop=True)
    m = treasury.weekly_moves(prices, regimes)
    # the move is |log(close[t+5]/close[t])| and the label is regime[t]
    row = m[(m.pair == "EURUSD")].iloc[10]
    i = one.index[one.date == row.date][0]
    expect = abs(np.log(one.close[i + 5] / one.close[i]))
    assert row.move == pytest.approx(expect) and row.end_date == one.date[i + 5]
    assert (
        row.regime
        == regimes[(regimes.pair == "EURUSD") & (regimes.date == row.date)].regime.iloc[0]
    )
    # altering the regimes of the LAST rows does not change any earlier window's label or move
    altered = regimes.copy()
    last = altered.groupby("pair")["date"].transform("max")
    altered.loc[altered.date >= last - pd.Timedelta(days=10), "regime"] = "crisis"
    m2 = treasury.weekly_moves(prices, altered)
    early = m.date < m.groupby("pair")["date"].transform("max") - pd.Timedelta(days=10)
    pd.testing.assert_frame_equal(m[early].reset_index(drop=True), m2[early].reset_index(drop=True))
    # truncation invariance: the same windows computed on a shorter history are identical
    cut = prices.date.max() - pd.Timedelta(days=60)
    m3 = treasury.weekly_moves(prices[prices.date <= cut], regimes[regimes.date <= cut])
    pd.testing.assert_frame_equal(m3, m[m.end_date <= cut].reset_index(drop=True))


def test_table_train_era_only_and_min_windows_fallback() -> None:
    prices, regimes = _frames(700, crisis_share=0.02)  # ~14 crisis days per pair -> fallback
    m = treasury.weekly_moves(prices, regimes)
    t = treasury.table(m, train_end="2016-12-31")
    for pair, d in t.items():
        n_train = int((m[(m.pair == pair) & (m.end_date <= "2016-12-31")]).shape[0])
        assert d["unconditional"]["n"] == n_train and not d["unconditional"]["fallback"]
        crisis, calm = d["table"]["crisis"], d["table"]["calm"]
        assert crisis["fallback"] and crisis["n"] < treasury.MIN_WINDOWS
        assert crisis["es_99"] == d["unconditional"]["es_99"]  # unconditional numbers, own n
        assert not calm["fallback"] and calm["es_99"] >= calm["var_99"] >= calm["var_95"]
    # no window ending after train_end leaks in
    m_late = m[m.end_date > "2016-12-31"]
    t2 = treasury.table(pd.concat([m, m_late, m_late]), train_end="2016-12-31")
    assert t2 == t


def test_fit_thresholds_from_train_era() -> None:
    _, regimes = _frames(300)
    th = treasury.fit_thresholds(regimes)
    cr = regimes.change_risk_5d
    assert th["high_risk"] == pytest.approx(cr.quantile(0.8)) and th["low_risk"] == pytest.approx(
        cr.quantile(0.4)
    )
    assert th["wide"] == treasury.DEFAULT_WIDE and th["width_source"] == "default"
    regimes["conformal_q"] = 0.05
    th2 = treasury.fit_thresholds(regimes)
    assert th2["wide"] == pytest.approx(0.10) and th2["narrow"] == pytest.approx(0.10)
    th3 = treasury.fit_thresholds(regimes.drop(columns=["change_risk_5d", "conformal_q"]))
    assert th3["high_risk"] == treasury.DEFAULT_HIGH_RISK and th3["risk_source"] == "default"


# ---- conversions --------------------------------------------------------------------------------
def test_conversion_arithmetic() -> None:
    fx = treasury.latest_fx(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-02"] * 3),
                "pair": ["EURUSD"] * 2 + ["USDCHF"] * 2 + ["GBPUSD"] * 2,
                "close": [1.0, 1.10, 1.0, 0.90, 1.0, 1.30],
            }
        )
    )
    assert fx["EURCHF"] == pytest.approx(0.99) and fx["GBPCHF"] == pytest.approx(1.17)
    assert treasury.convert(800_000, "EUR", "CHF", fx) == pytest.approx(792_000)
    assert treasury.convert(100, "CHF", "CHF", fx) == 100
    assert treasury.convert(
        treasury.convert(5, "GBP", "USD", fx), "USD", "GBP", fx
    ) == pytest.approx(5)
    assert treasury.scale_to_horizon(0.02, 4) == pytest.approx(0.04)
    assert treasury.round_sig(21_426.3) == 21_000 and treasury.round_sig(0.0123456, 3) == 0.0123
    # 800k EUR x ES 2.5 % x 1 week -> CHF, 2 significant figures
    assert treasury.money_at_risk(800_000, "EUR", 0.025, 1, "CHF", fx) == 20_000
    line = treasury.cost_of_waiting_line(800_000, "EUR", 0.025, "CHF", fx, "calm")
    assert (
        line
        == "Waiting 1 more week on €800,000 risks ≈ CHF 20,000 at the 99% level (regime: calm)."
    )


# ---- compliance lint ----------------------------------------------------------------------------
def test_templates_have_no_direction_words() -> None:
    for key, text in treasury.TEMPLATES.items():
        assert not treasury.has_direction_words(text), (key, treasury.has_direction_words(text))
    assert treasury.has_direction_words("we think it will rise, so buy") == ["rise", "buy"]
    assert not treasury.has_direction_words("update the upload")  # word boundaries
    assert treasury.TEMPLATES["disclaimer"] == config.DISCLAIMER


# ---- artifact build -----------------------------------------------------------------------------
def test_build_schema_events_and_features_ext(tmp_path) -> None:
    prices, regimes = _frames(700)
    events = pd.DataFrame(
        {
            "date": ["2010-01-01", str((regimes.date.max() + pd.Timedelta(days=3)).date())],
            "type": ["ECB", "FOMC"],
            "source": ["x", "x"],
        }
    )
    out = treasury.build(regimes, prices, events=events, train_end="2016-12-31")
    for k in [
        "generated_at_utc",
        "as_of",
        "levels",
        "horizon_days",
        "train_end",
        "method",
        "thresholds",
        "pairs",
        "fx",
        "disclaimer",
    ]:
        assert k in out
    assert out["disclaimer"] == config.DISCLAIMER and set(out["pairs"]) == {
        "EURUSD",
        "USDCHF",
        "GBPUSD",
    }
    d = out["pairs"]["EURUSD"]
    for k in [
        "current_regime",
        "regime_prob",
        "days_in_regime",
        "table",
        "unconditional",
        "light",
        "light_reason",
        "inputs",
    ]:
        assert k in d
    assert set(d["table"]) == set(treasury.REGIMES)
    assert {"n", "var_95", "es_95", "var_99", "es_99", "fallback"} <= set(d["table"]["calm"])
    assert d["inputs"]["next_event"] == "FOMC" and 1 <= d["inputs"]["days_to_next_event"] <= 3
    assert d["inputs"]["risk_lo"] is None and d["inputs"]["agreement"] is None
    assert d["light"] in {"hedge", "ladder", "wait"}
    # features_ext with a nearer event wins; malformed events.csv is ignored
    ext = pd.DataFrame(
        {"date": [regimes.date.max()], "pair": ["EURUSD"], "days_to_SNB": [1], "days_to_CPI": [-2]}
    )
    out2 = treasury.build(regimes, prices, features_ext=ext, events=events)
    assert out2["pairs"]["EURUSD"]["inputs"]["next_event"] == "SNB"
    assert out2["pairs"]["USDCHF"]["inputs"]["next_event"] == "FOMC"
    assert treasury.read_events(tmp_path / "missing.csv") is None
    # stage + writer round trip
    ctx = {"regimes": regimes, "prices": prices}
    treasury.stage(ctx)
    path = tmp_path / "t.json"
    treasury.write(ctx["treasury"], path)
    assert treasury.load(path)["pairs"].keys() == out["pairs"].keys()


# ---- generated artifact sanity (skipped until the artifact exists) ------------------------------
@pytest.mark.skipif(not treasury.PATH.exists(), reason="treasury_risk.json not built")
def test_generated_artifact_crisis_es_at_least_calm_es() -> None:
    art = treasury.load()
    rows = treasury.sanity_rows(art)
    assert rows and all(r["ok"] for r in rows), rows
    for d in art["pairs"].values():
        c = d["table"][d["current_regime"]]
        assert c["es_99"] >= c["es_95"] >= c["var_95"] and c["es_99"] >= c["var_99"]
    assert art["disclaimer"] == config.DISCLAIMER and "thresholds" in art
    assert not treasury.has_direction_words(
        " ".join(d["light_reason"] for d in art["pairs"].values())
    )


@pytest.mark.skipif(not treasury.PATH.exists(), reason="treasury_risk.json not built")
def test_treasury_page_renders_with_disclaimer() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(config.ROOT / "app/views/treasury.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    txt = " ".join(m.value for m in at.markdown)
    assert config.DISCLAIMER in txt and "Waiting 1 more week on €800,000" in txt
    assert "does no modelling" in txt
