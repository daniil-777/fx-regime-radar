"""Routing: rules first, Token Factory second, always an enum, never an exception to the UI.

The model classifies ONLY — it emits enum JSON and nothing else, and anything malformed
(missing key, unknown value, extra key, non-JSON, HTTP error, timeout) fails closed to
kind="unclear". After the model answers, rules (a) and (b) run again on the question; if either
matches, the rule wins and the log records override="rules" (defence in depth).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import requests

from ask import config as askcfg
from ask.rules import (
    ASSETS,
    DOC_TYPES,
    INSTITUTIONS,
    KINDS,
    LANGUAGES,
    WINDOWS,
    Route,
    detect_language,
    pre_route,
)

_UNCLEAR = Route(kind="unclear", language="other", router="model")

# At most 12 lines; no example answers.
SYSTEM_PROMPT = """You classify one user question about currency markets. Classify only.
Output JSON and nothing else, with exactly these keys and allowed values:
kind: conditions | official_fact | direction_or_advice | out_of_scope | unclear
institution: SNB | ECB | Fed | BoE | BIS | none
doc_type: decision | press_release | speech | minutes | none
window: today | week | month | none
asset: fx_pair | crypto | equity | other | none
language: en | de | fr | other"""

_ENUMS = {
    "kind": KINDS,
    "institution": INSTITUTIONS,
    "doc_type": DOC_TYPES,
    "window": WINDOWS,
    "asset": ASSETS,
    "language": LANGUAGES,
}


def _call_token_factory(question: str) -> dict:
    """One POST, temperature 0, JSON mode, 4 s timeout. Raises on any transport problem."""
    key = askcfg.nebius_key()
    if not key:
        raise RuntimeError("no NEBIUS_API_KEY")
    r = requests.post(
        askcfg.NEBIUS_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": askcfg.ASK_MODEL,
            "temperature": 0,
            "max_tokens": 120,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        },
        timeout=askcfg.MODEL_TIMEOUT_S,
    )
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def parse_model_slip(payload: object) -> Route:
    """Strict, fail closed: exactly the six keys, every value in its enum, else unclear."""
    if not isinstance(payload, dict) or set(payload) != set(_ENUMS):
        return _UNCLEAR
    for field, allowed in _ENUMS.items():
        if payload[field] not in allowed:
            return _UNCLEAR
    return Route(router="model", **{k: payload[k] for k in _ENUMS})


def route_with_meta(
    question: str, model: Callable[[str], dict] | None = None
) -> tuple[Route, dict]:
    """Route plus the metadata the log needs (latencies, override, model id)."""
    meta: dict = {
        "override": "none",
        "model_id": "none",
        "latency_rules_ms": 0.0,
        "latency_model_ms": 0.0,
    }
    t0 = time.perf_counter()
    ruled = pre_route(question)
    meta["latency_rules_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    if ruled is not None:
        return ruled, meta
    call = model or _call_token_factory
    meta["model_id"] = askcfg.ASK_MODEL
    t1 = time.perf_counter()
    try:
        decided = parse_model_slip(call(question))
    except Exception:
        decided = _UNCLEAR
    meta["latency_model_ms"] = round((time.perf_counter() - t1) * 1000, 2)
    if decided.kind == "unclear":
        return (
            Route(kind="unclear", language=detect_language(question.lower()), router="model"),
            meta,
        )
    # Defence in depth: rules (a)/(b) re-run on the question; a match beats the model.
    again = pre_route(question)
    if again is not None and again.kind in ("out_of_scope", "direction_or_advice"):
        meta["override"] = "rules"
        return Route(**{**again.__dict__, "router": "model"}), meta
    return decided, meta


def route(question: str, model: Callable[[str], dict] | None = None) -> Route:
    """The one-call form: rules decide, or the model does; never raises to the UI."""
    return route_with_meta(question, model=model)[0]
