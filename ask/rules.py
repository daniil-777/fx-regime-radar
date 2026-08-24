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

# (d) institution + document verb -> official_fact, decided by rules so the page needs no model
# key at all for its five outcomes (owner constraint: no Token Factory account; the model lane
# stays as an optional tail). Both signals are required: an institution alone is context.
_INSTITUTION_WORDS = [
    ("bank of england", "BoE"),
    ("federal reserve", "Fed"),
    ("snb", "SNB"),
    ("ezb", "ECB"),
    ("bce", "ECB"),
    ("ecb", "ECB"),
    ("fed", "Fed"),
    ("boe", "BoE"),
    ("bis", "BIS"),
]
_DOC_VERBS = [
    "did",
    "decide",
    "decided",
    "say",
    "said",
    "announce",
    "announced",
    "publish",
    "published",
    "minutes",
    "press release",
    "statement",
    "speech",
    "gesagt",
    "entschieden",
    "beschlossen",
    "angekündigt",
    "veröffentlicht",
    "décidé",
    "dit",
    "annoncé",
    "publié",
]


def _fact_slip(q: str, lang: str) -> Route | None:
    inst = next((code for word, code in _INSTITUTION_WORDS if word in q), None)
    if inst is None or not any(v in q for v in _DOC_VERBS):
        return None
    doc = (
        "minutes"
        if "minutes" in q
        else "press_release" if "press release" in q else "speech" if "speech" in q else "decision"
    )
    window = (
        "month"
        if any(w in q for w in ("month", "monat", "mois"))
        else (
            "week"
            if any(w in q for w in ("week", "woche", "semaine"))
            else "today" if any(w in q for w in ("today", "heute", "aujourd'hui")) else "none"
        )
    )
    return Route(kind="official_fact", institution=inst, doc_type=doc, window=window, language=lang)


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


_PAIR_WORDS = [
    ("euro", "EURUSD"),
    ("euros", "EURUSD"),
    ("eur", "EURUSD"),
    ("franc", "USDCHF"),
    ("francs", "USDCHF"),
    ("swissie", "USDCHF"),
    ("chf", "USDCHF"),
    ("pound", "GBPUSD"),
    ("pounds", "GBPUSD"),
    ("sterling", "GBPUSD"),
    ("cable", "GBPUSD"),
    ("gbp", "GBPUSD"),
]


def detect_pair_word(question: str) -> str | None:
    """The pair a question names in words ("euros", "franc") or codes; None when unnamed.

    The audit's wrong-market lesson applies here too: a question about francs must never get
    the euro's numbers by default. Codes first, then currency words, whole-word matched.
    """
    q = question.lower()
    compact = "".join(c for c in q if c.isalnum())
    for pair in fxconfig.PAIRS:
        if pair.lower() in compact:
            return pair
    words = set(re.split(r"[^a-z]+", q))
    for word, pair in _PAIR_WORDS:
        if word in words and pair in fxconfig.PAIRS:
            return pair
    return None


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
    # (d) institution + document verb: a past-tense fact question, answered with receipts.
    fact = _fact_slip(q, lang)
    if fact is not None:
        return fact
    # (c) conditions vocabulary, incl. the pairs the pipeline tracks.
    if any(t in q for t in _CONDITION_TERMS + _pair_terms()):
        return Route(kind="conditions", asset="fx_pair", window="today", language=lang)
    return None
