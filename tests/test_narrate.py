"""Narrator tests (phase 09): template shape, missing-key safety, mocked client request contents."""

import json
import re
import sys
import types

import pandas as pd
import pytest

from fxradar import narrate

STATS = {
    "pair": "USDCHF",
    "date": "2015-01-16",
    "regime": "crisis",
    "regime_prob": 0.97,
    "days_in_regime": 1,
    "change_risk_5d": 0.44,
    "top_drivers": ["vol_ratio", "rng_hl", "hmm_entropy"],
    "anomaly_pct": 100.0,
    "nearest_neighbor_date": "2008-10-24",
    "ret_5d_pct": -14.2,
}


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def test_template_is_three_sentences_with_regime_and_risk() -> None:
    text = narrate.template_narrate(STATS)
    assert len(_sentences(text)) == 3
    assert "crisis" in text and "44%" in text and "97%" in text
    assert "2008-10-24" in text  # anomaly_pct > 90 -> nearest neighbour mentioned
    quiet = narrate.template_narrate({**STATS, "anomaly_pct": 40.0})
    assert "2008-10-24" not in quiet and len(_sentences(quiet)) == 3


def test_missing_key_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(narrate, "get_api_key", lambda: None)
    text, source = narrate.narrate_with_fallback(STATS)
    assert source == "template" and len(_sentences(text)) == 3


def test_api_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(narrate, "narrate", boom)
    text, source = narrate.narrate_with_fallback(STATS)
    assert source == "template" and "crisis" in text


def test_mocked_client_receives_system_prompt_and_only_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class _Block:
        type = "text"
        text = "One. Two. Three."

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(content=[_Block()])

    class _Client:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    text = narrate.narrate(STATS, api_key="test-key")
    assert text == "One. Two. Three."
    assert captured["system"] == narrate.SYSTEM_PROMPT
    assert (
        captured["model"] == narrate.MODEL
        and captured["temperature"] == 0.3
        and captured["max_tokens"] == 350
    )
    assert len(captured["messages"]) == 1 and captured["messages"][0]["role"] == "user"
    assert json.loads(captured["messages"][0]["content"]) == STATS  # only JSON-derived content
    assert captured["client_kwargs"]["max_retries"] == 2
    assert "test-key" not in text


def test_build_stats_uses_numbers_only(prices_sample: pd.DataFrame) -> None:
    regimes = pd.DataFrame(
        {
            "date": [pd.Timestamp("2015-12-31")],
            "pair": ["EURUSD"],
            "regime": ["chop"],
            "regime_prob": [0.8],
            "days_in_regime": [3],
            "change_risk_5d": [0.31],
            "top_drivers": [["vol_20", "mom_20", "rng_hl"]],
            "anomaly_pct": [95.5],
        }
    )
    detail = pd.DataFrame(
        {
            "date": [pd.Timestamp("2015-12-31")],
            "pair": ["EURUSD"],
            "nn_date": [pd.Timestamp("2010-05-06")],
        }
    )
    stats = narrate.build_stats("EURUSD", regimes, detail, prices_sample)
    assert (
        stats["regime"] == "chop"
        and stats["change_risk_5d"] == 0.31
        and stats["nearest_neighbor_date"] == "2010-05-06"
    )
    assert all(isinstance(v, (int, float, str, list)) or v is None for v in stats.values())
    report = narrate.build_report(["EURUSD"], regimes, detail, prices_sample)
    assert (
        set(report["EURUSD"]) >= {"text", "generated_at", "source"}
        and report["EURUSD"]["source"] == "template"
    )


def test_direction_words_in_llm_reply_are_rejected_and_template_used() -> None:
    """Rule 5 guard: a reply that talks direction is discarded; the template never does."""
    import pytest

    with pytest.raises(RuntimeError):
        narrate.check_narration("EUR/USD will rise sharply this week.")
    assert narrate.check_narration("EUR/USD is in a calm regime.") == "EUR/USD is in a calm regime."
    with pytest.raises(RuntimeError):
        narrate.check_narration("   ")
