"""Phase 22: calibration strictly inside the validation years, crisis band wider than calm,
frozen-test coverage within 90 % ± 3 pp, deterministic, no theorem claims in user copy."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import config, conformal

ROOT = Path(__file__).resolve().parents[1]


def _regimes():
    return pd.read_parquet(ROOT / "data" / "regimes.parquet")


def test_calibration_dates_strictly_inside_validation_years() -> None:
    cal = conformal.calibration_rows(_regimes())
    assert cal["date"].min() >= pd.Timestamp(config.VAL_START)
    assert cal["date"].max() <= pd.Timestamp(config.VAL_END)
    assert cal["date"].min() > pd.Timestamp(config.TRAIN_END)
    assert len(cal) > 1000


def test_quantile_is_finite_sample_corrected() -> None:
    s = np.arange(1, 10) / 10  # n = 9 → k = ceil(10 * 0.9) = 9 → the largest
    assert conformal.conformal_quantile(s, 0.1) == 0.9
    assert np.isnan(conformal.conformal_quantile(np.array([]), 0.1))


def test_fit_is_deterministic_and_crisis_wider_than_calm() -> None:
    r = _regimes()
    a, b = conformal.fit(r), conformal.fit(r)
    assert a == b
    assert a["q"]["crisis"] > a["q"]["calm"]
    assert a["calibration"]["start"] >= "2017-01-01" and a["calibration"]["end"] <= "2018-12-31"
    committed = json.loads((ROOT / "models" / "conformal_v1.json").read_text())
    assert committed["q"] == a["q"]  # the frozen params are what fit() produces today


def test_frozen_test_coverage_within_three_points_of_ninety() -> None:
    r = _regimes()
    params = conformal.load_params(ROOT / "models" / "conformal_v1.json")
    cov = conformal.frozen_test_coverage(r, params)
    assert abs(cov["overall"] - 0.90) <= 0.03, cov["overall"]
    assert cov["n"] > 5000


def test_apply_clips_and_preserves_rows() -> None:
    r = _regimes().head(500)
    out = conformal.apply(r, {"q": {"calm": 0.5, "trend": 0.8, "chop": 0.8, "crisis": 0.7}})
    assert len(out) == len(r)
    assert (out["risk_lo"] >= 0).all() and (out["risk_hi"] <= 1).all()
    assert (out["risk_lo"] <= out["change_risk_5d"]).all()


def test_live_coverage_handles_missing_columns() -> None:
    assert conformal.live_coverage(None) == {"n": 0, "coverage": None}
    led = pd.DataFrame(
        {"outcome": [1.0, 0.0, np.nan], "risk_lo": [0.0, 0.0, 0.0], "risk_hi": [0.6, 0.6, 0.6]}
    )
    assert conformal.live_coverage(led) == {"n": 2, "coverage": 0.5}
