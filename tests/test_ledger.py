"""Live forward-test ledger: append-only + newest-date-only, hash chain, resolution == forecaster
label, summary nulls until warm, README block idempotence, round trip through disk."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fxradar import forecaster, ledger

PAIRS = ["EURUSD", "GBPUSD", "USDCHF"]
NOW = "2026-08-18T06:00:00Z"
META = {
    "threshold": 0.22,
    "train_pos_rate": 0.17,
    "test_scoreboard": [
        {
            "model": "XGBoost (ours, calibrated)",
            "pr_auc": 0.548,
            "precision": 0.45,
            "recall": 0.59,
            "brier": 0.102,
            "n": 5922,
            "pos_rate": 0.162,
        },
        {"model": "base_rate", "pr_auc": 0.162, "brier": 0.136},
    ],
}


def _regimes(n_days: int = 60, seed: int = 0) -> pd.DataFrame:
    """Sticky random regimes (so both label classes occur), random risks, one row per pair/day."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-01-05", periods=n_days)
    frames = []
    for pair in PAIRS:
        reg, cur = [], "calm"
        for _ in dates:
            if rng.random() < 0.15:
                cur = rng.choice(["calm", "trend", "chop", "crisis"])
            reg.append(cur)
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "pair": pair,
                    "regime": reg,
                    "change_risk_5d": rng.uniform(0, 1, n_days),
                    "anomaly_pct": rng.uniform(0, 100, n_days),
                    "model_version": "hmm=0.4.0|fc=1.1.0|siren=1.2.0",
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _simulate_daily_runs(regimes: pd.DataFrame, start_idx: int) -> pd.DataFrame:
    """Replay the pipeline day by day: on day d the ledger only ever sees rows <= d."""
    led = ledger.empty_ledger()
    for d in sorted(regimes["date"].unique())[start_idx:]:
        led, _ = ledger.append_latest(
            led, regimes[regimes["date"] <= d], f"{pd.Timestamp(d):%Y-%m-%d}T06:00Z"
        )
    return led


# --------------------------------------------------------------------------------------
# append: newest date only, forward only, idempotent, chained
# --------------------------------------------------------------------------------------
def test_append_records_only_the_newest_date_and_is_idempotent() -> None:
    reg = _regimes(30)
    led, added = ledger.append_latest(ledger.empty_ledger(), reg, NOW)
    assert added == len(PAIRS) and len(led) == len(PAIRS)
    assert (led["date"] == reg["date"].max()).all()  # nothing older is ever backfilled
    led2, added2 = ledger.append_latest(led, reg, NOW)  # same day twice (rerun)
    assert added2 == 0 and led2.equals(led)
    assert ledger.verify_chain(led2)
    assert led2["prev_hash"].iloc[0] == ledger.GENESIS
    assert (led2["prev_hash"].iloc[1:].to_numpy() == led2["row_hash"].iloc[:-1].to_numpy()).all()


def test_append_never_moves_backwards() -> None:
    reg = _regimes(30)
    led, _ = ledger.append_latest(ledger.empty_ledger(), reg, NOW)
    older = reg[reg["date"] < reg["date"].max()]  # a data-source rollback
    led2, added = ledger.append_latest(led, older, NOW)
    assert added == 0 and len(led2) == len(led)


def test_tampering_breaks_the_chain() -> None:
    led = _simulate_daily_runs(_regimes(20), 10)
    assert ledger.verify_chain(led)
    edited = led.copy()
    edited.loc[0, "change_risk_5d"] = 0.999  # rewrite a published forecast
    assert not ledger.verify_chain(edited)
    deleted = led.drop(index=len(led) // 2).reset_index(drop=True)  # remove an embarrassing row
    assert not ledger.verify_chain(deleted)
    relabelled = led.copy()
    relabelled.loc[1, "regime"] = "crisis"
    assert not ledger.verify_chain(relabelled)


# --------------------------------------------------------------------------------------
# resolution == the forecaster's label, exactly
# --------------------------------------------------------------------------------------
def test_resolution_matches_forecaster_build_labels() -> None:
    reg = _regimes(60, seed=3)
    led = _simulate_daily_runs(reg, 20)
    led, n = ledger.resolve(led, reg, NOW)
    matrix = reg.sort_values(["pair", "date"]).reset_index(drop=True)
    truth = matrix.assign(y=forecaster.build_labels(matrix))
    merged = led.merge(truth[["date", "pair", "y"]], on=["date", "pair"], how="left")
    # rows whose window is complete resolve to exactly build_labels' answer; the rest stay NaN
    assert n == int(merged["y"].notna().sum()) > 0
    pd.testing.assert_series_equal(
        merged["outcome"], merged["y"], check_names=False, check_dtype=False
    )
    assert merged.loc[merged["y"].isna(), "outcome"].isna().all()
    assert led.groupby("pair")["outcome"].apply(lambda s: s.isna().sum()).eq(ledger.HORIZON).all()


def test_resolve_is_idempotent_and_never_rewrites_outcomes() -> None:
    reg = _regimes(40, seed=1)
    led = _simulate_daily_runs(reg, 20)
    once, n1 = ledger.resolve(led, reg, NOW)
    twice, n2 = ledger.resolve(once, reg, "2026-09-01T06:00Z")
    assert n1 > 0 and n2 == 0
    pd.testing.assert_frame_equal(once, twice)
    assert ledger.verify_chain(
        twice
    )  # outcomes are outside the chain: filling them cannot break it


# --------------------------------------------------------------------------------------
# summary: null until warm, then the frozen-test metric code on the resolved rows
# --------------------------------------------------------------------------------------
def test_summary_is_null_while_warming_up_then_matches_forecaster_metrics() -> None:
    reg = _regimes(60, seed=5)
    led, _ = ledger.resolve(_simulate_daily_runs(reg, 20), reg, NOW)
    cold = ledger.summarize(led, 0.22, 0.17, ledger.frozen_from_meta(META), min_resolved=10_000)
    assert cold["metrics"] is None and cold["status"] == "warming up"
    assert cold["n_resolved"] > 0 and cold["chain_ok"] and cold["frozen_test"]["pr_auc"] == 0.548

    warm = ledger.summarize(led, 0.22, 0.17, ledger.frozen_from_meta(META), min_resolved=5)
    res = led[led["outcome"].notna()]
    expect = forecaster.metrics(res["outcome"].to_numpy(), res["change_risk_5d"].to_numpy(), 0.22)
    assert warm["status"] == "live"
    for k in ["pr_auc", "precision", "recall", "brier", "n", "pos_rate"]:
        assert warm["metrics"][k] == pytest.approx(expect[k])
    assert warm["metrics"]["base_rate_brier"] == pytest.approx(
        np.mean((0.17 - res["outcome"].to_numpy()) ** 2)
    )
    assert warm["n_forecasts"] == len(led) and warm["n_pending"] == len(led) - len(res)


def test_summary_scores_only_the_current_model_segment() -> None:
    reg = _regimes(60, seed=2)
    led, _ = ledger.resolve(_simulate_daily_runs(reg, 20), reg, NOW)
    cutoff = led["date"].max() - pd.Timedelta(days=10)
    led.loc[led["date"] > cutoff, "model_version"] = "hmm=0.5.0|fc=1.2.0|siren=1.2.0"  # a refit
    s = ledger.summarize(led, 0.22, 0.17, None, min_resolved=1)
    assert s["model_version"] == "hmm=0.5.0|fc=1.2.0|siren=1.2.0"
    assert s["n_forecasts"] == int((led["date"] > cutoff).sum()) < s["n_all_segments"] == len(led)


def test_single_class_gives_null_pr_auc_not_zero() -> None:
    reg = _regimes(40, seed=7)
    reg["regime"] = "calm"  # nothing ever changes → every outcome is 0
    led, _ = ledger.resolve(_simulate_daily_runs(reg, 20), reg, NOW)
    s = ledger.summarize(led, 0.22, 0.17, None, min_resolved=1)
    assert s["metrics"]["pr_auc"] is None and s["metrics"]["recall"] is None
    assert s["metrics"]["brier"] is not None


# --------------------------------------------------------------------------------------
# renderers
# --------------------------------------------------------------------------------------
def test_readme_block_replacement_is_idempotent_and_local() -> None:
    reg = _regimes(60, seed=5)
    led, _ = ledger.resolve(_simulate_daily_runs(reg, 20), reg, NOW)
    s = ledger.summarize(
        led, 0.22, 0.17, ledger.frozen_from_meta(META), min_resolved=5, generated_at_utc=NOW
    )
    block = ledger.readme_block(s)
    assert block.startswith(ledger.START_MARK) and block.endswith(ledger.END_MARK)
    assert "0.548" in block and f"{s['metrics']['brier']:.3f}" in block and "hash-chained" in block
    text = f"# Title\n\nintro\n\n{ledger.START_MARK}\nold stuff\n{ledger.END_MARK}\n\n## Next\nkeep me\n"
    once = ledger.update_readme(text, block)
    assert once.startswith("# Title\n\nintro\n\n") and once.endswith("\n\n## Next\nkeep me\n")
    assert "old stuff" not in once and block in once
    assert ledger.update_readme(once, block) == once  # idempotent
    assert ledger.update_readme("no markers here", block) == "no markers here"


def test_warming_up_block_and_badge_have_no_numbers() -> None:
    led, _ = ledger.append_latest(ledger.empty_ledger(), _regimes(30), NOW)
    s = ledger.summarize(led, 0.22, 0.17, ledger.frozen_from_meta(META), generated_at_utc=NOW)
    block, b = ledger.readme_block(s), ledger.badge(s)
    assert "Warming up" in block and "| — |" in block
    assert b["schemaVersion"] == 1 and b["label"] == "live record" and "warming up" in b["message"]
    empty = ledger.summarize(ledger.empty_ledger(), 0.22, 0.17, None, generated_at_utc=NOW)
    assert "starts with the first daily run" in ledger.readme_block(empty)


# --------------------------------------------------------------------------------------
# record + write: the pipeline path, through disk
# --------------------------------------------------------------------------------------
def test_record_and_write_outputs_round_trip(tmp_path: Path) -> None:
    reg = _regimes(40, seed=4)
    paths = dict(
        ledger_path=tmp_path / "ledger.parquet",
        record_path=tmp_path / "live_record.json",
        badge_path=tmp_path / "badges" / "live_record.json",
        readme_path=tmp_path / "README.md",
    )
    paths["readme_path"].write_text(f"# R\n{ledger.START_MARK}\nx\n{ledger.END_MARK}\n")
    dates = sorted(reg["date"].unique())
    for d in dates[-12:]:  # twelve daily runs, each seeing only data <= d
        led, s = ledger.record(
            reg[reg["date"] <= d],
            META,
            now_utc=f"{pd.Timestamp(d):%Y-%m-%d}T06:00Z",
            ledger_path=paths["ledger_path"],
        )
        ledger.write_outputs(led, s, **paths)
    disk = ledger.load(paths["ledger_path"])
    assert len(disk) == 12 * len(PAIRS) and ledger.verify_chain(disk)
    assert disk["outcome"].notna().sum() == (12 - ledger.HORIZON) * len(PAIRS)
    rec = json.loads(paths["record_path"].read_text())
    assert rec["n_forecasts"] == 36 and rec["n_resolved"] == 21 and rec["chain_ok"] is True
    assert rec["frozen_test"]["brier"] == 0.102 and rec["metrics"]["n"] == 21  # 21 >= MIN_RESOLVED
    assert json.loads(paths["badge_path"].read_text())["label"] == "live record"
    assert (
        ledger.START_MARK in paths["readme_path"].read_text()
        and "\nx\n" not in paths["readme_path"].read_text()
    )


def test_record_refuses_a_broken_chain(tmp_path: Path) -> None:
    reg = _regimes(30)
    led, _ = ledger.record(reg, META, now_utc=NOW, ledger_path=tmp_path / "l.parquet")
    led.loc[0, "change_risk_5d"] = 0.5
    ledger.save(led, tmp_path / "l.parquet")
    with pytest.raises(RuntimeError, match="chain broken"):
        ledger.record(reg, META, now_utc=NOW, ledger_path=tmp_path / "l.parquet")
