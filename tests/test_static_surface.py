"""The static customer surface (phase 44).

`scripts/check_budgets.py` is the CI gate over the built output. These tests cover the things a
byte-and-structure gate cannot see: that the builder escapes what it renders, that a missing or
partial artifact produces a designed state rather than a traceback, and that the two surfaces cannot
drift apart on colour.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_static", ROOT / "scripts/build_static.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_static"] = mod
    spec.loader.exec_module(mod)
    return mod


bs = _load_builder()


@pytest.fixture
def state() -> dict:
    from fxradar import config
    from fxradar import public_state as ps

    pack = json.loads((config.DATA_DIR / "avatar_context.json").read_text())
    return ps.build(pack)


def test_markup_from_the_artifact_is_escaped(state: dict) -> None:
    """Everything rendered comes from an artifact this repo writes, so injection is not the threat —
    a pair label containing an ampersand is. Broken markup on the customer surface is the failure.
    """
    hostile = json.loads(json.dumps(state))
    uni = next(iter(hostile["markets"].values()))
    code = next(iter(uni["pairs"]))
    uni["pairs"][code]["label"] = '<script>alert("x")</script> & "quoted"'
    html = bs.page_overview(hostile)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_a_missing_treasury_block_renders_a_designed_state(state: dict) -> None:
    """Empty is a first-class state: say what happened and what to do, never a blank panel."""
    without = dict(state, treasury={})
    html = bs.page_treasury(without)
    assert "No treasury reading published today" in html
    assert "did not finish" in html
    assert "Educational tool. Not investment advice." in html


def test_a_pair_with_missing_numbers_shows_a_dash_not_a_zero(state: dict) -> None:
    """A change risk of 0.00 and a change risk we do not have are different facts, and the second
    one must never be rendered as the first."""
    partial = json.loads(json.dumps(state))
    uni = next(iter(partial["markets"].values()))
    code = next(iter(uni["pairs"]))
    uni["pairs"][code] = {"label": "TEST", "regime": "calm"}
    html = bs.page_pairs(partial)
    assert "—" in html
    row = html.split("TEST", 1)[1][:600]
    assert "0.00" not in row, "a missing number was rendered as zero"


def test_an_unknown_regime_does_not_break_the_page(state: dict) -> None:
    odd = json.loads(json.dumps(state))
    uni = next(iter(odd["markets"].values()))
    code = next(iter(uni["pairs"]))
    uni["pairs"][code]["regime"] = "unheard_of"
    html = bs.page_overview(odd)
    assert "unheard_of" in html
    assert "Educational tool" in html


def test_every_page_carries_the_disclaimer_and_the_no_direction_statement(state: dict) -> None:
    for build in (bs.page_overview, bs.page_pairs, bs.page_treasury, bs.page_storms, bs.page_proof):
        html = build(state)
        assert "Educational tool. Not investment advice." in html
        assert "no price direction" in html, f"{build.__name__} omits the rule-5 statement"


def test_no_colour_is_written_by_hand(state: dict) -> None:
    """Both surfaces consume `design/tokens.json`; the moment one carries its own hex they drift.

    The generated CSS naturally contains hex values — that is the point of generating it. What must
    not happen is a literal appearing anywhere other than through the token module.
    """
    from fxradar import tokens as tk

    css = bs.stylesheet()
    allowed = set()
    for group in ("surface", "text", "accent"):
        allowed |= {v for v in tk.TOKENS[group].values() if isinstance(v, str)}
    allowed |= set(tk.REGIME_COLORS.values())
    import re

    for found in re.findall(r"#[0-9A-Fa-f]{6}", css):
        assert any(
            found.lower() == a.lower() for a in allowed
        ), f"{found} is in the stylesheet but not in design/tokens.json"


def test_the_treasury_page_refuses_to_read_as_advice(state: dict) -> None:
    """Rule 5 and rule 7 apply hardest here: a traffic light is the surface most easily mistaken
    for a recommendation, so the page says what it is not, on the page, not in a footnote."""
    html = bs.page_treasury(state)
    assert "not a view on where the rate will go" in html
    assert "not a recommendation" in html
    assert "licensed adviser" in html


def test_proof_reports_an_unresolved_ledger_honestly(state: dict) -> None:
    empty = json.loads(json.dumps(state))
    empty["ledger"]["n_resolved"] = 0
    empty["ledger"]["live_brier"] = None
    html = bs.page_proof(empty)
    assert "not yet" in html
    assert "would mean a perfect score" in html


def test_the_service_worker_is_keyed_to_the_context_version() -> None:
    a = bs.service_worker("2026-08-20")
    b = bs.service_worker("2026-08-21")
    assert a != b, "a new day's build must not be served from yesterday's cache"
    assert "2026-08-20" in a
    assert "caches.delete" in a


def test_the_manifest_is_valid_json_and_installable() -> None:
    m = json.loads(bs.manifest())
    assert m["display"] == "standalone"
    assert m["start_url"].endswith("index.html")
    assert any("maskable" in (i.get("purpose") or "") for i in m["icons"])
    assert "Not investment advice" in m["description"]
