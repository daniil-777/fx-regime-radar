"""Storm replays (phase 26): the replay engine equals the full-history artifact and the live ledger,
is truncation-invariant itself, and its reports are templated without hindsight or direction words.
"""

from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import pytest

from fxradar import config, replay

HAVE_ARTIFACTS = all(
    p.exists()
    for p in [config.PRICES_PATH, config.REGIMES_PATH, config.MODELS_DIR / "manifest.json"]
)
needs_artifacts = pytest.mark.skipif(not HAVE_ARTIFACTS, reason="artifacts/models not built")
CORE = ["regime_prob", "hmm_entropy", "change_risk_5d", "anomaly_pct", "anomaly_score"]
DIRECTION_WORDS = re.compile(
    r"\b(rise|rises|rose|rising|fall|falls|fell|falling|up|down|buy|sell|long|short|target|"
    r"bullish|bearish|rally|rallies|plunge|plunged|drop|dropped|climb|climbed|soar|soared|"
    r"higher|lower|gain|gains|loss|losses)\b",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    return pd.read_parquet(config.PRICES_PATH) if HAVE_ARTIFACTS else pd.DataFrame()


@pytest.fixture(scope="module")
def regimes() -> pd.DataFrame:
    return pd.read_parquet(config.REGIMES_PATH) if HAVE_ARTIFACTS else pd.DataFrame()


def _compare(rep: pd.DataFrame, ref: pd.DataFrame, cols: list[str], tol: float) -> None:
    m = rep.merge(ref, on=["date", "pair"], suffixes=("_r", "_a"))
    assert len(m) == len(rep), "every replayed (date, pair) must exist in the reference"
    assert (m["regime_r"] == m["regime_a"]).all(), m[["date", "pair", "regime_r", "regime_a"]]
    for c in cols:
        if f"{c}_a" in m.columns:
            np.testing.assert_allclose(m[f"{c}_r"], m[f"{c}_a"], atol=tol, rtol=0, err_msg=c)


# --------------------------------------------------------------------------------------
# the engine equals the full-history artifact (causality made visible)
# --------------------------------------------------------------------------------------
@needs_artifacts
def test_replay_equals_full_history(prices: pd.DataFrame, regimes: pd.DataFrame) -> None:
    """Three days of March 2020, all pairs: prices truncated at t -> the same row the full-history
    artifact holds for t. The forward filter, every feature and the siren's train-period reference
    are causal, so the agreement is exact (we assert 1e-9; observed 0.0 / 1e-16)."""
    rep = replay.replay(prices, "2020-03-09", "2020-03-11")
    assert len(rep) == 9 and list(rep.columns) == replay.REPLAY_COLUMNS
    _compare(rep, regimes, CORE + ["days_in_regime", "p_calm", "p_crisis"], tol=1e-9)
    m = rep.merge(regimes, on=["date", "pair"], suffixes=("_r", "_a"))
    for a, b in zip(m["top_drivers_r"], m["top_drivers_a"], strict=True):
        assert list(a) == list(b)


@needs_artifacts
def test_replay_equals_ledger(prices: pd.DataFrame) -> None:
    """For dates the live ledger covers, the replay reproduces the recorded forecasts (1e-9).
    The ledger is what was published BEFORE the outcome existed — the replay must meet it."""
    ledger_path = config.DATA_DIR / "ledger.parquet"
    if not ledger_path.exists():
        pytest.skip("no ledger yet")
    led = pd.read_parquet(ledger_path)
    led = led[~led["model_version"].astype(str).str.startswith("challenger")]  # champion rows
    led = led[led["date"].isin(prices["date"])]
    if led.empty:
        pytest.skip("ledger holds no date present in prices")
    day = led["date"].max()  # one day keeps the test fast; every ledger day is the same check
    rep = replay.replay(prices, str(day.date()), str(day.date()))
    _compare(rep, led[led["date"] == day], ["change_risk_5d", "anomaly_pct"], tol=1e-9)


@needs_artifacts
def test_replay_truncation_invariance(prices: pd.DataFrame) -> None:
    """Replaying a shorter window must reproduce the longer window's overlapping rows exactly — the
    row for day t never depends on what the window ends on. (Trailing 600-row warm-up for speed.)"""
    short = replay.replay(prices, "2020-03-09", "2020-03-10", warmup_days=600)
    longer = replay.replay(prices, "2020-03-09", "2020-03-12", warmup_days=600)
    overlap = longer.merge(short[["date", "pair"]], on=["date", "pair"])
    cmp_cols = [c for c in replay.REPLAY_COLUMNS if c != "top_drivers"]
    pd.testing.assert_frame_equal(
        overlap[cmp_cols].reset_index(drop=True), short[cmp_cols].reset_index(drop=True)
    )
    assert len(longer) == 12 and len(short) == 6


@needs_artifacts
def test_warmup_window_is_float_drift_only(prices: pd.DataFrame, regimes: pd.DataFrame) -> None:
    """A trailing 600-row warm-up agrees with the full-history artifact to ~1e-13 on the core
    columns (pandas' online rolling std and the forward filter's prior carry float state; a
    look-ahead would be O(1e-3)). The flagship replays use the exact full history."""
    rep = replay.replay(prices, "2020-03-10", "2020-03-11", warmup_days=600)
    _compare(rep, regimes, CORE, tol=1e-9)


# --------------------------------------------------------------------------------------
# windows fixed in advance; storyline + narrative from synthetic rows
# --------------------------------------------------------------------------------------
def test_windows_fixed_in_advance() -> None:
    assert list(replay.WINDOWS) == ["covid_2020", "credit_suisse_2023", "snb_2015"]
    w = replay.WINDOWS
    assert (w["covid_2020"]["pair"], w["covid_2020"]["start"], w["covid_2020"]["end"]) == (
        "EURUSD",
        "2020-02-03",
        "2020-04-30",
    )
    assert (w["credit_suisse_2023"]["pair"], w["credit_suisse_2023"]["start"]) == (
        "USDCHF",
        "2023-03-01",
    )
    assert (w["snb_2015"]["pair"], w["snb_2015"]["start"], w["snb_2015"]["end"]) == (
        "USDCHF",
        "2015-01-05",
        "2015-01-30",
    )
    assert "fixed in advance" in replay.SELECTION_RULE


def _rows(regimes: list[str], risk: list[float], siren: list[float], pair="USDCHF") -> pd.DataFrame:
    n = len(regimes)
    df = pd.DataFrame(
        {
            "date": pd.bdate_range("2021-01-04", periods=n),
            "pair": pair,
            "regime": regimes,
            "regime_prob": 0.9,
            "change_risk_5d": risk,
            "anomaly_pct": siren,
        }
    )
    for c in replay.REPLAY_COLUMNS:
        if c not in df.columns:
            df[c] = None if c in ("consensus_text", "top_drivers") else np.nan
    return df[replay.REPLAY_COLUMNS]


def test_storyline_moments() -> None:
    rows = _rows(
        ["calm", "calm", "calm", "crisis", "crisis", "trend"],
        [0.10, 0.25, 0.30, 0.05, 0.05, 0.05],
        [50, 60, 99, 100, 90, 40],
    )
    s = replay.storyline(rows, thr=0.22)
    assert s["first_alarm"] == "2021-01-05" and s["first_crisis"] == "2021-01-07"
    assert s["alarm_to_flip_days"] == 2 and s["n_alarm_days"] == 2
    assert s["peak_siren"] == "2021-01-07" and s["peak_siren_pct"] == 100.0
    assert s["n_crisis_days"] == 2 and s["longest_crisis_run"] == 2
    assert s["last_crisis"] == "2021-01-08" and s["regime_end"] == "trend"
    assert s["pre_crisis_max_risk"] == 0.30 and s["n_loud_days"] == 2


def test_storyline_no_warning_is_reported_as_such() -> None:
    """A flip with no prior alarm must say so (negative lag), never be dressed up."""
    rows = _rows(["calm", "calm", "crisis", "crisis"], [0.05, 0.05, 0.05, 0.40], [10, 10, 100, 100])
    s = replay.storyline(rows, thr=0.22)
    assert s["first_alarm"] == "2021-01-07" and s["first_crisis"] == "2021-01-06"
    assert s["alarm_to_flip_days"] == -1
    text = replay.narrative(s)
    assert "AFTER the regime flip" in text["alarm"]
    rows2 = _rows(["calm"] * 4, [0.05] * 4, [10] * 4)
    s2 = replay.storyline(rows2, thr=0.22)
    assert s2["first_alarm"] is None and s2["first_crisis"] is None
    assert "never reached" in replay.narrative(s2)["alarm"]


def test_narrative_and_sidebar_have_no_direction_words() -> None:
    rows = _rows(
        ["calm", "calm", "crisis", "crisis", "chop"],
        [0.10, 0.25, 0.05, 0.05, 0.05],
        [50, 99, 100, 90, 40],
    )
    s = replay.storyline(rows, thr=0.22)
    for window in replay.WINDOWS.values():
        for part in replay.narrative(s, window).values():
            assert not DIRECTION_WORDS.search(part), part
    md = replay.report_markdown(
        "snb_2015", replay.WINDOWS["snb_2015"], rows, 0.22, "2026-08-17", "x.png"
    )
    assert not DIRECTION_WORDS.search(replay.SNB_SIDEBAR), DIRECTION_WORDS.search(
        replay.SNB_SIDEBAR
    )
    assert "What the radar did\nNOT do: warn." in md  # the honest sidebar is in report C
    assert "Causal reconstruction — not the live record" in md
    assert "fixed in advance" in md and config.DISCLAIMER in md
    assert "| 2021-01-06 | crisis |" in md


def test_json_round_trip() -> None:
    rows = _rows(["calm", "crisis"], [0.1, 0.3], [50, 100])
    rows["top_drivers"] = [["vol_20", "hmm_entropy", "rng_hl"], None]
    payload = {"rows": replay._json_rows(rows)}
    text = json.dumps(payload)  # must be JSON-serialisable (no NaN, no numpy types)
    back = replay.rows_from_json(json.loads(text))
    assert list(back.columns) == replay.REPLAY_COLUMNS
    assert back["date"].tolist() == rows["date"].tolist()
    assert back.loc[0, "top_drivers"] == ["vol_20", "hmm_entropy", "rng_hl"]
    assert back["risk_lo"].isna().all()
    np.testing.assert_allclose(back["change_risk_5d"], rows["change_risk_5d"])


# --------------------------------------------------------------------------------------
# auto post-mortem stage (synthetic ctx)
# --------------------------------------------------------------------------------------
def _ctx(last_two: dict[str, tuple[str, str]]) -> dict:
    frames = []
    for pair, (prev, last) in last_two.items():
        n = 40
        reg = ["calm"] * (n - 2) + [prev, last]
        frames.append(
            pd.DataFrame(
                {
                    "date": pd.bdate_range("2026-01-05", periods=n),
                    "pair": pair,
                    "regime": reg,
                    "regime_prob": 0.95,
                    "change_risk_5d": np.linspace(0.05, 0.4, n),
                    "anomaly_pct": np.linspace(20, 100, n),
                    "model_version": "hmm=0.4.0|fc=1.1.0|siren=1.2.0",
                }
            )
        )
    return {"regimes": pd.concat(frames, ignore_index=True), "forecaster_meta": {"threshold": 0.22}}


def test_stage_drafts_on_live_entry_into_crisis(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(replay, "POSTMORTEM_DIR", tmp_path)
    ctx = _ctx(
        {"EURUSD": ("calm", "calm"), "USDCHF": ("chop", "crisis"), "GBPUSD": ("crisis", "crisis")}
    )
    replay.stage(ctx)
    assert [p.name for p in ctx["postmortems"]] == ["2026-02-27_USDCHF.md"]
    writers = ctx["extra_writers"]
    assert len(writers) == 1
    next(iter(writers.values()))(ctx)
    text = (tmp_path / "2026-02-27_USDCHF.md").read_text()
    assert text.startswith("# DRAFT — for human review")
    assert "entered crisis on 2026-02-27" in text and config.DISCLAIMER in text
    assert text.count("| 2026-") == replay.POSTMORTEM_DAYS  # last 30 live rows
    assert not DIRECTION_WORDS.search(text.split("## Day by day")[0].split("## The numbers")[1])


def test_stage_writes_nothing_without_entry(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(replay, "POSTMORTEM_DIR", tmp_path)
    ctx = _ctx({"EURUSD": ("crisis", "crisis"), "USDCHF": ("crisis", "calm")})  # exit, not entry
    replay.stage(ctx)
    assert ctx["postmortems"] == [] and "extra_writers" not in ctx
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------------------
# the Storms page reads artifacts only
# --------------------------------------------------------------------------------------
@needs_artifacts
def test_storms_page_renders_banner_selection_rule_and_disclaimer() -> None:
    if not replay.REPLAYS_PATH.exists():
        pytest.skip("no storm_replays.json yet — run python -m fxradar.replay")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(config.ROOT / "app/views/storms.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    txt = " ".join(m.value for m in at.markdown)
    assert "Causal reconstruction — not the live record" in txt and "fixed in advance" in txt
    assert config.DISCLAIMER in txt and len(at.get("plotly_chart")) == 1
    at.radio[0].set_value("snb_2015").run()
    assert not at.exception, at.exception
    txt = " ".join(m.value for m in at.markdown)
    assert "pegged EUR/CHF" in txt and "NOT do" in txt  # report C's honest sidebar is on the page
