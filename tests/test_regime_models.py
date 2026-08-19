"""Phase 32: the model registry. Alternatives obey the same contract, causality and naming as the
champion; the default path is byte-identical delegation; fx is hard-locked to the champion."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fxradar import config
from fxradar import forecaster_models as fm
from fxradar import hmm_model as hm
from fxradar import regime_models as rm


def _synthetic(n=1200, seed=0) -> pd.DataFrame:
    """Two planted volatility eras inside train + a quiet tail: enough structure to name states."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2012-01-02", periods=n)
    vol = np.where((np.arange(n) // 150) % 2 == 0, 0.004, 0.02)
    ret = rng.normal(0, vol)
    px = 1.2 * np.exp(np.cumsum(ret))
    df = pd.DataFrame({"date": dates, "pair": "SYNUSD", "ret_1d": ret})
    df["vol_20"] = pd.Series(ret).rolling(20).std().to_numpy() * np.sqrt(252)
    df["mom_20"] = pd.Series(np.log(px)).diff(20).to_numpy()
    return df.dropna().reset_index(drop=True)


def test_jump_contract_columns_and_probabilities() -> None:
    df = _synthetic()
    b = rm.fit_jump(df, train_end="2015-12-31", lam=1.0)
    sc = rm.score_pair(b, df)
    assert list(sc.columns) == [
        *hm.REGIME_COLUMNS[:6],
        *hm.PROB_COLUMNS,
        "vol_trend",
        "model_version",
    ]
    p = sc[hm.PROB_COLUMNS].to_numpy()
    assert np.allclose(p.sum(axis=1), 1) and (p >= 0).all()
    assert sc["model_version"].iloc[0].startswith("jump=")
    assert set(sc["regime"].unique()) <= {"calm", "trend", "chop", "crisis"}


def test_jump_greedy_inference_is_truncation_invariant_bit_for_bit() -> None:
    df = _synthetic()
    b = rm.fit_jump(df, train_end="2015-12-31", lam=1.0)
    full = rm.score_pair(b, df)
    for cut in (300, 700, len(df) - 5):
        part = rm.score_pair(b, df.iloc[:cut])
        assert full.iloc[:cut].reset_index(drop=True).equals(part.reset_index(drop=True))


def test_jump_names_low_vol_state_calm_and_is_deterministic() -> None:
    df = _synthetic()
    a = rm.fit_jump(df, train_end="2015-12-31", lam=1.0)
    b = rm.fit_jump(df, train_end="2015-12-31", lam=1.0)
    assert np.allclose(a.centers, b.centers) and a.mapping == b.mapping
    sc = rm.score_pair(a, df)
    tr = sc[sc["date"] <= "2015-12-31"].merge(df[["date", "vol_20"]], on="date")
    vols = tr.groupby("regime")["vol_20"].mean()
    assert vols.idxmin() == "calm"


def test_jump_is_more_persistent_than_gmm_on_the_same_data() -> None:
    """The point of the jump penalty: fewer switches than a temporally-uncoupled mixture."""
    df = _synthetic()
    jb = rm.fit_jump(df, train_end="2015-12-31", lam=2.0)
    gb = rm.fit_gmm(df, train_end="2015-12-31")
    js = rm.score_pair(jb, df)["regime"]
    gs = rm.score_pair(gb, df)["regime"]
    assert (js.values[1:] != js.values[:-1]).sum() < (gs.values[1:] != gs.values[:-1]).sum()


def test_registry_hmm_delegates_byte_identically() -> None:
    feats = pd.read_parquet(config.FEATURES_PATH)
    g = feats[feats["pair"] == "EURUSD"].tail(400)
    b = hm.load_bundles()["EURUSD"]
    assert rm.score_pair(b, g).equals(
        hm.score_pair(b, g.sort_values("date").reset_index(drop=True))
    )


def test_fx_universe_is_locked_to_the_champion(monkeypatch) -> None:
    monkeypatch.setattr(config, "REGIME_MODEL", "jump")
    monkeypatch.setattr(config, "UNIVERSE_NAME", "fx")
    with pytest.raises(RuntimeError, match="locked to the champion"):
        rm.selected_model()
    monkeypatch.setattr(config, "UNIVERSE_NAME", "g10")
    assert rm.selected_model() == "jump"
    monkeypatch.setattr(config, "REGIME_MODEL", "nope")
    with pytest.raises(KeyError):
        rm.selected_model()


def test_forecaster_engines_follow_the_protocol() -> None:
    """histgb + logistic fit, calibrate on val, threshold at target recall; xgb delegates."""
    rng = np.random.default_rng(3)
    n = 3000
    dates = pd.bdate_range("2010-01-04", periods=n)
    x = pd.DataFrame(rng.normal(size=(n, len(fm.fc.FEATURES))), columns=fm.fc.FEATURES)
    y = (x.iloc[:, 0] + rng.normal(0, 1.2, n) > 1.0).astype(float)
    df = x.assign(date=dates, pair="SYNUSD", regime="calm", y=y)
    df["split"] = np.where(
        df["date"] <= "2016-12-31", "train", np.where(df["date"] <= "2018-12-31", "val", "test")
    )
    for name in ("histgb", "logistic"):
        r = fm.evaluate(name, df)
        assert 0 < r["threshold"] < 1
        assert r["val"]["recall"] >= fm.fc.TARGET_RECALL - 1e-9  # the threshold rule held on val
        assert (
            0 <= r["test"]["brier"] <= 1 and r["test"]["pr_auc"] > df["y"].mean()
        )  # beats base rate
    with pytest.raises(KeyError):
        fm.fit_estimator("nope", x, y, x, y)
