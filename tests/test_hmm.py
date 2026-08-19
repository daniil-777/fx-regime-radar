"""Tests for the HMM regime model (phase 03): filtering correctness, causality, naming, artifacts."""

import numpy as np
import pandas as pd
import pytest
from hmmlearn.hmm import GaussianHMM

from fxradar import config, features
from fxradar import hmm_model as hm


def _toy_model(seed: int = 0, separation: float = 2.0) -> GaussianHMM:
    """A small hand-built 4-state, 3-dim Gaussian HMM (sticky transitions).

    `separation` scales the state means: small values give overlapping states, where the
    future genuinely changes the smoothed posterior."""
    rng = np.random.default_rng(seed)
    m = GaussianHMM(n_components=4, covariance_type="full", random_state=seed)
    m.startprob_ = np.array([0.4, 0.3, 0.2, 0.1])
    a = np.full((4, 4), 0.02) + np.eye(4) * 0.92
    m.transmat_ = a / a.sum(axis=1, keepdims=True)
    m.means_ = rng.normal(0, separation, size=(4, 3))
    covs = []
    for _ in range(4):
        b = rng.normal(0, 0.5, size=(3, 3))
        covs.append(b @ b.T + 0.3 * np.eye(3))
    m.covars_ = np.array(covs)
    return m


# --------------------------------------------------------------------------------------
# filtering: forward algorithm vs brute force on prefixes
# --------------------------------------------------------------------------------------
def test_filtered_probs_match_bruteforce_prefix_recompute() -> None:
    """The smoothed posterior at the LAST step of the prefix X[:t+1] cannot use any future, so it
    must equal the filtered probability at t. hmmlearn's predict_proba on the prefix is the oracle.
    """
    m = _toy_model()
    X, _ = m.sample(60, random_state=1)
    filt = hm.filtered_probs(m, X)
    assert filt.shape == (60, 4)
    np.testing.assert_allclose(filt.sum(axis=1), 1.0, atol=1e-12)
    for t in range(60):
        brute = m.predict_proba(X[: t + 1])[-1]
        np.testing.assert_allclose(filt[t], brute, atol=1e-8)


def test_filtered_probs_are_causal_but_smoothed_are_not() -> None:
    """Truncate the series: filtered rows before the cut are identical; smoothed rows change."""
    m = _toy_model(seed=3, separation=0.6)  # overlapping states: hindsight matters
    X, _ = m.sample(200, random_state=2)
    full = hm.filtered_probs(m, X)
    part = hm.filtered_probs(m, X[:150])
    np.testing.assert_allclose(full[:150], part, atol=1e-12)
    smoothed_full = m.predict_proba(X)[:150]
    smoothed_part = m.predict_proba(X[:150])
    assert (
        np.abs(smoothed_full - smoothed_part).max() > 1e-6
    )  # the future leaks into smoothed values


def test_frame_log_likelihood_matches_hmmlearn() -> None:
    m = _toy_model(seed=5)
    X, _ = m.sample(30, random_state=4)
    ours = hm.frame_log_likelihood(m, X)
    theirs = m._compute_log_likelihood(X)
    np.testing.assert_allclose(ours, theirs, atol=1e-9)


# --------------------------------------------------------------------------------------
# naming rule, run length, entropy
# --------------------------------------------------------------------------------------
def test_name_states_rule() -> None:
    labels = np.array([0] * 10 + [1] * 10 + [2] * 10 + [3] * 10)
    tr = pd.DataFrame(
        {
            "ret_1d": 0.0,
            "vol_20": np.repeat(
                [0.15, 0.05, 0.09, 0.10], 10
            ),  # 1 lowest -> calm, 0 highest -> crisis
            "mom_20": np.repeat(
                [0.0, 0.0, 0.001, -0.02], 10
            ),  # of {2, 3}: 3 has larger |mom| -> trend
        }
    )
    mapping = hm.name_states(tr, labels)
    assert mapping == {1: "calm", 3: "trend", 2: "chop", 0: "crisis"}
    assert sorted(mapping.values()) == sorted(hm.REGIMES)
    with pytest.raises(ValueError):
        hm.name_states(tr, np.where(labels == 3, 2, labels))  # only 3 states present


def test_run_length() -> None:
    s = pd.Series(["a", "a", "b", "b", "b", "a", "c"])
    assert hm.run_length(s).tolist() == [1, 2, 1, 2, 3, 1, 1]


def test_score_pair_outputs_and_causality(prices_sample: pd.DataFrame) -> None:
    """score_pair on the fixture with a toy-fitted bundle: contract columns, entropy in [0, ln 4],
    vol_trend in {-1,0,1}, days_in_regime resets on change, and truncation invariance."""
    feats = features.build_features(prices_sample)
    g = feats[feats["pair"] == "EURUSD"].reset_index(drop=True)
    bundle = hm.fit_hmm(g, train_end="2015-12-31", random_state=42)  # fixture is 2014-10..2015-12
    out = hm.score_pair(bundle, g)
    assert list(out.columns) == [
        *hm.REGIME_COLUMNS[:6],
        *hm.PROB_COLUMNS,
        "vol_trend",
        "model_version",
    ]
    assert set(out["regime"]) <= set(hm.REGIMES)
    assert out["regime_prob"].between(0.25, 1.0).all()
    assert out["hmm_entropy"].between(0.0, np.log(4) + 1e-12).all()
    assert set(out["vol_trend"].unique()) <= {-1.0, 0.0, 1.0}
    changes = out["regime"].ne(out["regime"].shift(1))
    assert (out.loc[changes, "days_in_regime"] == 1).all()
    assert (out["model_version"] == "hmm=0.4.0").all()

    part = hm.score_pair(bundle, g.iloc[:-30])
    pd.testing.assert_frame_equal(out.iloc[:-30].reset_index(drop=True), part, check_exact=True)


def test_scaler_and_model_fit_on_train_only(prices_sample: pd.DataFrame) -> None:
    feats = features.build_features(prices_sample)
    g = feats[feats["pair"] == "GBPUSD"].reset_index(drop=True)
    bundle = hm.fit_hmm(g, train_end="2015-11-30", random_state=42)
    tr = g[g["date"] <= pd.Timestamp("2015-11-30")]
    np.testing.assert_allclose(
        bundle.scaler.mean_, tr[hm.HMM_FEATURES].mean().to_numpy(), atol=1e-12
    )
    assert bundle.train_end == "2015-11-30"
    with pytest.raises(ValueError):
        hm.fit_hmm(g, train_end="2015-03-31")  # too few training rows: refuse


def test_bundle_roundtrip(tmp_path, prices_sample: pd.DataFrame) -> None:
    feats = features.build_features(prices_sample)
    g = feats[feats["pair"] == "GBPUSD"].reset_index(drop=True)
    bundle = hm.fit_hmm(g, train_end="2015-12-31", random_state=42)
    path = hm.save_bundle(bundle, models_dir=tmp_path)
    assert path.name == "hmm_GBPUSD_v0.4.0.joblib"
    back = hm.load_bundle("GBPUSD", models_dir=tmp_path)
    assert back.mapping == bundle.mapping and back.pair == "GBPUSD"
    np.testing.assert_allclose(back.model.transmat_, bundle.model.transmat_)
    pd.testing.assert_frame_equal(hm.score_pair(back, g), hm.score_pair(bundle, g))


# --------------------------------------------------------------------------------------
# sanity on the shipped models / artifacts (skipped if not built yet)
# --------------------------------------------------------------------------------------
_have_models = all(hm.bundle_path(p).exists() for p in config.PAIRS)


@pytest.mark.skipif(not _have_models, reason="saved HMM bundles not present")
def test_saved_models_are_sticky_and_mapping_is_permutation() -> None:
    feats = pd.read_parquet(config.FEATURES_PATH)
    for pair in config.PAIRS:
        b = hm.load_bundle(pair)
        assert np.diag(b.model.transmat_).mean() > 0.8, pair
        assert sorted(b.mapping.values()) == sorted(hm.REGIMES) and sorted(b.mapping) == [
            0,
            1,
            2,
            3,
        ]
        g = feats[(feats["pair"] == pair) & (feats["date"] <= pd.Timestamp(config.TRAIN_END))]
        states = hm.filtered_probs(
            b.model, b.scaler.transform(g[hm.HMM_FEATURES].to_numpy())
        ).argmax(axis=1)
        assert len(set(states)) == 4, pair
        assert b.train_end == config.TRAIN_END


@pytest.mark.skipif(not config.REGIMES_PATH.exists(), reason="regimes.parquet not built yet")
def test_regimes_parquet_matches_contract() -> None:
    r = pd.read_parquet(config.REGIMES_PATH)
    assert list(r.columns[:6]) == hm.REGIME_COLUMNS[:6] and "model_version" in r.columns
    assert set(r["pair"]) == set(config.PAIRS) and set(r["regime"]) <= set(hm.REGIMES)
    f = pd.read_parquet(config.FEATURES_PATH)
    for col in hm.POST_HMM_FEATURES:
        assert col in f.columns
    assert len(f) == len(r)
