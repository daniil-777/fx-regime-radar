"""Pipeline tests (phase 06): stage ordering, failure honesty (artifacts untouched), status file."""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from fxradar import config

_spec = importlib.util.spec_from_file_location(
    "run_daily", config.ROOT / "pipelines" / "run_daily.py"
)
run_daily = importlib.util.module_from_spec(_spec)
sys.modules["run_daily"] = run_daily
_spec.loader.exec_module(run_daily)


def _redirect_artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PRICES_PATH", tmp_path / "prices.parquet")
    monkeypatch.setattr(config, "FEATURES_PATH", tmp_path / "features.parquet")
    monkeypatch.setattr(config, "REGIMES_PATH", tmp_path / "regimes.parquet")
    monkeypatch.setattr(run_daily, "STATUS_PATH", tmp_path / "pipeline_status.json")


def _fake_stages(prices_sample: pd.DataFrame):
    def s_data(ctx):
        ctx["prices"] = prices_sample

    def s_features(ctx):
        ctx["features"] = prices_sample[["date", "pair"]].assign(x=1.0)

    def s_hmm(ctx):
        ctx["regimes"] = prices_sample[["date", "pair"]].assign(regime="calm")

    return [("data", s_data), ("features", s_features), ("hmm", s_hmm)]


def test_success_writes_all_artifacts_and_status(monkeypatch, tmp_path, prices_sample) -> None:
    _redirect_artifacts(monkeypatch, tmp_path)
    assert run_daily.run(_fake_stages(prices_sample)) == 0
    for name in ["prices", "features", "regimes"]:
        assert (tmp_path / f"{name}.parquet").exists()
    status = pd.read_json(tmp_path / "pipeline_status.json", typ="series")
    assert set(status["stage_seconds"]) == {"data", "features", "hmm"}
    assert status["data_through"] == str(prices_sample["date"].max().date())


def test_failure_leaves_artifacts_untouched_and_exits_nonzero(
    monkeypatch, tmp_path, prices_sample
) -> None:
    _redirect_artifacts(monkeypatch, tmp_path)
    (tmp_path / "prices.parquet").write_bytes(b"old")
    (tmp_path / "regimes.parquet").write_bytes(b"old")

    def boom(ctx):
        raise RuntimeError("Yahoo is down")

    stages = _fake_stages(prices_sample)
    stages[0] = ("data", boom)
    assert run_daily.run(stages) == 1
    assert (tmp_path / "prices.parquet").read_bytes() == b"old"  # last good state preserved
    assert (tmp_path / "regimes.parquet").read_bytes() == b"old"
    assert not (tmp_path / "pipeline_status.json").exists()


def test_simulated_failure_env_var(monkeypatch, tmp_path, prices_sample) -> None:
    _redirect_artifacts(monkeypatch, tmp_path)
    monkeypatch.setenv("FXRADAR_SIMULATE_FAILURE", "hmm")
    assert run_daily.run(_fake_stages(prices_sample)) == 1
    assert not (tmp_path / "regimes.parquet").exists()


def test_registered_stage_order() -> None:
    assert [n for n, _ in run_daily.STAGES][:3] == ["data", "features", "hmm"]


def test_ledger_stage_runs_after_siren_and_before_narrator() -> None:
    names = [n for n, _ in run_daily.STAGES]
    assert names.index("siren") < names.index("ledger") < names.index("narrator")


def test_ledger_stage_records_and_defers_writes_to_write_stage(monkeypatch, tmp_path) -> None:
    from fxradar import ledger

    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "ledger.parquet")
    dates = pd.bdate_range("2026-01-05", periods=8)
    regimes = pd.concat(
        pd.DataFrame(
            {
                "date": dates,
                "pair": p,
                "regime": "calm",
                "change_risk_5d": 0.1,
                "anomaly_pct": 10.0,
                "model_version": "hmm=0.4.0|fc=1.1.0|siren=1.2.0",
            }
        )
        for p in ["EURUSD", "USDCHF"]
    )
    ctx = {"regimes": regimes, "forecaster_meta": {"threshold": 0.22, "train_pos_rate": 0.17}}
    run_daily.stage_ledger(ctx)
    assert len(ctx["ledger"]) == 2 and ctx["live_record"]["added_today"] == 2
    assert not (tmp_path / "ledger.parquet").exists()  # nothing on disk until the write stage
    assert "ledger.parquet + live_record.json (+ README block)" in ctx["extra_writers"]
