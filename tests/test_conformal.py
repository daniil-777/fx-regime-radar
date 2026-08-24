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


def _toy_regimes() -> pd.DataFrame:
    dates = pd.bdate_range("2017-01-02", "2019-06-28")
    n = len(dates)
    pattern = (["calm"] * 7 + ["trend"] * 5 + ["chop"] * 6 + ["crisis"] * 2) * (n // 20 + 1)
    return pd.DataFrame({"date": dates, "pair": "EURUSD", "regime": pattern[:n]}).assign(
        change_risk_5d=np.linspace(0.05, 0.6, n)
    )


def test_frozen_test_coverage_honors_the_sealed_window() -> None:
    """Audit fix (receipt drift 5,922 -> 5,931): `through` caps the receipt population."""
    r = _toy_regimes()
    params = {"q": {"calm": 0.4, "trend": 0.6, "chop": 0.6, "crisis": 0.7}}
    full = conformal.frozen_test_coverage(r, params)
    sealed = conformal.frozen_test_coverage(r, params, through="2019-03-29")
    assert sealed["n"] < full["n"], "the seal must cap the population"
    assert sealed["frozen_through"] == "2019-03-29"
    assert full["frozen_through"] is None
    # growing the input beyond the seal date must not move the sealed receipt
    grown = pd.concat([r, _toy_regimes().assign(pair="GBPUSD")], ignore_index=True)
    sealed_grown = conformal.frozen_test_coverage(
        grown[grown["pair"] == "EURUSD"], params, through="2019-03-29"
    )
    assert sealed_grown["n"] == sealed["n"] and sealed_grown["overall"] == sealed["overall"]


def test_committed_fx_receipt_is_sealed_at_the_published_population() -> None:
    """The published receipt (README: n = 5,922) is frozen; the artifact must agree forever."""
    receipt = json.loads((ROOT / "data" / "conformal_coverage.json").read_text())
    assert receipt["frozen_test"]["frozen_through"] == "2026-08-10"
    assert receipt["frozen_test"]["n"] == 5922
    assert round(receipt["frozen_test"]["overall"], 3) == 0.916
    params = json.loads((ROOT / "models" / "conformal_v1.json").read_text())
    assert params["frozen_through"] == "2026-08-10"
