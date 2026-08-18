"""Forecaster tests (phase 07): labels, embargo gaps, truncation invariance of the matrix,
threshold rule, calibration, scoring shape. No training on real data here (fast, deterministic)."""

import numpy as np
import pandas as pd
import pytest

from fxradar import config, features, forecaster
from fxradar import hmm_model as hm


def _regimes_from(prices_sample: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # USDCHF's 15 months around the SNB shock give a singular state covariance on a tiny sample,
    # so the toy uses the two other pairs (pair_USDCHF is simply 0 in the matrix)
    feats = features.build_features(prices_sample[prices_sample["pair"] != "USDCHF"])
    parts = []
    for _pair, g in feats.groupby("pair"):
        b = hm.fit_hmm(g.reset_index(drop=True), train_end="2015-12-31", random_state=42)
        parts.append(hm.score_pair(b, g.reset_index(drop=True)))
    scored = pd.concat(parts, ignore_index=True)
    feats = feats.merge(scored[["date", "pair", *hm.POST_HMM_FEATURES]], on=["date", "pair"])
    return feats, scored[hm.REGIME_COLUMNS]


@pytest.fixture(scope="module")
def toy(prices_sample):
    return _regimes_from(prices_sample)


def test_labels_exact_semantics() -> None:
    m = pd.DataFrame(
        {
            "date": pd.bdate_range("2020-01-01", periods=12),
            "pair": "X",
            "regime": ["a"] * 6 + ["b"] * 6,
        }
    )
    y = forecaster.build_labels(m, horizon=5)
    # rows 1..5 have the change (row 6) inside t+1..t+5; row 0 does not (rows 1..5 are all 'a')
    assert y.iloc[0] == 0.0 and y.iloc[1:6].eq(1.0).all() and y.iloc[6] == 0.0
    assert y.iloc[-5:].isna().all()


def test_embargo_gaps_exist(toy) -> None:
    feats, regs = toy
    m = forecaster.build_matrix(feats, regs)
    m["date"] = m["date"] + pd.DateOffset(
        years=2
    )  # shift the 2014-15 fixture onto 2016-17 boundaries
    split = forecaster.assign_splits(m, embargo=5)
    for _, g in m.assign(split=split).groupby("pair"):
        g = g.sort_values("date")
        tr, va = g[g["split"] == "train"], g[g["split"] == "val"]
        assert len(tr) and len(va)
        between = g[(g["date"] > tr["date"].max()) & (g["date"] < va["date"].min())]
        assert len(between) >= 10  # 5 dropped on each side -> at least 10 rows nobody uses
        assert (between["split"] == "embargo").all()
        assert (g[g["date"] <= pd.Timestamp(config.TRAIN_END)]["split"] != "val").all()


def test_matrix_is_truncation_invariant(toy) -> None:
    """All forecaster inputs (incl. HMM-derived) must be causal: cut the last 20 rows per pair and
    the overlapping matrix rows are identical."""
    feats, regs = toy
    full = forecaster.build_matrix(feats, regs)
    cut_f = feats[feats.groupby("pair").cumcount(ascending=False) >= 20]
    cut_r = regs[regs.groupby("pair").cumcount(ascending=False) >= 20]
    part = forecaster.build_matrix(cut_f, cut_r)
    ov = full.merge(part[["date", "pair"]], on=["date", "pair"])
    pd.testing.assert_frame_equal(
        ov.reset_index(drop=True), part.reset_index(drop=True), check_exact=True
    )


def test_feature_list_is_exactly_the_spec() -> None:
    assert forecaster.FEATURES == [
        "vol_20", "vol_60", "vol_ratio", "mom_20", "rng_hl", "corr_20", "ret_5d_abs",
        "days_in_regime", "hmm_entropy", "vol_trend",
        "regime_trend", "regime_chop", "regime_crisis", "pair_GBPUSD", "pair_USDCHF",
    ]  # fmt: skip


def test_choose_threshold_meets_recall() -> None:
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500)
    p = np.clip(y * 0.4 + rng.uniform(0, 0.6, 500), 0, 1)
    thr = forecaster.choose_threshold(p, y, 0.6)
    assert (((p >= thr) & (y == 1)).sum() / (y == 1).sum()) >= 0.6
    assert (((p >= thr + 0.01) & (y == 1)).sum() / (y == 1).sum()) < 0.6 or thr >= 0.99


def test_platt_calibration_fixes_a_known_distortion() -> None:
    rng = np.random.default_rng(1)
    true_p = rng.uniform(0.02, 0.6, 4000)
    y = (rng.uniform(size=4000) < true_p).astype(int)
    z = np.log(true_p / (1 - true_p))
    raw = 1 / (1 + np.exp(-(z + 1.2)))  # over-predicting version of the truth
    a, b = forecaster.fit_calibrator(raw, y)
    cal = forecaster.calibrate(raw, a, b)
    assert abs(cal.mean() - y.mean()) < 0.02 and abs(raw.mean() - y.mean()) > 0.15
    assert abs(a - 1.0) < 0.15 and abs(b + 1.2) < 0.2


def test_top_drivers_shape() -> None:
    sv = np.array([[0.1, -0.9, 0.3, 0.0] + [0.0] * (len(forecaster.FEATURES) - 4)])
    td = forecaster.top_drivers(sv, k=3)
    assert td == [["vol_60", "vol_ratio", "vol_20"]] and all(isinstance(s, str) for s in td[0])


_have = forecaster.model_path().exists() and config.REGIMES_PATH.exists()


@pytest.mark.skipif(not _have, reason="forecaster artifacts not built")
def test_saved_model_scores_contract_columns() -> None:
    model, meta = forecaster.load_model()
    assert meta["features"] == forecaster.FEATURES and "calibration" in meta
    r = pd.read_parquet(config.REGIMES_PATH)
    assert {"change_risk_5d", "top_drivers"} <= set(r.columns)
    assert r["change_risk_5d"].between(0, 1).all() and r["top_drivers"].map(len).eq(3).all()
