"""The visual registry: retrieval, resolution and board composition (phase 38).

Fifty cards, eight primitives, and a prompt that does not grow. The model never sees fifty
candidates — retrieval injects six plus the two catch-alls, so registry growth costs nothing at
inference. The model also never sends a value: it names a card and passes keys, and everything
numeric is resolved here from published artifacts.

Three invariants this module enforces, each with a test:
  1. a `planned` entry can never be retrieved, resolved or rendered;
  2. the injected prompt slice is the same size at 24 entries as at 50;
  3. every `built` entry resolves against a sample context bundle, or the build fails.

Retrieval is deliberately dependency-free (token overlap with IDF weighting, all locales indexed
together): CI stays sklearn-only and the ranking is deterministic, which makes recall测 testable.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from fxradar import config

REGISTRY_PATH = config.ROOT / "config" / "visual_registry.yaml"
CATCH_ALLS = ("metric_table", "explainer_diagram")
TOP_K = 6
MAX_BOARD_CARDS = 3
PRIMITIVES = (
    "stat_block",
    "bar_row",
    "trace_band",
    "ribbon",
    "table",
    "dot_row",
    "media_frame",
    "diagram_frame",
)
FAMILIES = ("state", "time", "decision", "trust", "context", "story", "explain")
_WORD = re.compile(r"[a-zà-ÿ0-9]+", re.I)

# --- query understanding -----------------------------------------------------------------------
# Retrieval is lexical by design (CI stays sklearn-only and ranking stays deterministic), so the
# vocabulary gap does the damage: "where do we stand on euro dollar" shares no word with
# "how does EURUSD look today". Two cheap layers close it — spoken pair names become codes, and a
# domain thesaurus maps user vocabulary onto the words the registry actually uses. Both are applied
# to the query AND to the indexed intents, so they cannot bias one side.
PAIR_ALIASES = {
    "eurusd": ["euro dollar", "eur usd", "euro against the dollar", "eurodollar"],
    "usdchf": ["dollar franc", "usd chf", "swissie", "swiss franc"],
    "gbpusd": ["sterling dollar", "gbp usd", "cable", "pound dollar"],
}
THESAURUS = {
    "regime": ["state", "condition", "conditions", "market", "mode", "phase"],
    "today": ["now", "currently", "morning", "session", "stand", "current"],
    "unusual": [
        "odd",
        "strange",
        "weird",
        "abnormal",
        "anomaly",
        "anomalous",
        "stand out",
        "outlier",
        "unusualness",
    ],
    "probability": [
        "likelihood",
        "odds",
        "chance",
        "chances",
        "confidence",
        "sure",
        "certainty",
        "confident",
    ],
    "compare": [
        "versus",
        "against",
        "side by side",
        "contrast",
        "rank",
        "comparison",
        "alongside",
        "similar",
        "resemble",
        "resembles",
    ],
    "risk": ["change risk", "danger", "exposure to change"],
    "volatility": ["vol", "swing", "movement", "moves", "choppiness"],
    "history": ["past", "previous", "earlier", "prior", "historical", "record", "before"],
    "trust": ["record", "accuracy", "accurate", "reliable", "convince", "brier", "track record"],
    "coverage": ["intervals", "interval", "bands", "band", "calibrated", "contain"],
    "verify": ["audit", "check", "confirm", "independently", "seal", "sealed", "hash", "chain"],
    "hedge": ["cover", "covering", "protect", "insurance", "stance"],
    "money": ["loss", "lose", "cost", "damage", "impact", "amount", "exposure", "position"],
    "event": ["calendar", "diary", "meeting", "scheduled", "upcoming", "ahead", "policy decision"],
    "driver": ["drivers", "attribute", "attribution", "inputs", "contributed", "pushed", "because"],
    "explain": ["how does", "mechanism", "diagram", "picture", "draw", "walk through"],
    "definition": ["define", "meaning", "means", "what counts as", "term"],
    "advice": ["should i", "advise", "recommend", "what would you do", "tell me what"],
    "direction": [
        "rise",
        "fall",
        "higher",
        "lower",
        "target",
        "forecast the price",
        "heading",
        "strengthen",
        "weaken",
        "going up",
        "long",
        "short",
    ],
    "export": ["share", "shareable", "send", "forward", "image", "download", "take away"],
    "duration": ["how long", "persisted", "span", "length", "lasts"],
    "delay": [
        "waiting",
        "wait",
        "postpone",
        "postponing",
        "penalty",
        "defer",
        "deferring",
        "patience",
        "another month",
        "later",
    ],
    "frequency": ["how often", "how many times", "common", "ordinary", "occurrences", "rare"],
    "metrics": ["figures", "values", "numbers", "raw", "dump", "data"],
    "storm": ["crisis", "shock", "episode", "pandemic", "covid", "stress episode"],
    "replay": ["play", "playback", "step through", "session by session", "watch", "unfold"],
    "delta": ["changed", "change since", "shifted", "moved", "overnight", "new"],
}
_EXPANSION: dict[str, set[str]] = {}
for _canon, _variants in THESAURUS.items():
    for _v in _variants:
        for _w in _v.split():
            _EXPANSION.setdefault(_w, set()).add(_canon)
    _EXPANSION.setdefault(_canon, set()).add(_canon)
for _code, _names in PAIR_ALIASES.items():
    for _n in _names:
        for _w in _n.split():
            _EXPANSION.setdefault(_w, set()).add(_code)
    _EXPANSION.setdefault(_code, set()).add(_code)


def _normalise(text: str) -> str:
    """Spoken pair names become codes before tokenising ("euro dollar" -> "eurusd")."""
    low = (text or "").lower()
    for code, names in PAIR_ALIASES.items():
        for name in names:
            if name in low:
                low = low.replace(name, code)
    return low


def _expand(tokens: list[str]) -> Counter:
    """Tokens plus their canonical domain terms — applied identically to queries and documents."""
    bag = Counter(tokens)
    for tok in tokens:
        for canon in _EXPANSION.get(tok, ()):  # noqa: SIM118
            bag[canon] += 1
    return bag


def _char_ngrams(text: str, n: int = 4) -> Counter:
    s = f" {re.sub(r'[^a-z0-9 ]', '', (text or '').lower())} "
    return Counter(s[i : i + n] for i in range(max(0, len(s) - n + 1)))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return num / (na * nb) if na and nb else 0.0


class RegistryError(RuntimeError):
    """A card was asked to do something the registry forbids."""


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


@dataclass(frozen=True)
class Card:
    id: str
    status: str
    tier: int
    family: str
    primitive: str
    question_intents: dict[str, list[str]]
    args: dict[str, Any]
    bindings: dict[str, str]
    disambiguation: dict[str, Any]
    caption: dict[str, str]
    aria: dict[str, str]
    when_not: str
    owner_artifact: str

    @property
    def built(self) -> bool:
        return self.status == "built"

    def intents(self) -> list[str]:
        return [p for phrases in self.question_intents.values() for p in phrases]


@dataclass
class Registry:
    version: str
    cards: dict[str, Card]
    _df: Counter = field(default_factory=Counter)
    _docs: dict[str, Counter] = field(default_factory=dict)
    _chars: dict[str, Counter] = field(default_factory=dict)

    def built(self) -> list[Card]:
        return [c for c in self.cards.values() if c.built]

    def index(self) -> None:
        """Build the retrieval index over question_intents of BUILT cards, all locales together.

        The document for a card is its intents in every locale, plus its id and its caption — the
        caption carries the domain nouns a user is likely to echo back ("expected shortfall",
        "conformal band") that the intents do not always spell out.
        """
        self._docs, self._df, self._chars = {}, Counter(), {}
        for card in self.built():
            text = (
                " ".join(card.intents())
                + " "
                + card.id.replace("_", " ")
                + " "
                + " ".join(card.caption.values())
            )
            norm = _normalise(text)
            bag = _expand(_tokens(norm))
            self._docs[card.id] = bag
            self._chars[card.id] = _char_ngrams(norm)
            self._df.update(set(bag))

    def _score(self, card_id: str, q_bag: Counter, q_chars: Counter) -> float:
        bag = self._docs.get(card_id)
        if not bag:
            return 0.0
        n = max(1, len(self._docs))
        lexical = 0.0
        for tok, qn in q_bag.items():
            if tok in bag:
                idf = math.log(1 + n / (1 + self._df[tok]))
                lexical += idf * qn * (1 + math.log(1 + bag[tok]))
        lexical /= 1 + math.log(1 + sum(bag.values()))
        # character similarity catches morphology and near-spellings the thesaurus misses
        return lexical + 2.5 * _cosine(q_chars, self._chars.get(card_id, Counter()))

    def retrieve(self, question: str, k: int = TOP_K) -> list[Card]:
        """Top-k built candidates plus the two catch-alls — never more, whatever the registry size."""
        if not self._docs:
            self.index()
        norm = _normalise(question)
        q_bag, q_chars = _expand(_tokens(norm)), _char_ngrams(norm)
        ranked = sorted(
            (c for c in self.built()),
            key=lambda c: (-self._score(c.id, q_bag, q_chars), c.tier, c.id),
        )
        out = [c for c in ranked[:k]]
        for cid in CATCH_ALLS:
            card = self.cards.get(cid)
            if card and card.built and card not in out:
                out.append(card)
        return out


@lru_cache(maxsize=4)
def _load(path_str: str, mtime: float) -> Registry:
    doc = yaml.safe_load(Path(path_str).read_text())
    cards: dict[str, Card] = {}
    for raw in doc["cards"]:
        card = Card(
            id=raw["id"],
            status=raw["status"],
            tier=int(raw["tier"]),
            family=raw["family"],
            primitive=raw["primitive"],
            question_intents=raw.get("question_intents") or {},
            args=raw.get("args") or {},
            bindings=raw.get("bindings") or {},
            disambiguation=raw.get("disambiguation") or {},
            caption=raw.get("caption") or {},
            aria=raw.get("aria") or {},
            when_not=raw.get("when_not", ""),
            owner_artifact=raw.get("owner_artifact", ""),
        )
        cards[card.id] = card
    reg = Registry(version=str(doc.get("registry_version", "0")), cards=cards)
    reg.index()
    return reg


def load_registry(path: Path | None = None) -> Registry:
    p = path or REGISTRY_PATH
    return _load(str(p), p.stat().st_mtime)


# ---------------------------------------------------------------------------------------------
# the injected prompt slice — the flat-cost guarantee
# ---------------------------------------------------------------------------------------------
def prompt_slice(candidates: list[Card], locale: str = "en") -> str:
    """What the model actually sees: only the retrieved candidates, with their tie-break rules.

    The whole registry is NEVER injected — that is the entire point. This function's output size
    is a function of len(candidates), not of registry size, which `test_flat_prompt` asserts.
    """
    lines = ["VISUAL CANDIDATES (name one, or none; pass keys only — never values):"]
    for c in candidates:
        args = ", ".join(f"{k}:{v.get('type')}" for k, v in c.args.items()) or "none"
        line = f"- {c.id} ({c.family}/{c.primitive}) args[{args}] — {c.caption.get(locale, '')}"
        rule = (c.disambiguation or {}).get("rule")
        rivals = (c.disambiguation or {}).get("rivals") or []
        if rule and rivals:
            line += f" | vs {', '.join(rivals)}: {rule}"
        if c.when_not:
            line += f" | not when: {c.when_not}"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# resolution — the server owns every value
# ---------------------------------------------------------------------------------------------
def _dig(bundle: dict, path: str) -> Any:
    node: Any = bundle
    for part in path.split("."):
        if isinstance(node, dict):
            if part not in node:
                raise RegistryError(f"binding path not found: {path} (missing {part!r})")
            node = node[part]
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError) as exc:
                raise RegistryError(f"binding path not found: {path}") from exc
        else:
            raise RegistryError(f"binding path not found: {path}")
    return node


def resolve(card: Card, args: dict[str, Any], bundle: dict) -> dict[str, Any]:
    """Resolve one card's bindings into concrete values. Refuses planned entries, always."""
    if not card.built:
        raise RegistryError(f"{card.id} is planned, not built — it may never be rendered")
    for name, spec in card.args.items():
        if spec.get("type") == "enum" and name in args:
            if str(args[name]) not in [str(v) for v in spec.get("values", [])]:
                raise RegistryError(f"{card.id}: {name}={args[name]!r} is not an allowed value")
    supplied = {k: str(v) for k, v in (args or {}).items()}
    out: dict[str, Any] = {}
    for key, template in card.bindings.items():
        needed = set(re.findall(r"\{(\w+)\}", template))
        missing = needed - set(supplied)
        if missing:
            raise RegistryError(
                f"{card.id}: binding {key!r} needs argument(s) {sorted(missing)} — "
                f"got {sorted(supplied) or 'none'}"
            )
        out[key] = _dig(bundle, template.format(**supplied) if needed else template)
    return out


def caption_for(card: Card, values: dict[str, Any], locale: str = "en") -> str:
    tmpl = card.caption.get(locale) or card.caption.get("en") or ""
    safe = {k: ("—" if v is None else v) for k, v in values.items()}
    try:
        return tmpl.format(**safe)
    except KeyError:
        return tmpl


# ---------------------------------------------------------------------------------------------
# board composition
# ---------------------------------------------------------------------------------------------
def validate_board(cards: list[Card]) -> None:
    """At most three cards; support cards from a different family; no repeated primitive unless
    the second card is an explainer (primary + explain is the one allowed pairing)."""
    if len(cards) > MAX_BOARD_CARDS:
        raise RegistryError(f"a board carries at most {MAX_BOARD_CARDS} cards, got {len(cards)}")
    if any(not c.built for c in cards):
        raise RegistryError("a planned card may never appear in a board")
    if not cards:
        return  # the null board is first-class
    primary, support = cards[0], cards[1:]
    for c in support:
        if c.family == primary.family:
            raise RegistryError(
                f"support card {c.id} shares the family {c.family!r} with the primary {primary.id}"
            )
    by_primitive: dict[str, list[Card]] = {}
    for c in cards:
        by_primitive.setdefault(c.primitive, []).append(c)
    for primitive, group in by_primitive.items():
        if len(group) == 1:
            continue
        # The allowed exception is a PAIR whose roles differ: one primary plus one explainer. A
        # chain of three sharing a primitive is the visual noise this rule exists to prevent, and
        # a pairwise check let it through.
        explainers = [c for c in group if c.family == "explain"]
        if len(group) > 2 or len(explainers) != 1:
            raise RegistryError(
                f"{len(group)} cards share the primitive {primitive!r} "
                f"({', '.join(c.id for c in group)}); only primary + explain may repeat one"
            )


def cache_key(
    registry_version: str, context_version: str, component: str, args: dict[str, Any], locale: str
) -> str:
    """(registry_version, context_version, component, args, locale) — locale added at 50 cards."""
    flat = ",".join(f"{k}={args[k]}" for k in sorted(args))
    return f"{registry_version}|{context_version}|{component}|{flat}|{locale}"
