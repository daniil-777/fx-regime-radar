"""Phase 21: BOCPD is online (exact truncation invariance), catches planted breaks, is
deterministic; the consensus sums three causal votes and never uses direction words."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from fxradar import bocpd

DIRECTION = re.compile(
    r"\b(rise|fall|up|down|buy|sell|long|short|target|bullish|bearish|rally|drop)\b", re.I
)


def _series(seed=0):
    rng = np.random.default_rng(seed)
    return np.concatenate(
        [rng.normal(0, 0.005, 300), rng.normal(0, 0.02, 100), rng.normal(0.004, 0.005, 120)]
    )


def test_truncation_invariance_bit_for_bit() -> None:
    x = _series()
    rl_full, p_full = bocpd.bocpd(x)
    for cut in (50, 317, 450):
        rl_cut, p_cut = bocpd.bocpd(x[:cut])
        assert np.array_equal(rl_cut, rl_full[:cut])
        assert np.array_equal(p_cut, p_full[:cut])  # bit-for-bit, not "close"


def test_planted_vol_break_and_mean_break_flagged_within_days() -> None:
    x = _series()
    rl, p = bocpd.bocpd(x)
    # variance quadruples at 300: the run length must reset within 3 days and p_change spike
    assert rl[300:303].min() <= 3 and p[300:303].max() > 0.8
    # mean shifts by 0.8 sd at 400: reset within ~15 days
    assert rl[400:416].min() <= 12
    # and in quiet stretches the run length keeps growing
    assert rl[250] > 100


def test_deterministic() -> None:
    x = _series(3)
    a, b = bocpd.bocpd(x), bocpd.bocpd(x)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_nan_returns_carry_no_evidence() -> None:
    x = _series()
    x[100] = np.nan
    rl, p = bocpd.bocpd(x)
    assert np.isfinite(p).all() and rl[100] == rl[99]


def _frames(n=400, seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n)
    ret = np.concatenate([rng.normal(0, 0.005, n - 60), rng.normal(0, 0.03, 60)])
    feats = pd.DataFrame({"date": dates, "pair": "EURUSD", "ret_1d": ret})
    feats["vol_20"] = pd.Series(ret).rolling(20).std().to_numpy() * np.sqrt(252)
    regimes = pd.DataFrame({"date": dates, "pair": "EURUSD", "regime": "calm"})
    regimes["p_crisis"] = np.where(np.arange(n) >= n - 40, 0.9, 0.01)
    return feats, regimes


def test_consensus_votes_and_templates() -> None:
    feats, regimes = _frames()
    params = bocpd.fit_params(feats, regimes.assign(p_crisis=0.0), train_end="2016-12-31")
    out = bocpd.score_all(regimes, feats, params)
    assert set(bocpd.BOCPD_COLUMNS + bocpd.VOTE_COLUMNS) <= set(out.columns)
    assert out["agreement"].between(0, 3).all()
    assert (out["agreement"] == out[["vote_hmm", "vote_bocpd", "vote_vol"]].sum(axis=1)).all()
    assert out["agreement"].iloc[-1] >= 2  # the planted storm: HMM + vol (+ BOCPD) agree
    assert out["consensus_text"].iloc[-1].startswith(("2/3", "3/3"))
    for text in bocpd.CONSENSUS_TEMPLATES.values():
        assert not DIRECTION.search(text), text


def test_params_fit_on_train_only() -> None:
    feats, regimes = _frames()
    a = bocpd.fit_params(feats, regimes, train_end="2015-12-31")
    later = feats.copy()
    later.loc[later["date"] > "2015-12-31", "ret_1d"] *= 10  # change the future → no effect
    b = bocpd.fit_params(later, regimes, train_end="2015-12-31")
    assert a == b
