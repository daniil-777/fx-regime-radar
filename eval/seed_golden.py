#!/usr/bin/env python3
"""Assemble `eval/golden.yaml` from authored questions, attaching COMPUTED gold values (phase 39).

Sources, in order of trust:
  1. `eval/authored/*.json` — questions written for this suite (six families, EN/DE/FR), including
     the multi-turn and injection families that a conversational product actually receives.
  2. `tests/golden_visuals.yaml` — the phase-38 card-selection set, reused for card coverage.

The seeder never types a number. Where a family has a numeric expectation, it derives a `source_ref`
from the question's own subject (which market, which metric) and lets the harness resolve the value
from the snapshot at load time. Anything it cannot address confidently gets no gold value rather
than a guessed one: a missing expectation is honest, a wrong one is corrosive.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from harness import FAMILY_MINIMUMS, load_snapshot  # noqa: E402

AUTHORED = ROOT / "eval" / "authored"
OUT = ROOT / "eval" / "golden.yaml"

# Which market a question is about, using the same alias table the retriever uses.
PAIR_WORDS = {
    "eurusd": ["eur usd", "eurusd", "eur/usd", "euro dollar", "euro"],
    "usdchf": ["usd chf", "usdchf", "usd/chf", "franc", "swissie", "chf"],
    "gbpusd": ["gbp usd", "gbpusd", "gbp/usd", "sterling", "cable", "pound", "livre"],
}
MARKET_ONLY = {  # non-major markets live under the markets block
    "usdjpy": ["yen", "jpy", "usdjpy", "usd/jpy"],
    "usdrub": ["ruble", "rouble", "rubel", "usdrub"],
    "btc-usd": ["bitcoin", "btc"],
    "audusd": ["aussie", "audusd", "australian"],
    "usdpln": ["zloty", "usdpln", "polish"],
}
METRIC_REFS = {
    "change_risk": (
        "change_risk_5d",
        ["change risk", "änderungsrisiko", "risiko", "risque", "risk"],
    ),
    "siren": ("anomaly_pct", ["siren", "sirene", "sirène", "anomaly", "unusual", "ungewöhnlich"]),
    "regime": ("regime", ["regime", "régime", "state", "zustand"]),
    "consensus": ("agreement", ["consensus", "konsens", "voters", "agree", "einig"]),
}
LEDGER_REFS = {
    "days_live": ["how long", "days live", "since", "seit wann", "depuis"],
    "chain_head_short": ["chain", "head", "hash", "kette"],
    "n_forecasts": ["how many forecast", "forecasts", "prognosen", "rows", "sealed"],
    "frozen_brier": ["brier", "accuracy", "genauigkeit"],
}
ROUTE_BY_FAMILY = {
    "adversarial_direction": "refuse_direction",
    "adversarial_advice": "refuse_advice",
    "out_of_scope": "refuse_off_topic",
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9äöüéèàç ]+", " ", (text or "").lower())


def detect_pair(question: str, context: str = "") -> str | None:
    hay = _norm(question + " " + context)
    for code, words in {**PAIR_WORDS, **MARKET_ONLY}.items():
        if any(w in hay for w in words):
            return code.upper() if "-" not in code else code.upper()
    return None


def _pack_path(snap, pair: str, field: str) -> str | None:
    """Address a market wherever it lives: the majors block or one of the other boards."""
    if pair in (snap.pack.get("pairs") or {}):
        return f"pack:pairs.{pair}.{field}"
    for board, uni in (snap.pack.get("markets") or {}).items():
        if pair in (uni.get("pairs") or {}):
            return f"pack:markets.{board}.pairs.{pair}.{field}"
    return None


def infer_gold(item: dict, snap) -> list[dict]:
    """Derive source_refs from what the question is actually asking about."""
    family, q = item.get("family", ""), item.get("question", "")
    hay = _norm(q + " " + (item.get("turn_context") or ""))
    out: list[dict] = []

    if family in (
        "today_state",
        "comparative_temporal",
        "causal_explanatory",
        "multi_turn_followup",
    ):
        pair = detect_pair(q, item.get("turn_context", ""))
        if not pair:
            return out
        wanted = [name for name, (_f, words) in METRIC_REFS.items() if any(w in hay for w in words)]
        if not wanted and family == "today_state":
            wanted = ["regime"]  # a bare "eurusd?" is asking for the state
        for name in wanted[:2]:
            fieldname = METRIC_REFS[name][0]
            ref = _pack_path(snap, pair, fieldname)
            if ref:
                out.append({"name": name, "source_ref": ref})

    elif family == "ledger_historical":
        for fieldname, words in LEDGER_REFS.items():
            if any(w in hay for w in words):
                out.append({"name": fieldname, "source_ref": f"pack:ledger.{fieldname}"})
                break

    elif family == "aggregation":
        for regime in ("calm", "trend", "chop", "crisis"):
            if regime in hay:
                out.append(
                    {"name": f"n_{regime}", "source_ref": f"count:regimes.regime=={regime}@last"}
                )
                break
    return out


def to_item(raw: dict, idx: int, snap, source: str) -> dict:
    family = raw.get("family") or "today_state"
    route = raw.get("expected_route") or ROUTE_BY_FAMILY.get(family, "answer")
    item = {
        "id": f"{family}-{idx:03d}",
        "question": raw["question"].strip(),
        "locale": raw.get("locale", "en"),
        "family": family,
        "intent_id": raw.get("intent_id") or family,
        "precomputable": family not in ("multi_hop", "aggregation", "comparative_temporal"),
        "turn_context": raw.get("turn_context", "") or "",
        "expected_route": route,
        "expected_primary_card": raw.get("expected_primary_card", "") or "",
        "expected_support_cards": raw.get("expected_support_cards") or [],
        "gold_values": infer_gold(raw, snap),
        "tolerance": 0.0,
        "must_not_contain": raw.get("must_not_contain") or [],
        "notes": (raw.get("notes") or "").strip(),
        "source": source,
    }
    if family == "adversarial_direction":
        item["must_not_contain"] = sorted(
            set(item["must_not_contain"]) | {"rise", "fall", "higher", "lower", "target"}
        )
        # A direction question SHOULD produce a visual — the evidence card, and only that. Scoring
        # it as "wanted no picture" would credit the system for staying silent when the designed
        # behaviour is to show why the question cannot be answered.
        item["expected_primary_card"] = item["expected_primary_card"] or "direction_evidence_card"
    if family == "adversarial_advice" and route == "refuse_advice":
        item["expected_primary_card"] = item["expected_primary_card"] or "ask_your_bank_card"
    return item


def from_visual_golden(snap) -> list[dict]:
    """Reuse the phase-38 selection set so every built card keeps at least three items."""
    doc = yaml.safe_load((ROOT / "tests" / "golden_visuals.yaml").read_text())
    fam_map = {
        "selection": "today_state",
        "adversarial": None,
        "no_visual": "no_visual_expected",
        "stale_context": "stale_context",
        "planted_number": "planted_number",
        "planned_blocked": None,
    }
    out = []
    for row in doc["questions"]:
        family = fam_map.get(row["family"])
        if not family:
            continue
        card = row.get("expect") or ""
        # knowledge-shaped cards belong in the methodology family, not today_state
        if card in ("explainer_diagram", "glossary_card", "methodology_flow"):
            family = "knowledge_methodology"
        elif card in ("faq_card",):
            family = "product_faq"
        elif card in (
            "scoreboard_card",
            "ledger_row_receipt",
            "chain_verify_card",
            "coverage_plot",
        ):
            family = "ledger_historical"
        elif card in ("feature_driver_bars",):
            family = "causal_explanatory"
        elif card in ("regime_history_table", "storm_replay_mini", "period_compare_card"):
            family = "comparative_temporal"
        out.append(
            {
                "question": row["q"],
                "locale": "en",
                "family": family,
                "expected_primary_card": card,
                "expected_route": "answer" if card else "refuse_off_topic",
                "notes": "card-selection item carried over from the phase-38 golden set",
            }
        )
    return out


def main() -> None:
    snap = load_snapshot()
    raws: list[tuple[dict, str]] = []
    for path in sorted(AUTHORED.glob("*.json")):
        for raw in json.loads(path.read_text()):
            raws.append((raw, path.stem))
    for raw in from_visual_golden(snap):
        raws.append((raw, "phase38_visual_golden"))

    # Balance the set. The phase asks for 180–280 items, and the sources over-supply the easy
    # families: left alone, `today_state` would be 40% of the suite and the German and French share
    # would fall below the quarter that makes locale bugs visible. Cap each family, and when
    # trimming keep non-English items and items carrying a computed gold value first — those are
    # the ones that can actually fail in an informative way.
    import math

    CAPS = {fam: max(need, math.ceil(need * 1.4)) for fam, need in FAMILY_MINIMUMS.items()}
    CAPS["today_state"] = 40

    pooled: dict[str, list[tuple[dict, str]]] = {}
    seen: set[str] = set()
    for raw, source in raws:
        q = raw.get("question", "").strip()
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        pooled.setdefault(raw.get("family") or "today_state", []).append((raw, source))

    def keep_rank(entry: tuple[dict, str]) -> tuple[int, int]:
        raw, _ = entry
        non_english = 0 if raw.get("locale", "en") != "en" else 1
        has_gold = 0 if infer_gold(raw, snap) else 1
        return (non_english, has_gold)

    counters: dict[str, int] = {}
    items = []
    picked: set[int] = set()
    per_card: dict[str, int] = {}
    for fam, entries in pooled.items():
        cap = CAPS.get(fam, len(entries))
        chosen = sorted(entries, key=keep_rank)[:cap]
        for raw, source in chosen:
            picked.add(id(raw))
            card = raw.get("expected_primary_card") or ""
            if card:
                per_card[card] = per_card.get(card, 0) + 1
            counters[fam] = counters.get(fam, 0) + 1
            items.append(to_item(raw, counters[fam], snap, source))

    # Capping a family can starve a card of coverage: a card with no golden item is a card nobody
    # would notice breaking. Top each one back up to three from the items the cap dropped.
    for fam, entries in pooled.items():
        for raw, source in entries:
            if id(raw) in picked:
                continue
            card = raw.get("expected_primary_card") or ""
            if card and per_card.get(card, 0) < 3:
                per_card[card] = per_card.get(card, 0) + 1
                picked.add(id(raw))
                counters[fam] = counters.get(fam, 0) + 1
                items.append(to_item(raw, counters[fam], snap, source))

    # The phase specifies 180–280 items. Trim the surplus from the least informative end: English
    # items, in families already past their minimum, carrying no computed gold value, whose card is
    # already covered three times. Everything that can actually fail in an interesting way stays.
    MAX_ITEMS = 280
    if len(items) > MAX_ITEMS:
        fam_counts: dict[str, int] = {}
        card_counts: dict[str, int] = {}
        for it in items:
            fam_counts[it["family"]] = fam_counts.get(it["family"], 0) + 1
            if it["expected_primary_card"]:
                card_counts[it["expected_primary_card"]] = (
                    card_counts.get(it["expected_primary_card"], 0) + 1
                )

        def droppable(it: dict) -> bool:
            card = it["expected_primary_card"]
            return (
                it["locale"] == "en"
                and not it["gold_values"]
                and fam_counts.get(it["family"], 0) > FAMILY_MINIMUMS.get(it["family"], 0)
                and (not card or card_counts.get(card, 0) > 3)
            )

        kept = []
        for it in items:
            if (
                len(items) - (len(items) - len(kept))
                and len(kept) + (len(items) - items.index(it)) > MAX_ITEMS
                and droppable(it)
            ):
                fam_counts[it["family"]] -= 1
                if it["expected_primary_card"]:
                    card_counts[it["expected_primary_card"]] -= 1
                continue
            kept.append(it)
        items = kept[:MAX_ITEMS] if len(kept) > MAX_ITEMS else kept

    doc = {
        "note": (
            "Gold values are COMPUTED: each carries a source_ref resolved from eval/snapshot at "
            "load time, so a number can never rot into a false failure. Edit questions here; never "
            "type a value."
        ),
        "snapshot": snap.label,
        "items": items,
    }
    OUT.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))

    by_fam: dict[str, int] = {}
    by_loc: dict[str, int] = {}
    for it in items:
        by_fam[it["family"]] = by_fam.get(it["family"], 0) + 1
        by_loc[it["locale"]] = by_loc.get(it["locale"], 0) + 1
    print(f"wrote {OUT.relative_to(ROOT)}: {len(items)} items")
    print(
        f"  locales: {by_loc} · non-English share "
        f"{(len(items) - by_loc.get('en', 0)) / max(1, len(items)):.0%}"
    )
    short = []
    for fam, need in FAMILY_MINIMUMS.items():
        have = by_fam.get(fam, 0)
        flag = "" if have >= need else f"  SHORT by {need - have}"
        print(f"  {fam:26} {have:3}/{need}{flag}")
        if have < need:
            short.append(fam)
    n_gold = sum(1 for it in items if it["gold_values"])
    print(f"  items with computed gold values: {n_gold}")
    if short:
        print(f"  families below minimum: {', '.join(short)}")


if __name__ == "__main__":
    main()
