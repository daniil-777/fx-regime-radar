"""Advisor tests: stability index bounds/monotonicity, durability math, risk budget rules,
allocation, sizing, snapshot shape, and the Q&A guardrails."""

import numpy as np
import pandas as pd
import pytest

from fxradar import advisor


def _row(**kw) -> pd.Series:
    base = {
        "date": pd.Timestamp("2024-01-05"),
        "pair": "EURUSD",
        "regime": "calm",
        "regime_prob": 0.99,
        "days_in_regime": 10,
        "change_risk_5d": 0.05,
        "anomaly_pct": 30.0,
        "vol_20": 0.07,
        "vol_ratio": 0.9,
        "hmm_entropy": 0.02,
        "top_drivers": ["vol_20", "rng_hl", "mom_20"],
    }
    base.update(kw)
    return pd.Series(base)


def test_stability_index_bounds_and_ordering() -> None:
    calm, _ = advisor.stability_index(_row())
    crisis, comps = advisor.stability_index(
        _row(regime="crisis", change_risk_5d=0.6, anomaly_pct=99.5, vol_ratio=2.5, hmm_entropy=1.0)
    )
    assert 0 <= crisis < calm <= 100 and calm > 85 and crisis < 25
    assert (
        set(comps) == set(advisor.STABILITY_WEIGHTS)
        and abs(sum(advisor.STABILITY_WEIGHTS.values()) - 1) < 1e-12
    )
    assert advisor.stability_word(calm) == "Fair" and advisor.stability_word(crisis) in {
        "Stormy",
        "Severe",
    }
    # more change risk never raises stability
    a, _ = advisor.stability_index(_row(change_risk_5d=0.1))
    b, _ = advisor.stability_index(_row(change_risk_5d=0.5))
    assert b < a


def test_durability_math() -> None:
    assert advisor.expected_regime_duration(0.95) == pytest.approx(20.0)
    assert advisor.expected_regime_duration(0.98) == pytest.approx(50.0)
    d = advisor.durability(_row(days_in_regime=79), 0.98)
    assert d["typical_days"] == 50.0 and d["days_in_regime"] == 79 and "memoryless" in d["note"]
    assert advisor.durability(_row(), None)["typical_days"] is None


def test_risk_budget_rules() -> None:
    assert advisor.risk_budget(_row())["budget"] == 1.0
    stopped = advisor.risk_budget(_row(anomaly_pct=99.0))
    assert stopped["budget"] == 0.0 and "siren stop" in stopped["reasons"][0]
    risky = advisor.risk_budget(_row(change_risk_5d=0.5))
    assert risky["budget"] == pytest.approx(0.5)
    crisis = advisor.risk_budget(_row(regime="crisis", change_risk_5d=0.5, anomaly_pct=95.0))
    assert crisis["budget"] == pytest.approx(0.5 * 0.5 * 0.7) and len(crisis["reasons"]) == 3
    assert all(
        0 <= advisor.risk_budget(_row(regime=r))["budget"] <= 1
        for r in ["calm", "trend", "chop", "crisis"]
    )
    # never a direction word
    for r in [stopped, risky, crisis]:
        assert not any(
            w in " ".join(r["reasons"]).lower() for w in ["buy", "sell", "long", "short"]
        )


def test_allocation_and_sizing() -> None:
    rows = {"A": _row(pair="A"), "B": _row(pair="B", anomaly_pct=99.0), "C": _row(pair="C")}
    w = advisor.allocation(rows, {"A": 0.05, "B": 0.10, "C": 0.10})
    assert (
        w["B"] == 0.0
        and w["A"] == pytest.approx(2 / 3, abs=1e-3)
        and w["C"] == pytest.approx(1 / 3, abs=1e-3)
    )
    s = advisor.sizing(10_000, 0.10, 0.20, 1.0)
    assert s["notional"] == 5_000.0 and s["leverage"] == 0.5
    assert advisor.sizing(10_000, 0.10, 0.02, 1.0)["leverage"] == 2.0  # capped
    assert advisor.sizing(10_000, 0.10, 0.20, 0.0)["notional"] == 0.0


def test_snapshot_and_template_answers(prices_sample: pd.DataFrame) -> None:
    from fxradar import features, universes
    from fxradar import hmm_model as hm

    feats = features.build_features(prices_sample[prices_sample["pair"] != "USDCHF"])
    parts = []
    for _p, g in feats.groupby("pair"):
        b = hm.fit_hmm(g.reset_index(drop=True), train_end="2015-12-31", random_state=42)
        parts.append(hm.score_pair(b, g.reset_index(drop=True)))
    scored = pd.concat(parts, ignore_index=True)
    regimes = scored[hm.REGIME_COLUMNS].assign(
        change_risk_5d=0.2,
        anomaly_pct=50.0,
        top_drivers=[["vol_20", "rng_hl", "mom_20"]] * len(scored),
    )
    feats = feats.merge(scored[["date", "pair", *hm.POST_HMM_FEATURES]], on=["date", "pair"])
    uni = universes.get("fx")
    snap = advisor.snapshot(
        regimes, feats, prices_sample, transmat_diag={"EURUSD": {"calm": 0.97}}, universe=uni
    )
    assert set(snap["markets"]) == {"EURUSD", "GBPUSD"} and 0 <= snap["overall_stability"] <= 100
    m = snap["markets"]["EURUSD"]
    assert {
        "stability",
        "risk_budget",
        "durability",
        "allocation_weight",
        "stability_components",
    } <= set(m)
    assert abs(sum(x["allocation_weight"] for x in snap["markets"].values()) - 1) < 1e-6
    # guardrails: direction questions are refused; stability and budget questions are answered from the snapshot
    text, source = advisor.answer("should I buy EURUSD now?", snap, api_key=None)
    assert source == "template" and "never predicts price direction" in text
    text, _ = advisor.answer("how stable is the market?", snap, api_key=None)
    assert "Overall stability" in text and "Evidence:" in text
    text, _ = advisor.answer("how much should I invest?", snap, api_key=None)
    assert (
        "risk budget" in text.lower()
        and "Evidence:" in text
        and not any(w in text.lower() for w in [" buy ", " sell "])
    )
    assert "Stability:" in advisor.answer("what does stability mean?", snap, api_key=None)[0]
    assert np.isfinite(snap["overall_stability"])
