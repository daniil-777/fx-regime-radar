"""The decision engine: deterministic, every branch tested, tolerance ordering sane, schedules sum
to the ratio, the table builds from real artifacts, and no template contains a direction word."""

from __future__ import annotations

import json

import pytest

from fxradar import config, decision, narrate


def test_hedge_ratio_branches_and_clipping() -> None:
    assert decision.hedge_ratio("hedge", "balanced", 0) == 0.75
    assert decision.hedge_ratio("wait", "balanced", 0) == 0.25
    assert decision.hedge_ratio("ladder", "balanced", 0) == 0.50
    # tolerance ordering: conservative covers more than aggressive, always
    for light in ("hedge", "ladder", "wait"):
        c = decision.hedge_ratio(light, "conservative", 0)
        b = decision.hedge_ratio(light, "balanced", 0)
        a = decision.hedge_ratio(light, "aggressive", 0)
        assert c > b > a
    # consensus nudge and the cap/floor
    assert decision.hedge_ratio("hedge", "conservative", 3) == 0.95
    assert decision.hedge_ratio("wait", "aggressive", 0) == 0.10
    # 5 % steps
    assert (decision.hedge_ratio("ladder", "conservative", 2) * 20) % 1 == 0


def test_tranche_schedules_sum_to_the_ratio() -> None:
    for light in ("hedge", "ladder", "wait"):
        for h in (1, 2, 4, 8, 12):
            ratio = decision.hedge_ratio(light, "balanced", 0)
            sched = decision.tranche_schedule(light, ratio, h)
            assert sum(t["fraction"] for t in sched) == pytest.approx(ratio, abs=0.02)
            assert all(0 <= t["week"] <= h for t in sched)
    # hedge is front-loaded: the first tranche is the largest
    sched = decision.tranche_schedule("hedge", 0.75, 4)
    assert sched[0]["fraction"] == max(t["fraction"] for t in sched)


def test_table_builds_from_the_committed_artifacts() -> None:
    pack = json.loads((config.DATA_DIR / "avatar_context.json").read_text())
    treasury = json.loads((config.DATA_DIR / "treasury_risk.json").read_text())
    table = decision.build_table(pack, treasury)
    assert set(table["pairs"]) == set(pack["pairs"]) & set(treasury["pairs"])
    for tols in table["pairs"].values():
        assert set(tols) == set(decision.TOLERANCES)
        for row in tols.values():
            assert 0.10 <= row["hedge_ratio"] <= 0.95
            assert row["es_99_1w"] is None or row["es_99_1w"] > 0
            assert set(row["schedule_by_horizon"]) == {"1", "2", "4", "8", "12"}
    assert "FinSA" in table["compliance"]


def test_no_direction_words_in_any_spoken_template() -> None:
    table = decision.build_table(
        json.loads((config.DATA_DIR / "avatar_context.json").read_text()),
        json.loads((config.DATA_DIR / "treasury_risk.json").read_text()),
    )
    narrate.check_narration(decision.ADVICE_DISCLOSURE)
    narrate.check_narration(table["method"])
    for tols in table["pairs"].values():
        for row in tols.values():
            narrate.check_narration(row["review_trigger"])
