"""`public/state.json` goes on a CDN, so what it may not contain is a test, not a habit.

The whole point of an allow-list build is that a field added to the context pack next year does not
publish itself. These tests are the other half of that: they check the built artifact rather than
the builder, so a future change that routes around `PAIR_FIELDS` still fails here.
"""

from __future__ import annotations

import json
import re

import pytest

from fxradar import public_state as ps

# Things that must never be on a public CDN. Written as substrings of the SERIALISED file, so a
# leak nested six levels deep is caught exactly like a top-level one.
FORBIDDEN_SUBSTRINGS = [
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "ANTHROPIC",
    "ELEVENLABS",
    "ANAM",
    "HEYGEN",
    "STRIPE",
    "/Users/",
    "/home/",
    "C:\\",
    ".venv",
    "allowed_numbers",  # the grounding gate's configuration
    "refusals",  # our refusal copy is product surface, not public data
    "knowledge_pack",
    "system_prompt",
    "faq",
]


@pytest.fixture(scope="module")
def pack() -> dict:
    from fxradar import config

    return json.loads((config.DATA_DIR / "avatar_context.json").read_text())


@pytest.fixture(scope="module")
def state(pack: dict) -> dict:
    return ps.build(pack)


@pytest.fixture(scope="module")
def body(state: dict) -> str:
    return json.dumps(state, separators=(",", ":"), sort_keys=True)


def test_nothing_secret_or_internal_is_published(body: str) -> None:
    low = body.lower()
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle.lower() not in low, f"public/state.json contains {needle!r}"


def test_no_absolute_path_or_key_shaped_string(body: str) -> None:
    """A long opaque string in a public file is either a key or a mistake; both need looking at."""
    for value in re.findall(r'"([A-Za-z0-9+/=_-]{32,})"', body):
        pytest.fail(f"a {len(value)}-character opaque string is published: {value[:16]}…")


def test_no_personal_data(body: str) -> None:
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", body), "an e-mail address is published"
    assert "session" not in body.lower(), "a session identifier is published"


def test_the_research_lab_does_not_leak(state: dict) -> None:
    """The lab holds unfrozen, unvalidated numbers. Publishing one would put a research artefact
    beside the frozen record with nothing to tell a reader which is which."""
    for key in ("model_lab", "challenger", "strategy", "backtest", "lab", "experiment"):
        assert key not in state, f"{key!r} is research output and must not be published"


def test_it_fits_in_one_fetch(state: dict, tmp_path) -> None:
    size = ps.write(state, tmp_path / "state.json")
    assert size <= ps.MAX_BYTES
    # The cap is 50 KB; if the real artifact ever gets close, that is worth knowing before it fails.
    assert (
        size < ps.MAX_BYTES * 0.8
    ), f"state.json is {size} bytes, within 20% of the cap — trim a field before the build breaks"


def test_the_cap_is_enforced_not_advisory(tmp_path) -> None:
    fat = {"schema_version": "1.0.0", "junk": "x" * (ps.MAX_BYTES + 10)}
    with pytest.raises(ValueError, match="over the"):
        ps.write(fat, tmp_path / "state.json")


def test_every_page_can_render_from_this_file_alone(state: dict) -> None:
    """One fetch is the design. If a page needs a second file the budget is already lost."""
    assert state["markets"], "Overview and Pairs need the market blocks"
    assert state["ledger"]["chain_head_short"], "Proof needs the chain head"
    assert "model_stale" in state["drift"], "the stale badge needs the drift flag"
    assert state["disclaimer"], "rule 7: every user-facing surface carries the disclaimer"
    assert state["context_version"], "cache headers are keyed to this"
    for uni in state["markets"].values():
        for code, blk in uni["pairs"].items():
            assert blk.get("regime"), f"{code} has no regime word"


def test_degenerate_values_are_null_not_zero(state: dict) -> None:
    """A live Brier of 0.0 would read as a perfect score; it means 'nothing has resolved yet'."""
    led = state["ledger"]
    if led.get("n_resolved") == 0:
        assert led.get("live_brier") is None, "an unresolved ledger must report null, never 0"


def test_the_artifact_is_byte_stable_for_the_same_input(pack: dict, tmp_path) -> None:
    """Cache headers are keyed to context_version, so the same context must produce the same bytes
    apart from the generation stamp — otherwise every rebuild busts a cache that did not need it."""
    a = ps.build(pack)
    b = ps.build(pack)
    a.pop("generated_at")
    b.pop("generated_at")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
