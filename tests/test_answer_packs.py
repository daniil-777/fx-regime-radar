"""Phase 40 — precomputed answers, the cube, and the classifier's honesty.

The failures worth testing here are the ones that would be invisible in production. A pack served
under superseded gate rules looks exactly like a fresh one. A classifier trained on its own eval set
reports a beautiful number and hides every real failure. Both would ship happily.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from fxradar import answer_packs as AP  # noqa: E402

PACKS = ROOT / "data" / "answer_packs.json"
ROLLUPS = ROOT / "data" / "rollups.parquet"
pytestmark = pytest.mark.skipif(not PACKS.exists(), reason="packs not built yet")


@pytest.fixture(scope="module")
def built() -> dict:
    return json.loads(PACKS.read_text())


# ------------------------------------------------------------------- the packs -----------------
def test_packs_carry_both_speech_variants(built: dict) -> None:
    """A follow-up answered with the standalone sentence is what makes a voice product sound like a
    kiosk: "USD/CHF is calm today" after you just asked about EUR/USD repeats what you already know.
    """
    for key, pack in built["packs"].items():
        assert pack["speech"]["standalone"].strip(), f"{key}: no standalone speech"
        assert pack["speech"]["followup"].strip(), f"{key}: no follow-up variant"
        assert pack["speech"]["followup"] != pack["speech"]["standalone"], f"{key}: identical"


def test_no_pack_exists_for_a_user_supplied_quantity(built: dict) -> None:
    """An exposure or a hypothetical move does not exist until somebody speaks, so a pack claiming
    to answer one would be answering an invented question."""
    excluded = set(AP.load_intents()["excluded_from_precompute"])
    for key, pack in built["packs"].items():
        assert pack["card"] not in excluded, f"{key}: precomputed a card needing user input"


def test_every_pack_carries_provenance(built: dict) -> None:
    for key, pack in built["packs"].items():
        assert pack["provenance"], f"{key}: no provenance record"
        for record in pack["provenance"]:
            assert record.get("artifact"), f"{key}: provenance without an artifact"
            assert record.get("as_of"), f"{key}: provenance without an as-of date"


def test_gates_ran_at_build_time(built: dict) -> None:
    """The blocked list is the evidence. A build that blocked nothing has either perfect content or
    a gate that is not running — and only one of those is likely."""
    assert "blocked" in built, "no record of what the build-time gates rejected"
    manifest = built["manifest"]
    assert manifest["n_blocked_by_gates"] == len(built["blocked"])


@pytest.mark.parametrize(
    "field",
    [
        "context_version",
        "intent_version",
        "registry_version",
        "prompt_version",
        "gate_rules_version",
        "model_id_and_version",
        "voice_id",
    ],
)
def test_a_change_to_any_pinned_field_invalidates_every_pack(built: dict, field: str) -> None:
    """Serving a pack gated under superseded rules is indistinguishable from serving a fresh one —
    which is exactly why it needs a test rather than a convention."""
    manifest = dict(built["manifest"])
    current = {
        "context_version": manifest["context_version"],
        "intent_version": manifest["intent_version"],
        "registry_version": manifest["registry_version"],
    }
    ok, reasons = AP.manifest_is_current(manifest, **current)
    assert ok, f"a freshly built manifest should be current, got {reasons}"

    manifest[field] = "something-else"
    ok, reasons = AP.manifest_is_current(manifest, **current)
    assert not ok and any(field in r for r in reasons), f"{field} change was not detected"


def test_stale_packs_are_detectable_rather_than_silent(built: dict) -> None:
    """The nightly build fails at 06:00. At 09:00 a user should still get an answer — yesterday's,
    clearly labelled. Silence would be worse, and so would a stale number wearing today's date."""
    manifest = dict(built["manifest"])
    ok, reasons = AP.manifest_is_current(
        manifest,
        context_version="2099-01-01",
        intent_version=manifest["intent_version"],
        registry_version=manifest["registry_version"],
    )
    assert not ok
    assert any("context_version" in r for r in reasons)


def test_german_and_french_packs_are_actually_localised(built: dict) -> None:
    """A German pack that says "change risk" with a comma decimal is not localised, it is confusing:
    neither an English speaker nor a German one reads it comfortably."""
    de = [
        p for p in built["packs"].values() if p["locale"] == "de" and p["card"] == "condition_card"
    ]
    assert de, "no German condition packs were built"
    text = de[0]["speech"]["standalone"]
    assert "Änderungsrisiko" in text, f"German pack still says it in English: {text}"
    assert "0," in text, f"German pack should use a decimal comma: {text}"


# ------------------------------------------------------------------ the classifier -------------
def test_training_and_eval_are_disjoint() -> None:
    """Training a router on the eval set makes the reported accuracy a memorisation score AND hides
    the failures the eval exists to surface. Both halves of that sentence matter."""
    from fxradar import intent_model as IM  # noqa: PLC0415

    corpus = IM.build_corpus()
    train_questions = {r["text"].strip().lower() for r in corpus}
    golden = IM.golden_questions()
    overlap = train_questions & golden
    assert not overlap, f"{len(overlap)} golden questions leaked into training: {list(overlap)[:5]}"


def test_low_confidence_never_selects_a_pack() -> None:
    from fxradar import intent_model as IM  # noqa: PLC0415

    model_path = ROOT / "models" / "intent_clf_v1.pkl"
    if not model_path.exists():
        pytest.skip("classifier not trained yet")
    model = IM.load(model_path)
    intent, p = model.confident("asdfghjkl qwertyuiop zxcvbnm")
    assert p < 1.0
    if p < model.threshold:
        assert intent is None, "a low-confidence classification must not select a pack"


# ------------------------------------------------------------------- the cube ------------------
@pytest.mark.skipif(not ROLLUPS.exists(), reason="cube not built yet")
def test_cube_covers_its_documented_shapes() -> None:
    import pandas as pd  # noqa: PLC0415

    from fxradar import rollups as R  # noqa: PLC0415

    cube = pd.read_parquet(ROLLUPS)
    present = set(cube["rollup"].unique())
    documented = set(R.DEFINITIONS)
    missing = documented - present
    assert not missing, f"documented shapes with no rows: {missing}"
    assert not (present - documented), "the cube has rows nobody documented"
    assert "definition_version" in cube.columns, "a cube row must name the recipe that produced it"


@pytest.mark.skipif(not ROLLUPS.exists(), reason="cube not built yet")
def test_cube_agrees_with_a_live_scan_on_a_shared_range() -> None:
    """The cube is only useful if it is the same answer, faster."""
    import pandas as pd  # noqa: PLC0415

    cube = pd.read_parquet(ROLLUPS)
    regimes = pd.read_parquet(ROOT / "data" / "regimes.parquet")
    regimes["month"] = pd.to_datetime(regimes["date"]).dt.to_period("M").astype(str)
    monthly = cube[cube["rollup"] == "regime_month"]
    sample = monthly.dropna(subset=["days"]).head(20)
    for row in sample.itertuples():
        live = len(
            regimes[
                (regimes["pair"] == row.pair)
                & (regimes["month"] == row.month)
                & (regimes["regime"] == row.regime)
            ]
        )
        assert (
            int(row.days) == live
        ), f"cube says {row.days} days for {row.pair} {row.month} {row.regime}, live scan says {live}"
