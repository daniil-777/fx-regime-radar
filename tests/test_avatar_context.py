"""Phase 35 — the avatar's mind: parity with source artifacts, lint on every spoken template,
grounding set covers everything the greeting says, FAQ parser, canonical number form."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from fxradar import avatar_context as ac
from fxradar import config, narrate

ROOT = Path(__file__).resolve().parents[1]


def _pack():
    regimes = pd.read_parquet(config.REGIMES_PATH)
    knowledge = ac.KNOWLEDGE_PATH.read_text()
    return ac.build_pack(
        regimes,
        ac._read_events(),
        json.loads((config.DATA_DIR / "treasury_risk.json").read_text()),
        json.loads((config.DATA_DIR / "live_record.json").read_text()),
        json.loads((config.DATA_DIR / "conformal_coverage.json").read_text()),
        json.loads((config.DATA_DIR / "status.json").read_text()),
        knowledge,
        now_utc="2026-08-20T00:00:00Z",
    )


def test_parity_with_source_artifacts() -> None:
    """Every number in the pack equals the artifact it came from — the mind never paraphrases."""
    pack = _pack()
    regimes = pd.read_parquet(config.REGIMES_PATH)
    latest = regimes.sort_values("date").groupby("pair").tail(1).set_index("pair")
    for pair, blk in pack["pairs"].items():
        row = latest.loc[pair]
        assert blk["regime"] == row["regime"]
        assert blk["change_risk_5d"] == round(float(row["change_risk_5d"]), 2)
        assert blk["anomaly_pct"] == round(float(row["anomaly_pct"]), 0)
        assert blk["risk_hi"] == round(float(row["risk_hi"]), 2)
        assert blk["days_in_regime"] == int(row["days_in_regime"])
    live = json.loads((config.DATA_DIR / "live_record.json").read_text())
    assert pack["ledger"]["frozen_brier"] == round(live["frozen_test"]["brier"], 3)
    assert pack["ledger"]["days_live"] == live["days_recorded"]
    assert pack["ledger"]["chain_head_short"] == live["head_hash"][:8]
    assert pack["data_through"] == f"{regimes['date'].max():%Y-%m-%d}"


def test_every_spoken_template_passes_the_direction_lint() -> None:
    pack = _pack()
    for text in [pack["greeting"], pack["disclosure"], *pack["refusals"].values()]:
        assert narrate.check_narration(text)
    for f in pack["faq"]:
        assert narrate.check_narration(f["answer"]), f["q"]


def test_greeting_numbers_are_all_in_the_allowed_set() -> None:
    """The grounding gate must never block our own greeting."""
    pack = _pack()
    allowed = set(pack["allowed_numbers"])
    for tok in re.findall(r"\d+(?:\.\d+)?", pack["greeting"]):
        assert ac.canon(tok) in allowed, tok


def test_canonical_number_form_matches_the_gate_contract() -> None:
    assert ac.canon("0.010") == "0.01"
    assert ac.canon(73.0) == "73"
    assert ac.canon("91.60") == "91.6"
    assert ac.canon(0) == "0"


def test_faq_parser_extracts_all_questions_with_keywords() -> None:
    faq = ac.parse_faq(ac.KNOWLEDGE_PATH.read_text())
    assert len(faq) >= 12
    by_q = {f["q"]: f for f in faq}
    siren = next(f for q, f in by_q.items() if "siren" in q.lower())
    assert "siren" in siren["keywords"] and "autoencoder" in siren["answer"]
    assert all(f["answer"] for f in faq)


def test_fabricated_number_would_fail_the_grounding_contract() -> None:
    """Mirror of the rust gate: a number absent from the pack is not in allowed_numbers."""
    pack = _pack()
    allowed = set(pack["allowed_numbers"])
    assert ac.canon("0.4242") not in allowed
    assert ac.canon("777") not in allowed


def test_pack_refuses_to_build_with_a_direction_word_in_a_template(monkeypatch) -> None:
    monkeypatch.setitem(ac.REFUSALS, "direction", "The price will rise soon.")
    with pytest.raises(RuntimeError):
        _pack()
