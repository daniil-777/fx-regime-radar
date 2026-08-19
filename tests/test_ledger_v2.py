"""Phase 20: schema-2 ledger rows (probabilities, votes, band, git SHA), corrections, the public
verifier, the head file and the per-segment scoreboard. Legacy schema-1 rows must keep verifying."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fxradar import ledger

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_ledger.py"


def _regimes(dates, pairs=("EURUSD", "USDCHF"), risk=0.1, with_extras=True) -> pd.DataFrame:
    parts = []
    for p in pairs:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(list(dates)),
                "pair": p,
                "regime": "calm",
                "change_risk_5d": risk,
                "anomaly_pct": 10.0,
                "model_version": "hmm=0.4.0|fc=1.1.0|siren=1.2.0",
            }
        )
        if with_extras:
            df["p_calm"], df["p_trend"], df["p_chop"], df["p_crisis"] = 0.7, 0.2, 0.05, 0.05
            df["risk_lo"], df["risk_hi"], df["conformal_q"] = 0.0, 0.6, 0.5
            df["bocpd_run_length"], df["bocpd_p_change_5d"] = 12, 0.03
            df["vote_hmm"], df["vote_bocpd"], df["vote_vol"], df["agreement"] = 0, 0, 1, 1
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def _run_days(n_days: int, ledger_df=None, sha="abc123def456"):
    led = ledger.empty_ledger() if ledger_df is None else ledger_df
    dates = pd.bdate_range("2026-01-05", periods=n_days)
    for i in range(n_days):
        led, _ = ledger.append_latest(
            led, _regimes(dates[: i + 1]), f"2026-01-0{i + 1}T06:00:00Z", sha=sha
        )
    return led


def test_schema2_rows_carry_probabilities_votes_band_and_sha() -> None:
    led = _run_days(1)
    assert len(led) == 2 and (led["schema"] == 2).all()
    assert led["git_sha"].iloc[0] == "abc123def456"
    assert np.isclose(led[["p_calm", "p_trend", "p_chop", "p_crisis"]].sum(axis=1), 1).all()
    assert (led["agreement"] == 1).all() and (led["risk_hi"] == 0.6).all()
    assert ledger.verify_chain(led)


def test_missing_optional_columns_become_null_and_still_hash() -> None:
    led, n = ledger.append_latest(
        ledger.empty_ledger(), _regimes(["2026-01-05"], with_extras=False), "t", sha="x"
    )
    assert n == 2 and led["p_calm"].isna().all() and led["agreement"].isna().all()
    assert ledger.verify_chain(led)


def test_legacy_schema1_file_loads_widened_and_verifies(tmp_path: Path) -> None:
    """Rows written before phase 20 keep their schema-1 hash and are never rewritten."""
    legacy = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-08-17"),
                "pair": "EURUSD",
                "regime": "calm",
                "change_risk_5d": 0.0112121164,
                "anomaly_pct": 75.6456241033,
                "model_version": "hmm=0.4.0|fc=1.1.0|siren=1.2.0",
                "recorded_at_utc": "2026-08-18T12:11:19Z",
                "prev_hash": ledger.GENESIS,
                "row_hash": "d654c1311d84bef2ca15e0b44ce4878afa7c6859ce05e96b398aeabd2d57067f",
                "outcome": np.nan,
                "resolved_at_utc": None,
            }
        ]
    )
    legacy.to_parquet(tmp_path / "ledger.parquet", index=False)
    led = ledger.load(tmp_path / "ledger.parquet")
    assert list(led.columns) == ledger.COLUMNS and int(led["schema"].iloc[0]) == 1
    assert ledger.verify_chain(led)
    led2, n = ledger.append_latest(led, _regimes(["2026-08-18"]), "2026-08-19T06:00:00Z", sha="x")
    assert n == 2 and led2["schema"].tolist() == [1, 2, 2] and ledger.verify_chain(led2)
    assert led2.iloc[0]["row_hash"] == legacy.iloc[0]["row_hash"]  # untouched


def test_committed_ledger_verifies_from_genesis() -> None:
    led = ledger.load(ROOT / "data" / "ledger.parquet")
    assert len(led) >= 3 and ledger.verify_chain(led)


def test_double_run_same_day_one_row_per_pair() -> None:
    led = _run_days(1)
    led2, n = ledger.append_latest(led, _regimes(["2026-01-05"]), "later", sha="x")
    assert n == 0 and len(led2) == 2


def test_tamper_middle_row_breaks_chain_and_public_verifier(tmp_path: Path) -> None:
    led = _run_days(3)
    assert ledger.verify_chain(led)
    bad = led.copy()
    bad.loc[2, "change_risk_5d"] = 0.9  # edit a middle row
    assert not ledger.verify_chain(bad)
    (tmp_path / "ledger.jsonl").write_text(ledger.to_jsonl(bad))
    proc = subprocess.run(
        [sys.executable, str(VERIFY), str(tmp_path / "ledger.jsonl")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1 and proc.stdout.startswith("BROKEN")
    (tmp_path / "ledger.jsonl").write_text(ledger.to_jsonl(led))
    proc = subprocess.run(
        [sys.executable, str(VERIFY), str(tmp_path / "ledger.jsonl")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0 and proc.stdout.startswith("VALID rows=6")
    assert led["row_hash"].iloc[-1] in proc.stdout


def test_deleting_a_row_breaks_the_chain() -> None:
    led = _run_days(3)
    assert not ledger.verify_chain(led.drop(index=3).reset_index(drop=True))


def test_correction_is_a_new_row_pointing_at_the_original() -> None:
    led = _run_days(2)
    original = led.iloc[1]
    fixed = {**original.to_dict(), "change_risk_5d": 0.33}
    led2 = ledger.append_correction(
        led, original["row_hash"], fixed, "2026-01-09T06:00:00Z", sha="x"
    )
    assert len(led2) == len(led) + 1
    assert led2.iloc[-1]["correction_of"] == original["row_hash"]
    assert led2.iloc[1]["change_risk_5d"] == 0.1  # original untouched
    assert ledger.verify_chain(led2)
    with pytest.raises(KeyError):
        ledger.append_correction(led, "deadbeef", fixed, "t", sha="x")


def test_scorer_refuses_unmatured_rows_and_segments_by_model_version() -> None:
    dates = pd.bdate_range("2026-01-05", periods=8)
    led = _run_days(1)
    reg = _regimes(dates)  # 8 trading days exist → the day-1 row has a full 5-day window
    led, n = ledger.resolve(led, reg, "t")
    assert n == 2 and led["outcome"].notna().all()
    led3, _ = ledger.append_latest(led, reg.assign(model_version="challenger=1.0.0"), "t2", sha="x")
    assert len(led3) == 4  # challenger rows record the same newest date under their own family
    led3, n = ledger.resolve(led3, reg, "t3")
    assert n == 0  # newest date: window incomplete → refuses to score
    board = ledger.scoreboard(led3, 0.22, 0.17, min_resolved=1)
    assert {b["family"] for b in board} == {"champion", "challenger"}
    champ = next(b for b in board if b["family"] == "champion")
    assert champ["n_resolved"] == 2 and champ["brier"] is not None
    chal = next(b for b in board if b["family"] == "challenger")
    assert chal["n_resolved"] == 0 and chal["brier"] is None


def test_head_line_and_outputs(tmp_path: Path) -> None:
    led = _run_days(2)
    summary = {
        "metrics": None,
        "n_resolved": 0,
        "min_resolved": 20,
        "scoreboard": ledger.scoreboard(led, 0.22, 0.17),
    }
    ledger.write_outputs(
        led,
        summary,
        ledger_path=tmp_path / "ledger.parquet",
        record_path=tmp_path / "live_record.json",
        badge_path=tmp_path / "badge.json",
        readme_path=None,
        reports_dir=tmp_path,
    )
    head = (tmp_path / "ledger_head.txt").read_text().split()
    assert head[0] == led["row_hash"].iloc[-1] and head[1] == "2026-01-06" and head[2] == "4"
    assert (tmp_path / "ledger.jsonl").read_text().count("\n") == 4
    assert (tmp_path / ledger.SCOREBOARD_MD.name).exists()
