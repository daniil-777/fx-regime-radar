"""Strategy-layer tests (phase 15): overlay behaviour, vol targeting, blend weights, causality."""

import numpy as np
import pandas as pd
import pytest

from fxradar import backtest as bt
from fxradar import config
from fxradar import strategies as st


def _toy_inputs(n: int = 800, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2014-01-01", periods=n)
    rows = []
    for p in config.PAIRS:
        ret = rng.normal(0, 0.006, n)
        close = np.exp(np.cumsum(ret))
        d = pd.DataFrame({"date": dates, "pair": p, "close": close, "ret_1d": ret})
        d["vol_20"] = pd.Series(ret).rolling(20).std().fillna(0.006) * np.sqrt(252)
        d["mom_20"] = pd.Series(close).pct_change(20).fillna(0.0)
        d["regime"] = rng.choice(["calm", "trend", "chop", "crisis"], n, p=[0.5, 0.2, 0.25, 0.05])
        d["change_risk_5d"] = rng.uniform(0, 0.6, n)
        d["anomaly_pct"] = rng.uniform(0, 100, n)
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


def test_overlay_forces_flat_on_siren_days_and_scales_by_risk() -> None:
    df = _toy_inputs()
    pos = pd.Series(1.0, index=df.index)
    out = st.risk_and_siren(pos, df)
    siren = df["anomaly_pct"] > st.PARAMS["siren_stop"]
    assert siren.sum() > 0 and (out[siren] == 0.0).all()
    risky = (df["change_risk_5d"] > st.PARAMS["risk_threshold"]) & ~siren
    np.testing.assert_allclose(out[risky], 1.0 - df.loc[risky, "change_risk_5d"])
    quiet = (df["change_risk_5d"] <= st.PARAMS["risk_threshold"]) & ~siren
    assert (out[quiet] == 1.0).all()
    final = st.overlay(pos, df)
    assert (final[siren] == 0.0).all() and final.abs().max() <= st.PARAMS["leverage_cap"] + 1e-12


def test_strategies_stay_in_unit_range_and_are_causal() -> None:
    df = _toy_inputs()
    for name, fn in st.STRATEGY_FUNCS.items():
        p = fn(df)
        assert p.abs().max() <= 1.0 + 1e-12, name
        cut = df[df.groupby("pair").cumcount(ascending=False) >= 30]
        p_cut = fn(cut)
        pd.testing.assert_series_equal(p.loc[cut.index], p_cut, check_names=False)


def test_regime_gate_semantics() -> None:
    df = _toy_inputs()
    s1, s2, s3 = st.s1_trend(df), st.s2_meanrev(df), st.s3_regime_gate(df)
    r = df["regime"]
    assert (s3[r == "crisis"] == 0.0).all()
    np.testing.assert_allclose(s3[r == "trend"], s1[r == "trend"])
    np.testing.assert_allclose(s3[r == "chop"], s2[r == "chop"])
    np.testing.assert_allclose(s3[r == "calm"], st.PARAMS["calm_size"] * s1[r == "calm"])


_have = config.REGIMES_PATH.exists() and config.FEATURES_PATH.exists()


@pytest.mark.skipif(not _have, reason="artifacts not built")
def test_vol_targeting_hits_ten_percent_on_train_unless_the_cap_binds() -> None:
    """Each overlaid strategy targets 10 % annualised vol per pair on the training period. With
    small-average signals the 2x leverage cap binds on most days (measured 46-81 %), so realised vol
    may sit BELOW target — never above. The rule: within +/-2 % of target, or capped-and-below."""
    df = st.load_inputs()
    train = df["date"] <= pd.Timestamp(config.TRAIN_END)
    for name, fn in st.STRATEGY_FUNCS.items():
        base = st.risk_and_siren(fn(df), df)
        pos = st.vol_target(base, df)
        for pair, g in df.groupby("pair"):
            p, b = pos.loc[g.index], base.loc[g.index]
            r = (p.shift(1) * g["close"].pct_change())[train.loc[g.index]]
            vol = float(r.std(ddof=1) * np.sqrt(252))
            cap_share = float(
                (p / b.replace(0.0, np.nan))
                .abs()
                .ge(st.PARAMS["leverage_cap"] - 1e-9)[train.loc[g.index]]
                .mean()
            )
            on_target = abs(vol - st.PARAMS["target_vol"]) <= 0.02
            capped_below = cap_share > 0.4 and vol <= st.PARAMS["target_vol"] + 0.02
            assert on_target or capped_below, (name, pair, vol, cap_share)
            assert vol <= st.PARAMS["target_vol"] + 0.02  # never runs hotter than target


def test_blend_weights_are_monthly_inverse_vol_and_causal() -> None:
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2020-01-01", periods=400)
    rets = pd.DataFrame(
        {
            "S1_trend": rng.normal(0, 0.01, 400),
            "S2_meanrev": rng.normal(0, 0.02, 400),
            "S3_regime_gate": rng.normal(0, 0.005, 400),
        },
        index=idx,
    )
    w = st.blend_weights(rets)
    np.testing.assert_allclose(w.sum(axis=1), 1.0)
    late = w.iloc[-1]
    assert late["S3_regime_gate"] > late["S1_trend"] > late["S2_meanrev"]  # inverse vol ordering
    # constant within a month, and unaffected by returns AFTER the month started
    months = w.index.to_period("M")
    for m in months.unique()[-3:]:
        block = w[months == m]
        assert (block.nunique() == 1).all()
    w_cut = st.blend_weights(rets.iloc[:-15])
    pd.testing.assert_frame_equal(w.iloc[:-15], w_cut)


def test_leverage_never_above_cap_in_saved_backtests() -> None:
    if not st.STRATEGY_PATH.exists():
        pytest.skip("backtests not built")
    b = pd.read_parquet(st.STRATEGY_PATH)
    assert b["pos"].abs().max() <= st.PARAMS["leverage_cap"] + 1e-9
    assert set(b["strategy"]) >= set(st.ALL_NAMES)
    assert bt.BACKTESTS_PATH == st.STRATEGY_PATH
