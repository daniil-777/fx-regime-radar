"""Arcade tests (phase 17): Brier math, resolution timing, lock-before-reveal, streaks, badges, ranks."""

from datetime import date

import pandas as pd
import pytest

from fxradar import arcade


def _regimes(regs: list[str], pair: str = "EURUSD", risk: float = 0.3) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(regs))
    return pd.DataFrame(
        {"date": dates, "pair": pair, "regime": regs, "days_in_regime": 1, "change_risk_5d": risk}
    )


@pytest.fixture
def conn(tmp_path):
    return arcade.connect(tmp_path / "arcade.db")


def test_brier_hand_values() -> None:
    assert arcade.brier(1.0, 1) == 0.0 and arcade.brier(0.0, 1) == 1.0
    assert arcade.brier(0.7, 1) == pytest.approx(0.09) and arcade.brier(0.7, 0) == pytest.approx(
        0.49
    )
    assert arcade.brier(0.5, 0) == pytest.approx(0.25)


def test_resolution_flip_on_day_3_vs_day_6() -> None:
    base = ["calm"] * 20
    flip3 = base[:]
    flip3[13] = "chop"  # call at index 10 -> day 3 flips -> outcome 1
    assert (
        arcade.outcome_for(
            _regimes(flip3), "EURUSD", str(pd.bdate_range("2024-01-01", periods=20)[10].date())
        )
        == 1
    )
    flip6 = base[:]
    flip6[16] = "chop"  # day 6: outside the 5-day window -> outcome 0
    assert (
        arcade.outcome_for(
            _regimes(flip6), "EURUSD", str(pd.bdate_range("2024-01-01", periods=20)[10].date())
        )
        == 0
    )
    # not matured yet: only 3 trading days after the call
    assert (
        arcade.outcome_for(
            _regimes(base), "EURUSD", str(pd.bdate_range("2024-01-01", periods=20)[16].date())
        )
        is None
    )


def test_lock_before_reveal(conn) -> None:
    regs = _regimes(["calm"] * 12, risk=0.42)
    pre = arcade.pre_lock_payload(regs, "EURUSD").as_dict()
    assert "model_risk" not in pre and "change_risk_5d" not in pre and 0.42 not in pre.values()
    cid = arcade.place_call(conn, regs, "sam", "EURUSD", 0.6)
    view = arcade.post_lock_view(conn, cid)
    assert view["model_risk"] == 0.42 and view["prob"] == 0.6 and view["outcome"] is None
    with pytest.raises(ValueError):
        arcade.place_call(conn, regs, "sam", "EURUSD", 0.5)  # one per pair per week


def test_resolution_and_ledger(conn) -> None:
    regs = _regimes(["calm"] * 5 + ["chop"] * 10, risk=0.2)
    # place a call on the day 5 rows before the end... build a frame where the call date has 5+ days after it
    call_regs = regs.iloc[:6]  # latest row = index 5 (first chop day)
    cid = arcade.place_call(conn, call_regs, "sam", "EURUSD", 0.8)
    assert arcade.resolve_calls(conn, call_regs) == 0  # not matured
    n = arcade.resolve_calls(
        conn, regs
    )  # now 9 more days exist -> matured; regime stays chop -> outcome 0
    assert n == 1
    v = arcade.post_lock_view(conn, cid)
    assert (
        v["outcome"] == 0
        and v["brier_user"] == pytest.approx(0.64)
        and v["brier_model"] == pytest.approx(0.04)
    )
    led = arcade.ledger(conn, "sam")
    assert led["resolved"] == 1 and led["wins"] == 0 and led["brier_user"] > led["brier_model"]


def test_streak_rollover_at_midnight_utc(conn) -> None:
    arcade.record_visit(conn, "sam", date(2024, 5, 1))
    arcade.record_visit(conn, "sam", date(2024, 5, 2))
    assert arcade.watch_streak(conn, "sam", date(2024, 5, 2)) == 2
    assert (
        arcade.watch_streak(conn, "sam", date(2024, 5, 3)) == 0
    )  # a new UTC day without a visit resets
    arcade.record_visit(conn, "sam", date(2024, 5, 3))
    assert arcade.watch_streak(conn, "sam", date(2024, 5, 3)) == 3


def test_ranks_depend_only_on_calls_and_brier() -> None:
    assert arcade.rank_for(0, None) == "observer"
    assert arcade.rank_for(6, 0.28) == "forecaster"
    assert arcade.rank_for(20, 0.24) == "storm chaser"
    assert arcade.rank_for(40, 0.15) == "regime master"
    assert arcade.rank_for(40, 0.40) == "observer"  # many calls but poorly calibrated: no rank


def test_badges_rules(conn) -> None:
    assert arcade.evaluate_badges(conn, "sam") == []
    arcade.record_event(conn, "sam", "methodology_opened")
    assert "methodology reader" in arcade.evaluate_badges(conn, "sam")
    assert "storm survivor" in arcade.evaluate_badges(
        conn, "sam", live_regimes={"EURUSD": "crisis"}
    )
    assert set(arcade.BADGES) == {
        "methodology reader",
        "first resolved call",
        "well calibrated",
        "storm survivor",
        "beat the model",
    }


def test_nickname_filter_and_storms() -> None:
    assert arcade.clean_nickname("  Sam_42! ") == "Sam_42"
    with pytest.raises(ValueError):
        arcade.clean_nickname("")
    with pytest.raises(ValueError):
        arcade.clean_nickname("shithead")
    storms = arcade.load_storms()
    assert (
        len(storms) >= 4
        and all(s["verified"] for s in storms)
        and all(len(s["story"].strip().split("\n")) == 3 for s in storms)
    )
