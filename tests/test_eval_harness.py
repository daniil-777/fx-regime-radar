"""Phase 39 — the measuring stick must itself be trustworthy.

The failures these guard against are quiet ones. An eval that reads `data/` looks healthy until the
morning it disagrees with yesterday for no reason anybody can reconstruct. A hand-typed gold value
looks healthy until the pipeline moves and the suite starts failing a system that is right. Both
produce the same symptom — a red suite — and neither points at the cause, so each is worth a test
that names it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

import harness as H  # noqa: E402

EVAL_DIR = ROOT / "eval"
GOLDEN = EVAL_DIR / "golden.yaml"
pytestmark = pytest.mark.skipif(not GOLDEN.exists(), reason="golden set not seeded yet")


@pytest.fixture(scope="module")
def snap() -> H.Snapshot:
    return H.load_snapshot()


@pytest.fixture(scope="module")
def items(snap: H.Snapshot) -> list[H.GoldItem]:
    return H.load_golden(snap)


# ------------------------------------------------------------------ the snapshot ---------------
def test_snapshot_matches_its_own_manifest(snap: H.Snapshot) -> None:
    """A snapshot that has drifted from its hashes is not a snapshot."""
    from eval.build_snapshot import sha256  # noqa: PLC0415

    for rel, expected in snap.manifest.items():
        path = snap.path / rel
        assert path.exists(), f"{rel} listed in the manifest but missing"
        assert sha256(path) == expected, f"{rel} has changed since the snapshot was built"


def test_no_eval_path_reads_live_data() -> None:
    """Every eval run must read the snapshot. Reading `data/` re-introduces the drift the whole
    apparatus exists to remove — and the resulting flakiness is indistinguishable from a
    regression, which is what makes it expensive."""
    offenders = []
    for py in EVAL_DIR.glob("*.py"):
        if py.name == "build_snapshot.py":
            continue  # the one file whose job is to copy OUT of data/
        for n, line in enumerate(py.read_text().splitlines(), 1):
            # Only the REPO's data/ is forbidden. `snap.path / "data" / ...` is the snapshot's own
            # data directory and is exactly what eval code should be reading.
            if re.search(r"""ROOT\s*/\s*['"]data['"]|["']data/[a-z]""", line):
                if line.strip().startswith("#"):
                    continue
                offenders.append(f"{py.name}:{n}: {line.strip()}")
    assert not offenders, "eval code reaching for live data:\n" + "\n".join(offenders)


# ------------------------------------------------------------------ computed gold --------------
def test_every_source_ref_resolves(snap: H.Snapshot, items: list[H.GoldItem]) -> None:
    """The build gate: an unresolvable reference fails HERE, where it costs a minute, instead of
    surfacing later as a model failure, where it costs an afternoon."""
    for item in items:
        for gv in item.gold_values:
            assert gv["name"] in item.resolved, f"{item.id}: {gv['source_ref']} did not resolve"


def test_a_broken_source_ref_fails_loudly(snap: H.Snapshot, tmp_path: Path) -> None:
    """Proof the gate works: point one item at a field that does not exist."""
    doc = yaml.safe_load(GOLDEN.read_text())
    victim = next((i for i in doc["items"] if i.get("gold_values")), None)
    if victim is None:
        pytest.skip("no item carries a gold value yet")
    victim = dict(victim)
    victim["gold_values"] = [{"name": "bogus", "source_ref": "pack:pairs.EURUSD.sharpe_ratio"}]
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump({"items": [victim]}, allow_unicode=True))
    with pytest.raises(H.SnapshotError, match="not found in the snapshot"):
        H.load_golden(snap, broken)


def test_no_hand_typed_numeric_expectations() -> None:
    """Gold values carry a source_ref and nothing else. A literal `value:` key would mean somebody
    typed a number, which is the practice this phase exists to end."""
    doc = yaml.safe_load(GOLDEN.read_text())
    for item in doc["items"]:
        for gv in item.get("gold_values") or []:
            assert "source_ref" in gv, f"{item['id']}: gold value without a source_ref"
            assert "value" not in gv, f"{item['id']}: hand-typed value — use a source_ref"


# ------------------------------------------------------------------ set composition ------------
def test_family_minimums(items: list[H.GoldItem]) -> None:
    counts: dict[str, int] = {}
    for it in items:
        counts[it.family] = counts.get(it.family, 0) + 1
    short = {f: (counts.get(f, 0), n) for f, n in H.FAMILY_MINIMUMS.items() if counts.get(f, 0) < n}
    assert not short, f"families below minimum (have, need): {short}"
    assert 180 <= len(items) <= 400, f"golden set is {len(items)} items"


def test_a_quarter_of_the_set_is_not_english(items: list[H.GoldItem]) -> None:
    """A German or French treasurer is not a translation of an English one: decimal commas,
    compound nouns and different question shapes are where locale bugs actually live."""
    non_en = [i for i in items if i.locale != "en"]
    assert len(non_en) / len(items) >= 0.25, f"only {len(non_en)}/{len(items)} non-English"
    joined = " ".join(i.question for i in non_en)
    assert re.search(r"\d,\d", joined), "no decimal-comma case in the German/French items"
    assert re.search(r"\b\w{12,}\b", joined), "no German compound noun in the non-English items"


def test_every_built_card_has_three_items(items: list[H.GoldItem]) -> None:
    from fxradar import visuals as V  # noqa: PLC0415

    reg = V.load_registry()
    counts: dict[str, int] = {}
    for it in items:
        if it.expected_primary_card:
            counts[it.expected_primary_card] = counts.get(it.expected_primary_card, 0) + 1
    resolvable = {
        c["component"]
        for c in __import__("json")
        .loads((ROOT / "data" / "visual_boards.json").read_text())["cards"]
        .values()
    }
    thin = {
        c.id: counts.get(c.id, 0)
        for c in reg.built()
        if c.id in resolvable and counts.get(c.id, 0) < 3
    }
    assert not thin, f"built cards with fewer than three golden items: {thin}"


def test_multi_turn_items_carry_their_prior_turn(items: list[H.GoldItem]) -> None:
    """An elliptical follow-up without its context is not a multi-turn test, it is a broken one."""
    for it in items:
        if it.family == "multi_turn_followup":
            assert it.turn_context, f"{it.id}: multi-turn item with no turn_context"
            assert len(it.question.split()) <= 12, f"{it.id}: follow-ups are short by nature"


def test_injection_items_expect_ordinary_handling(items: list[H.GoldItem]) -> None:
    """An injection attempt is ordinary text. Expecting a special mode would BUILD the very
    behaviour an attacker is fishing for — a system that reacts to being probed is a system whose
    reactions can be mapped."""
    for it in items:
        if it.family == "adversarial_injection":
            assert it.expected_route in H.ROUTES, f"{it.id}: unknown route"
            assert it.expected_route != "refuse_not_in_pack" or it.notes, f"{it.id}: unexplained"


# ------------------------------------------------------------------ locale arithmetic ----------
@pytest.mark.parametrize(
    ("value", "locale", "text", "expected"),
    [
        (0.03, "en", "change risk 0.03 today", True),
        (0.03, "de", "Änderungsrisiko 0,03 heute", True),
        (0.03, "fr", "risque 0,03", True),
        (0.03, "en", "change risk 0.04 today", False),
        (79.0, "en", "siren 79 of 100", True),
        ("calm", "en", "EUR/USD reads calm today", True),
        ("calm", "de", "das Regime ist chop", False),
    ],
)
def test_numbers_are_compared_in_the_asked_locale(value, locale, text, expected) -> None:
    assert H.number_matches(value, text, locale) is expected


def test_routes_are_from_the_known_set(items: list[H.GoldItem]) -> None:
    for it in items:
        assert it.expected_route in H.ROUTES, f"{it.id}: {it.expected_route}"
