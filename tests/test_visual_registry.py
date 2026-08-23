"""Phase 38 — the fifty-card registry: schema, retrieval, resolution, composition, flat prompt.

The three invariants worth naming, because each has been a real failure mode in systems like this:
  1. a `planned` entry can never be retrieved, resolved or rendered (documentation must not ship);
  2. the injected prompt slice does not grow with the registry (retrieval, not enumeration);
  3. every `built` entry resolves against a sample bundle — a card pointing at a field that no
     longer exists fails the build rather than a customer's question.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from fxradar import visuals as V

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden_visuals.yaml"
CARDS_JS = ROOT / "rust" / "fxradar-serve" / "static" / "cards.js"
WIDGET_CSS = ROOT / "rust" / "fxradar-serve" / "static" / "widget-tokens.css"


@pytest.fixture(scope="module")
def reg() -> V.Registry:
    return V.load_registry()


@pytest.fixture(scope="module")
def golden() -> list[dict]:
    return yaml.safe_load(GOLDEN.read_text())["questions"]


# --------------------------------------------------------------------------------- schema ------
def test_registry_holds_fifty_cards(reg: V.Registry) -> None:
    assert len(reg.cards) == 50
    tiers = {t: sum(1 for c in reg.cards.values() if c.tier == t) for t in (1, 2, 3)}
    # The catalog's per-card table gives 20/20/10; its summary line says 20/18/12 and contradicts
    # itself. The table is the data, so the table wins — recorded here so the choice is visible.
    assert tiers == {1: 20, 2: 20, 3: 10}, tiers
    assert all(c.status == "built" for c in reg.cards.values() if c.tier in (1, 2))
    assert all(c.status == "planned" for c in reg.cards.values() if c.tier == 3)


def test_every_entry_is_well_formed(reg: V.Registry) -> None:
    for card in reg.cards.values():
        assert card.primitive in V.PRIMITIVES, f"{card.id}: unknown primitive"
        assert card.family in V.FAMILIES, f"{card.id}: unknown family"
        assert card.caption.get("en"), f"{card.id}: no caption"
        assert card.aria.get("en"), f"{card.id}: no ARIA label"
        assert card.when_not, f"{card.id}: no when_not rule"
        assert card.owner_artifact, f"{card.id}: no owner_artifact"
        for locale in ("en", "de", "fr"):
            assert card.question_intents.get(locale), f"{card.id}: no {locale} intents"


def test_schema_contains_no_numeric_type_anywhere() -> None:
    """The model may never send a value. If a numeric type appears in the arg schema, it can."""
    raw = yaml.safe_load(V.REGISTRY_PATH.read_text())
    banned = {"number", "float", "int", "integer", "numeric", "decimal"}
    for card in raw["cards"]:
        for name, spec in (card.get("args") or {}).items():
            assert str(spec.get("type")).lower() not in banned, f"{card['id']}.{name} is numeric"


def test_captions_and_bindings_reference_declared_args(reg: V.Registry) -> None:
    for card in reg.cards.values():
        declared = set(card.args) | {"asof"}
        for template in list(card.bindings.values()) + [card.caption["en"], card.aria["en"]]:
            for ph in re.findall(r"\{(\w+)\}", template):
                if template in card.bindings.values():
                    assert ph in declared, f"{card.id}: binding uses undeclared arg {{{ph}}}"


# ------------------------------------------------------------------------------ planned --------
def test_planned_entries_are_invisible_to_retrieval(reg: V.Registry) -> None:
    planned = {c.id for c in reg.cards.values() if not c.built}
    assert planned, "expected some planned entries"
    for card in reg.cards.values():
        for phrase in card.intents():
            got = {c.id for c in reg.retrieve(phrase)}
            assert not (got & planned), f"planned card surfaced for {phrase!r}"


def test_planned_entry_cannot_resolve_or_join_a_board(reg: V.Registry) -> None:
    planned = next(c for c in reg.cards.values() if not c.built)
    with pytest.raises(V.RegistryError, match="planned"):
        V.resolve(planned, {}, {})
    with pytest.raises(V.RegistryError, match="planned"):
        V.validate_board([planned])


def test_golden_planned_questions_never_yield_their_card(
    reg: V.Registry, golden: list[dict]
) -> None:
    for row in [g for g in golden if g["family"] == "planned_blocked"]:
        got = {c.id for c in reg.retrieve(row["q"])}
        assert row["planned_id"] not in got, f"{row['q']!r} surfaced planned {row['planned_id']}"


# ---------------------------------------------------------------------------- retrieval --------
def _recall_at_k(reg: V.Registry, rows: list[dict], k: int = V.TOP_K) -> tuple[float, list[dict]]:
    hits, misses = 0, []
    for row in rows:
        got = [c.id for c in reg.retrieve(row["q"], k=k)]
        if row["expect"] in got:
            hits += 1
        else:
            misses.append({"q": row["q"], "expect": row["expect"], "got": got[:4]})
    return hits / max(1, len(rows)), misses


def test_recall_at_6_meets_the_gate(reg: V.Registry, golden: list[dict]) -> None:
    rows = [g for g in golden if g["family"] == "selection"]
    recall, misses = _recall_at_k(reg, rows)
    by_family: dict[str, list[int]] = {}
    for row in rows:
        fam = reg.cards[row["expect"]].family
        got = [c.id for c in reg.retrieve(row["q"])]
        by_family.setdefault(fam, []).append(1 if row["expect"] in got else 0)
    print("\nrecall@6 by family:")
    for fam, vals in sorted(by_family.items()):
        print(f"  {fam:9s} {sum(vals)}/{len(vals)} = {sum(vals)/len(vals):.0%}")
    print(f"  OVERALL   {recall:.1%} over {len(rows)} unseen paraphrases")
    if misses:
        print("misses:")
        for m in misses[:5]:
            print(f"  {m['q']!r} expected {m['expect']}, got {m['got']}")
    assert recall >= 0.98, f"recall@6 {recall:.1%} below the 98% gate; misses: {misses}"


def test_the_guard_cards_are_always_resolvable(reg: V.Registry) -> None:
    """The direction and advice guards PIN their card; retrieval never selects it.

    This test used to assert that a direction question surfaces `direction_evidence_card` in the
    candidate slice — which was measuring the wrong thing, and broke the moment BM25 changed the
    ranking, reporting a "safety regression" where none existed. What actually protects the user is
    that the guard fires first and that the card it pins can always be filled; the board-level
    guarantee (a direction question is offered that card and NOTHING else, never a chart) is
    asserted in `rust/.../tests/avatar.rs::direction_questions_get_only_the_evidence_card`.
    """
    boards = __import__("json").loads((ROOT / "data" / "visual_boards.json").read_text())
    resolvable = {c["component"] for c in boards["cards"].values()}
    for guard_card in ("direction_evidence_card", "ask_your_bank_card"):
        assert guard_card in reg.cards, f"{guard_card} is missing from the registry"
        assert reg.cards[guard_card].built, f"{guard_card} is not built"
        assert guard_card in resolvable, (
            f"{guard_card} has no resolved instance — the guard would pin a card it cannot fill, "
            f"and a refusal would arrive with an empty box beside it"
        )


# --------------------------------------------------------------------------- flat prompt -------
def _approx_tokens(text: str) -> float:
    """~4 characters per token: precise enough to prove the slice does not scale with the registry."""
    return len(text) / 4


def test_prompt_slice_does_not_grow_with_the_registry(reg: V.Registry) -> None:
    """Truncate the registry to 24 entries and measure the injected slice against the full 50."""
    questions = [
        "how does EURUSD look today",
        "how has risk moved",
        "hedge wait or ladder",
        "why should I trust you",
        "what is coming up",
        "how did covid look",
        "what does chop mean",
        "how bad is a bad week",
        "do the models agree",
        "is volatility rising",
    ]
    # 24 entries INCLUDING the two catch-alls: they are structural (always injected), so a
    # truncation that drops them compares six candidates against eight and overstates the growth.
    subset = {k: v for k, v in list(reg.cards.items())[:22]}
    for cid in V.CATCH_ALLS:
        subset[cid] = reg.cards[cid]
    small = V.Registry(version=reg.version, cards=subset)
    small.index()
    full_t = [_approx_tokens(V.prompt_slice(reg.retrieve(q))) for q in questions]
    small_t = [_approx_tokens(V.prompt_slice(small.retrieve(q))) for q in questions]
    mean_full, mean_small = sum(full_t) / len(full_t), sum(small_t) / len(small_t)
    print(
        f"\nregistry slice over {len(questions)} questions: "
        f"24 entries -> {mean_small:.0f} tok mean · 50 entries -> {mean_full:.0f} tok mean "
        f"({(mean_full - mean_small) / mean_small:+.1%})"
    )
    # The structural guarantee is the candidate COUNT: eight, whatever the registry holds. The
    # remaining token difference is which eight cards were retrieved (captions differ in length),
    # not how many entries exist — doubling the registry does not double the prompt.
    cap = V.TOP_K + len(V.CATCH_ALLS)
    for q in questions:
        # never more than eight candidates, at either registry size; the union can be seven when a
        # catch-all already ranks inside the top six, which is dedup working, not a shrunken slice.
        assert V.TOP_K <= len(reg.retrieve(q)) <= cap
        assert V.TOP_K <= len(small.retrieve(q)) <= cap
    assert abs(mean_full - mean_small) / mean_small < 0.25


# ---------------------------------------------------------------------------- resolution -------
def _sample_bundle() -> dict:
    """Minimal but complete: one value for every binding path every built card declares."""
    pairs = {
        p: {
            "regime": "calm",
            "regime_prob": 0.99,
            "days_in_regime": 12,
            "change_risk_5d": 0.02,
            "risk_lo": 0.0,
            "risk_hi": 0.51,
            "anomaly_pct": 71,
            "agreement": 1,
            "consensus_text": "1 of 3",
        }
        for p in ("EURUSD", "USDCHF", "GBPUSD")
    }
    tre = {
        p: {"light": "wait", "light_reason": "calm and quiet", "current_regime": "calm"}
        for p in pairs
    }
    dec = {
        p: {
            t: {
                "hedge_ratio": 0.25,
                "es_99_1w": 0.0267,
                "light": "wait",
                "schedule_by_horizon": {h: [] for h in ("1", "2", "4", "8", "12")},
            }
            for t in ("conservative", "balanced", "aggressive")
        }
        for p in pairs
    }
    series: dict = {}
    for p in pairs:
        for w in ("30d", "90d", "1y", "5y"):
            series.setdefault("risk", {}).setdefault(p, {})[w] = [{"v": 0.1, "lo": 0.0, "hi": 0.3}]
            series.setdefault("vol", {}).setdefault(p, {})[w] = [{"v": 0.06}]
            series.setdefault("regime", {}).setdefault(p, {})[w] = [{"label": "calm", "weight": 1}]
        series.setdefault("regime_probs", {})[p] = [{"label": "calm", "value": 0.9}]
        series.setdefault("delta", {})[p] = "+0.01"
        series.setdefault("anchor", {})[p] = {a: 0.05 for a in ("week", "month", "quarter", "year")}
        series.setdefault("cost_of_waiting", {})[p] = [{"v": 0.02}]
    series["coverage"] = [{"v": 0.916}]
    series["storm"] = {"covid_2020": [{"label": "crisis", "weight": 1}]}
    tables: dict = {
        "pair_compare": [["EURUSD", "calm", "0.02"]],
        "regime_history": {p: [["2020-03-01", "crisis", "34"]] for p in pairs},
        "var_es": {
            p: {
                m: [{"label": "calm", "value": 0.01}]
                for m in ("var_99", "var_95", "es_99", "es_95")
            }
            for p in pairs
        },
        "scenario": {p: [["-3%", "0.9"]] for p in pairs},
        "impact": {p: [{"label": "spot", "value": 1.0}] for p in pairs},
        "move_frequency": {
            p: {b: [{"label": "1pct", "value": 12}] for b in ("1pct", "2pct", "3pct", "5pct")}
            for p in pairs
        },
        "hedge_compare": {p: [["forward", "full", "0"]] for p in pairs},
        "ledger_row": {"2026-08-19": [["date", "2026-08-19"]]},
        "drivers": {p: [{"label": "vol_20", "value": 0.4}] for p in pairs},
        "cross_asset": [["SPX", "quiet"]],
        "event_study": {
            e: [{"label": "day 0", "value": 0.3}]
            for e in ("FOMC", "ECB", "SNB", "BOE", "NFP", "CPI")
        },
        "storm_compare": {p: {"covid_2020": [["siren", "71", "99"]]} for p in pairs},
        "faq": {
            t: [["what", "answer"]]
            for t in ("pricing", "tiers", "alerts", "api", "data", "privacy")
        },
        "ask_bank": {
            t: [["question"]] for t in ("forward", "option", "spread", "ladder", "policy")
        },
        "metrics": {"default": [["change_risk_5d", "0.02"]]},
    }
    return {
        "pack": {
            "pairs": pairs,
            "events": [{"type": "SNB", "days": 12}],
            "ledger": {
                "days_live": 3,
                "live_brier": 0.1,
                "frozen_brier": 0.102,
                "coverage_live": 0.916,
                "chain_head_short": "a1b2c3d4",
                "chain_ok": True,
                "n_forecasts": 42,
            },
            "drift": {"model_stale": False},
        },
        "treasury": {"pairs": tre},
        "decision": {"pairs": dec},
        "series": series,
        "table": tables,
        "media": {
            "storm": {"covid_2020": "/media/covid.mp4"},
            "weekly": {"2026-W34": "/media/w34.mp4"},
            "snapshot": {"board1": "/media/board1.png"},
        },
        "diagram": {
            d: "<svg/>" for d in ("siren", "regime", "conformal", "ledger", "consensus", "pipeline")
        }
        | {"flow": {m: "<svg/>" for m in ("change_risk", "siren", "regime", "band", "light")}},
        "glossary": {
            t: "a definition"
            for t in (
                "chop",
                "calm",
                "trend",
                "crisis",
                "siren",
                "band",
                "brier",
                "consensus",
                "filtered",
                "ledger",
            )
        },
    }


SAMPLE_ARGS = {
    "pair": "EURUSD",
    "pairs": "EURUSD",
    "window": "90d",
    "anchor": "month",
    "metric": "es_99",
    "tolerance": "balanced",
    "exposure": "800000",
    "move": "3%",
    "size_band": "3pct",
    "horizon": "4",
    "date": "2026-08-19",
    "episode": "covid_2020",
    "event_type": "SNB",
    "bank": "SNB",
    "week": "2026-W34",
    "board_id": "board1",
    "diagram": "siren",
    "term": "chop",
    "topic": "pricing",
    "metric_keys": "default",
    "slot": "regime",
}


def _args_for(card: V.Card) -> dict[str, str]:
    """Arguments taken from the card's OWN schema — the same arg name means different things on
    different cards (metric on var_es_bars is es_99; on methodology_flow it is change_risk)."""
    out: dict[str, str] = {}
    for name, spec in card.args.items():
        values = spec.get("values") or []
        out[name] = str(values[0]) if values else SAMPLE_ARGS.get(name, "default")
    return out


def test_every_built_card_resolves_against_a_sample_bundle(reg: V.Registry) -> None:
    """The contract test: a binding that has drifted fails CI, not a customer's question."""
    bundle = _sample_bundle()
    failures = []
    for card in reg.built():
        args = _args_for(card)
        try:
            values = V.resolve(card, args, bundle)
            caption = V.caption_for(card, values | {"asof": "2026-08-19"})
            assert caption, f"{card.id}: empty caption"
        except Exception as exc:  # noqa: BLE001 — collect all, report together
            failures.append(f"{card.id}: {exc}")
    assert not failures, "unresolvable built cards:\n" + "\n".join(failures)


def test_resolver_rejects_an_out_of_enum_argument(reg: V.Registry) -> None:
    card = reg.cards["condition_card"]
    with pytest.raises(V.RegistryError, match="not an allowed value"):
        V.resolve(card, {"pair": "XAUUSD"}, _sample_bundle())


# --------------------------------------------------------------------------- composition -------
def test_board_rules(reg: V.Registry) -> None:
    c = reg.cards
    V.validate_board([])  # null board is first-class
    # primary + two supports: three families, three primitives
    V.validate_board([c["condition_card"], c["risk_trace"], c["event_countdown_strip"]])
    with pytest.raises(V.RegistryError, match="at most"):
        V.validate_board(
            [c["condition_card"], c["risk_trace"], c["event_countdown_strip"], c["treasury_light"]]
        )
    with pytest.raises(V.RegistryError, match="family"):
        V.validate_board([c["condition_card"], c["siren_gauge"]])  # both state
    with pytest.raises(V.RegistryError, match="primitive"):
        V.validate_board(
            [c["condition_card"], c["treasury_light"]]
        )  # both stat_block, no explainer
    V.validate_board([c["condition_card"], c["glossary_card"]])  # primary + explain is allowed


def test_board_rejects_a_chain_of_three_sharing_one_primitive(reg: V.Registry) -> None:
    """Regression: the rule was checked pairwise, so three stat_blocks passed as long as one was
    an explainer. Only a PAIR (primary + explain) may repeat a primitive."""
    c = reg.cards
    with pytest.raises(V.RegistryError, match="share the primitive"):
        V.validate_board([c["condition_card"], c["glossary_card"], c["treasury_light"]])
    V.validate_board([c["condition_card"], c["glossary_card"]])  # the allowed pair still passes


def test_missing_argument_names_itself(reg: V.Registry) -> None:
    """Regression: a missing arg surfaced as 'binding path not found: pack.pairs.{pair}.regime',
    which sends the reader looking for a data problem instead of a call-site problem."""
    with pytest.raises(V.RegistryError, match=r"needs argument\(s\) \['pair'\]"):
        V.resolve(reg.cards["condition_card"], {}, _sample_bundle())


def test_cache_key_includes_locale_and_versions() -> None:
    k1 = V.cache_key("3.0.0", "ctx1", "condition_card", {"pair": "EURUSD"}, "en")
    k2 = V.cache_key("3.0.0", "ctx1", "condition_card", {"pair": "EURUSD"}, "de")
    assert k1 != k2 and "3.0.0" in k1 and "ctx1" in k1


# ------------------------------------------------------------------------------ golden ---------
def test_golden_set_covers_every_built_card(reg: V.Registry, golden: list[dict]) -> None:
    """A card without golden questions may not be marked built."""
    counts: dict[str, int] = {}
    for row in golden:
        if row["family"] == "selection":
            counts[row["expect"]] = counts.get(row["expect"], 0) + 1
    missing = [c.id for c in reg.built() if counts.get(c.id, 0) < 3]
    assert not missing, f"built cards with fewer than 3 golden questions: {missing}"
    assert len(golden) >= 150, f"golden set is {len(golden)}, needs >= 150"


def test_golden_questions_are_not_copied_from_the_index(
    reg: V.Registry, golden: list[dict]
) -> None:
    """If a golden question were an intent, recall@6 would measure nothing."""
    intents = {p.lower().strip() for c in reg.cards.values() for p in c.intents()}
    leaked = [g["q"] for g in golden if g["q"].lower().strip() in intents]
    assert not leaked, f"golden questions copied from question_intents: {leaked}"


# -------------------------------------------------------------------------- the primitives -----
def test_cards_js_implements_exactly_the_eight_primitives() -> None:
    js = CARDS_JS.read_text()
    for p in V.PRIMITIVES:
        assert f"function {p}(" in js, f"cards.js does not implement {p}"
    assert not re.search(r"#[0-9a-fA-F]{6}\b", js), "cards.js contains a hex colour literal"
    assert "buildText" in js, "the single caption/ARIA source is missing"


def test_widget_css_declares_a_height_band_for_every_primitive() -> None:
    css = WIDGET_CSS.read_text()
    for p in V.PRIMITIVES:
        assert f".fxc-h-{p}{{min-height:" in css, f"no fixed height band for {p}"
