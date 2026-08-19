"""Phase 20: PSI / KS fire on synthetic shifted fixtures and stay quiet on stable ones."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fxradar import drift


def test_psi_zero_on_same_distribution_and_large_on_shift() -> None:
    rng = np.random.default_rng(0)
    train = rng.normal(0, 1, 5000)
    assert drift.psi(train, rng.normal(0, 1, 2000)) < 0.05
    assert drift.psi(train, rng.normal(3, 1, 2000)) > 1.0
    assert drift.psi_label(0.05) == "stable" and drift.psi_label(0.5) == "drifted"


def test_feature_drift_fires_on_a_shifted_recent_window() -> None:
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2010-01-01", periods=2000)
    df = pd.DataFrame({"date": dates, "pair": "EURUSD", "ret_1d": rng.normal(0, 0.005, 2000)})
    for c in [
        "vol_20",
        "vol_60",
        "vol_ratio",
        "mom_20",
        "rng_hl",
        "corr_20",
        "ret_5d_abs",
        "hmm_entropy",
    ]:
        df[c] = rng.normal(0, 1, 2000)
    quiet = drift.feature_drift(df, train_end="2015-12-31", window=60)
    assert sum(v["status"] == "drifted" for v in quiet.values()) <= 2  # p95 rule: ~5 % false alarms
    shifted = df.copy()
    shifted.loc[shifted.index[-60:], "vol_20"] += 8.0
    loud = drift.feature_drift(shifted, train_end="2015-12-31", window=60)
    assert loud["vol_20"]["status"] == "drifted" and loud["vol_20"]["ks"] > 0.9


def test_status_json_shape_from_committed_artifacts() -> None:
    feats = pd.read_parquet(drift.config.FEATURES_PATH)
    s = drift.status(feats, generated_at_utc="2026-01-01T00:00:00Z")
    assert set(s) >= {"model_stale", "features", "hmm", "drifted_features", "stale_pairs"}
    assert isinstance(s["model_stale"], bool)
    assert set(s["hmm"]) == set(drift.config.PAIRS)
