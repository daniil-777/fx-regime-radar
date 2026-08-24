"""One card anatomy for every outcome, and the five gates that run before anything shows.

Order on every card: verdict line, body, receipts, conditions strip, footer. The only free text
on the page is the verbatim quoted passage, always visually marked as a quotation; every other
string is a template filled from the daily artifact or the slip.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from ask.retrieve import ALLOWLIST, Evidence, build_search_payload, latest_cached
from ask.rules import KINDS, Route
from fxradar import config as fxconfig
from fxradar.config import DISCLAIMER
from fxradar.narrate import DIRECTION_WORDS

VERDICTS = {
    "conditions": "✓ Answered from today's data",
    "official_fact": "✓ Found on {domain}",
    "direction_or_advice": "— Not something we answer",
    "out_of_scope": "— Not covered",
    "unclear": "? Not sure what you're asking",
}

_ASSET_WORDS = {
    "crypto": "Crypto",
    "equity": "Stocks",
    "other": "That market",
    "none": "That market",
    "fx_pair": "That market",
}

SORTED_NOTE = "Questions are sorted by an AI model; answers are templated from data."
FOOTER = f"{DISCLAIMER} {SORTED_NOTE}"


def _refusals() -> dict:
    """The existing customer-facing refusal sentences, read from the grounding artifact."""
    try:
        return json.loads((fxconfig.DATA_DIR / "avatar_context.json").read_text()).get(
            "refusals", {}
        )
    except Exception:
        return {}


def fmt_stats(stats: dict) -> dict:
    """The ONE formatting of artifact numbers; gate G5 builds its allowed set from this."""
    return {
        "pair": f"{stats['pair'][:3]}/{stats['pair'][3:]}",
        "regime": str(stats["regime"]),
        "risk": f"{float(stats['change_risk_5d']) * 100:.0f}",
        "lo": f"{float(stats['risk_lo']) * 100:.0f}",
        "hi": f"{float(stats['risk_hi']) * 100:.0f}",
        "siren": f"{float(stats['anomaly_pct']):.0f}",
    }


def conditions_strip(stats: dict) -> dict:
    f = fmt_stats(stats)
    # The conformal band is clipped to [0, 100] and therefore asymmetric, so it renders as a
    # range, not a ±: pretending symmetry would misstate the published interval.
    return {
        "pair": f["pair"],
        "regime": f["regime"],
        "text": f"change risk {f['risk']}% (band {f['lo']}–{f['hi']}%) · siren {f['siren']}",
    }


@dataclass
class Card:
    kind: str
    verdict: str
    subline: str
    body: str
    quote: str = ""  # verbatim passage; the ONLY non-templated text; rendered as quotation
    receipts: list = field(default_factory=list)
    source_url: str = ""
    strip: dict = field(default_factory=dict)
    footer_note: str = FOOTER
    trust_line: str = ""
    gate: str = "none"


def _receipt_chips(ev: Evidence) -> list:
    chips = [ev.domain, f"seen {ev.seen_date}"]
    if ev.receipt_id:
        chips.append(f"receipt {ev.receipt_id[:8]}")
    chips.append(f"sha {ev.content_sha256[:8]}")
    return chips


def render(
    route: Route, evidence: Evidence | None, stats: dict, pairs: list[str], tag: str
) -> Card:
    """Fill the template for the routed kind. Computes nothing; formats artifact fields only."""
    ref = _refusals()
    strip = conditions_strip(stats)
    trust = f"v{tag} · frozen test scored once · verify independently"
    slipwords = " · ".join(
        w
        for w in (
            route.doc_type if route.doc_type != "none" else "",
            route.window if route.window != "none" else "",
        )
        if w
    )
    if route.kind == "conditions":
        f = fmt_stats(stats)
        body = (
            f"{f['pair']} is in a {f['regime']} regime today. Change risk over the next five "
            f"trading days: {f['risk']}% (band {f['lo']}–{f['hi']}%). Siren: {f['siren']} of 100."
        )
        return Card(
            "conditions",
            VERDICTS["conditions"],
            "today's published reading",
            body,
            strip=strip,
            trust_line=trust,
        )
    if route.kind == "official_fact" and evidence is not None:
        sub = " · ".join(x for x in (slipwords, f"seen {evidence.seen_date}") if x)
        return Card(
            "official_fact",
            VERDICTS["official_fact"].format(domain=evidence.domain),
            sub,
            "",
            quote=evidence.passage,
            receipts=_receipt_chips(evidence),
            source_url=evidence.url,
            strip=strip,
            trust_line=trust,
        )
    if route.kind == "direction_or_advice":
        line = (
            ref.get("direction")
            or "That asks which way the price will move, and this radar never models direction — in any market, mine included."
        )
        first = line.split(". ")[0].rstrip(".") + "."
        return Card(
            "direction_or_advice",
            VERDICTS["direction_or_advice"],
            "sorted by rule, no model call" if route.router == "rules" else "sorted by the model",
            f"{first} Here's what's true today.",
            receipts=_borrowed_receipts(route),
            strip=strip,
            trust_line=trust,
        )
    if route.kind == "out_of_scope":
        listed = ", ".join(f"{p[:3]}/{p[3:]}" for p in pairs)
        # The spec's sentence, reworded past the direction-word gate ("buy" is a banned word even
        # inside a refusal): meaning kept, vocabulary compliant.
        body = (
            f"{_ASSET_WORDS.get(route.asset, 'That market')} isn't something this service reads, and it "
            f"never gives buying-or-selling advice in any market. Here's what's true today for the "
            f"currency pairs it does track: {listed}."
        )
        sub = (
            f"{route.asset if route.asset != 'none' else 'other'} · sorted by rule, no model call"
            if route.router == "rules"
            else f"{route.asset} · sorted by the model"
        )
        return Card(
            "out_of_scope",
            VERDICTS["out_of_scope"],
            sub,
            body,
            receipts=_borrowed_receipts(route),
            strip=strip,
            trust_line=trust,
        )
    return Card(
        "unclear",
        VERDICTS["unclear"],
        "try one of the examples",
        "Try one of the three example questions below — conditions today, an official statement, or what this service never answers.",
        strip=strip,
        trust_line=trust,
    )


def _borrowed_receipts(route: Route) -> list:
    """Refusal cards show the latest cached official receipts: the slip's institution, else SNB."""
    for inst in (route.institution, "SNB"):
        if inst and inst != "none":
            ev = latest_cached(inst)
            if ev is not None:
                return _receipt_chips(ev)
    return []


# ---------------------------------------------------------------- the five gates ---------------


def g1_enums(route: Route) -> str | None:
    from ask.rules import ASSETS, DOC_TYPES, INSTITUTIONS, LANGUAGES, ROUTERS, WINDOWS

    ok = (
        route.kind in KINDS
        and route.institution in INSTITUTIONS
        and route.doc_type in DOC_TYPES
        and route.window in WINDOWS
        and route.asset in ASSETS
        and route.language in LANGUAGES
        and route.router in ROUTERS
    )
    return None if ok else "G1"


def g2_allowlist(route: Route, evidence: Evidence | None) -> str | None:
    if build_search_payload(route)["include_domains"] != ALLOWLIST:
        return "G2"
    if evidence is not None and evidence.domain not in ALLOWLIST:
        return "G2"
    return None


def g3_passage_hash(card: Card, evidence: Evidence | None) -> str | None:
    if not card.quote:
        return None
    if evidence is None:
        return "G3"
    same = (
        hashlib.sha256(card.quote.encode()).hexdigest()
        == hashlib.sha256(evidence.passage.encode()).hexdigest()
    )
    return None if same else "G3"


def g4_words(card: Card) -> str | None:
    """Product-authored strings pass the direction-word gate; the quotation is document text."""
    authored = " ".join([card.verdict, card.body, card.strip.get("text", ""), card.footer_note])
    return "G4" if DIRECTION_WORDS.search(authored) else None


_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def g5_numbers(card: Card, stats: dict, evidence: Evidence | None) -> str | None:
    """Every number in a product claim equals a formatted artifact field (or the seen-date)."""
    f = fmt_stats(stats)
    allowed = {f["risk"], f["lo"], f["hi"], f["siren"], "5", "100"}  # 5-day horizon, siren scale
    if evidence is not None:
        allowed |= set(_NUM_RE.findall(evidence.seen_date))
    claimed = " ".join([card.verdict, card.subline, card.body, card.strip.get("text", "")])
    return None if set(_NUM_RE.findall(claimed)) <= allowed else "G5"


def apply_gates(route: Route, card: Card, evidence: Evidence | None, stats: dict, tag: str) -> Card:
    """Run G1..G5 in order; any failure swaps in the unclear template and names the gate."""
    for gate in (
        g1_enums(route),
        g2_allowlist(route, evidence),
        g3_passage_hash(card, evidence),
        g4_words(card),
        g5_numbers(card, stats, evidence),
    ):
        if gate is not None:
            fallback = render(Route(kind="unclear", router=route.router), None, stats, [], tag)
            fallback.gate = gate
            return fallback
    return card
