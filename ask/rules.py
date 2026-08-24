"""Rules-first routing: pure functions, ordered patterns, decided before any model is called.

Precedence is (a) asset lexicon over (b) advice/forecast modality over (c) conditions vocabulary.
Past-tense fact questions deliberately match nothing here — "did the SNB cut rates in June?"
returns None and goes to the model, because "did" asks about a document, not a direction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fxradar import config as fxconfig

KINDS = {"conditions", "official_fact", "direction_or_advice", "out_of_scope", "unclear"}
INSTITUTIONS = {"SNB", "ECB", "Fed", "BoE", "BIS", "none"}
DOC_TYPES = {"decision", "press_release", "speech", "minutes", "none"}
WINDOWS = {"today", "week", "month", "none"}
ASSETS = {"fx_pair", "crypto", "equity", "other", "none"}
LANGUAGES = {"en", "de", "fr", "other"}
ROUTERS = {"rules", "model"}


@dataclass(frozen=True)
class Route:
    """The enum-only slip. Nothing free-text ever sits in these fields."""

    kind: str
    institution: str = "none"
    doc_type: str = "none"
    window: str = "none"
    asset: str = "none"
    language: str = "en"
    router: str = "rules"


def _load_lexicon() -> list[str]:
    path = Path(__file__).with_name("lexicon_assets.txt")
    return [w.strip() for w in path.read_text().splitlines() if w.strip()]


_ASSET_TERMS = _load_lexicon()
_CRYPTO = {"crypto", "bitcoin", "btc", "eth", "ethereum"}
_EQUITY = {
    "stock",
    "stocks",
    "share",
    "shares",
    "equity",
    "equities",
    "aktie",
    "aktien",
    "action",
    "actions",
    "etf",
    "fund",
    "fonds",
}

# (b) advice and forecast MODALITY — start from the narrator's rule-5 word list, but matched with
# the modal frames that make them a request for direction/advice rather than a fact question.
_ADVICE_RES = [
    re.compile(p)
    for p in (
        r"\bshould i\b",
        r"\bshall i\b",
        r"\bis it a good time\b",
        r"\bbuy\b",
        r"\bsell\b",
        r"\binvest\b",
        r"\bhedge now\b",
        r"\bwill\b.*\b(go up|go down|rise|fall|rally|crash|strengthen|weaken|cut|raise|hike)\b",
        r"\bpredict\w*\b",
        r"\bforecast\w*\b",
        r"\btarget\b",
        # DE / FR
        r"\bsoll ich\b",
        r"\bkaufen\b",
        r"\bverkaufen\b",
        r"\bwird\b.*\b(steigen|fallen)\b",
        r"\bdois-je\b",
        r"\bacheter\b",
        r"\bvendre\b",
        r"\bva\b.*\b(monter|baisser)\b",
    )
]

_CONDITION_TERMS = [
    "regime",
    "siren",
    "change risk",
    "crisis",
    "calm",
    "chop",
    "trend",
    "today",
    # DE / FR condition words, same meaning
    "krise",
    "ruhig",
    "heute",
    "aujourd'hui",
    "crise",
    "calme",
]

_DE_HINTS = (
    "soll ich",
    "kaufen",
    "verkaufen",
    "wird ",
    "heute",
    "krise",
    "aktie",
    "zinsen",
    "gesagt",
    "gesenkt",
)
_FR_HINTS = (
    "dois-je",
    "acheter",
    "vendre",
    "va ",
    "aujourd'hui",
    "crise",
    "baisser",
    "monter",
    "décidé",
    "taux",
)


def detect_language(q_lower: str) -> str:
    """Logged only in this phase; rendering stays English."""
    if any(h in q_lower for h in _DE_HINTS):
        return "de"
    if any(h in q_lower for h in _FR_HINTS):
        return "fr"
    return "en"


def _pair_terms() -> list[str]:
    """Pair vocabulary from the data layer (never hardcoded): 'eurusd', 'eur/usd', ..."""
    terms: list[str] = []
    for p in fxconfig.PAIRS:
        terms += [p.lower(), f"{p[:3]}/{p[3:]}".lower()]
    return terms


def pre_route(question: str) -> Route | None:
    """Ordered rules on the lower-cased question; under 1 ms; None means 'ask the model'."""
    q = question.lower().strip()
    lang = detect_language(q)
    words = set(re.split(r"[^a-zäöüéèêà]+", q))
    # (a) named non-FX asset -> out of scope, whatever else the sentence asks.
    hit = next((t for t in _ASSET_TERMS if t in words), None)
    if hit:
        asset = "crypto" if hit in _CRYPTO else "equity" if hit in _EQUITY else "other"
        return Route(kind="out_of_scope", asset=asset, language=lang)
    # (b) direction/advice modality.
    if any(rx.search(q) for rx in _ADVICE_RES):
        return Route(kind="direction_or_advice", asset="fx_pair", language=lang)
    # (c) conditions vocabulary, incl. the pairs the pipeline tracks.
    if any(t in q for t in _CONDITION_TERMS + _pair_terms()):
        return Route(kind="conditions", asset="fx_pair", window="today", language=lang)
    return None
