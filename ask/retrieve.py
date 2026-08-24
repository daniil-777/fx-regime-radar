"""Official-document retrieval: Tavily, allow-listed in the payload, cached per day.

The search string is built by the server from the slip alone — user text never enters a Tavily
call, which is what makes the page injection-proof end to end: nothing a web page says can reach
a model (no model runs after retrieval), and nothing a user types can steer the search.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import requests

from ask import config as askcfg
from ask.rules import Route

ALLOWLIST = ["snb.ch", "ecb.europa.eu", "federalreserve.gov", "bankofengland.co.uk", "bis.org"]

_INSTITUTION_NAMES = {
    "SNB": "Swiss National Bank",
    "ECB": "European Central Bank",
    "Fed": "Federal Reserve",
    "BoE": "Bank of England",
    "BIS": "Bank for International Settlements",
}
_DOC_WORDS = {
    "decision": "monetary policy decision",
    "press_release": "press release",
    "speech": "speech",
    "minutes": "minutes",
    "none": "monetary policy",
}
_TIME_RANGE = {"today": "day", "week": "week", "month": "month"}


@dataclass(frozen=True)
class Evidence:
    url: str
    domain: str
    title: str
    seen_date: str  # fetch date, UTC; publication dates are not extracted in this phase
    passage: str
    content_sha256: str
    receipt_id: str
    credits: float
    latency_ms: dict


def build_search_payload(route: Route) -> dict:
    """Slip-only search body. Asserted by a unit test, not requested in a prompt."""
    name = _INSTITUTION_NAMES.get(route.institution, _INSTITUTION_NAMES["SNB"])
    body = {
        "query": f"{name} {_DOC_WORDS.get(route.doc_type, _DOC_WORDS['none'])}",
        "search_depth": "basic",
        "topic": "general",
        "include_domains": ALLOWLIST,
        "max_results": 3,
        "include_answer": False,
        "include_raw_content": False,
        "include_usage": True,
    }
    if route.window in _TIME_RANGE:
        body["time_range"] = _TIME_RANGE[route.window]
    return body


def _cache_path(route: Route, day: str):
    return askcfg.CACHE_DIR / f"{day}_{route.institution}_{route.doc_type}_{route.window}.json"


def pick_passage(text: str, route: Route) -> str:
    """Deterministic: keyword-scored paragraphs, ties to the earliest, cut before 600 chars."""
    keywords = [
        w.lower()
        for w in (
            route.institution,
            _INSTITUTION_NAMES.get(route.institution, ""),
            *_DOC_WORDS.get(route.doc_type, "").split(),
            "policy rate",
            "interest rate",
        )
        if w
    ]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return ""
    best = max(
        paragraphs, key=lambda p: (sum(k in p.lower() for k in keywords), -paragraphs.index(p))
    )
    if len(best) <= 600:
        return best
    cut = best[:600]
    end = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    return cut[: end + 1] if end > 0 else cut


def find_official(
    route: Route, search=None, extract=None, day: str | None = None
) -> Evidence | None:
    """One allow-listed search, one extract, per-day cache. Any failure returns None."""
    day = day or datetime.now(UTC).strftime("%Y%m%d")
    cache = _cache_path(route, day)
    if cache.exists():
        stored = json.loads(cache.read_text())
        stored["latency_ms"] = {**stored.get("latency_ms", {}), "cache_hit": True}
        return Evidence(**stored)
    try:
        key = askcfg.tavily_key()
        payload = build_search_payload(route)
        t0 = time.perf_counter()
        if search is None:  # pragma: no cover - live path, never in pytest
            if not key:
                return None
            r = requests.post(
                askcfg.TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                timeout=askcfg.SEARCH_TIMEOUT_S,
            )
            r.raise_for_status()
            found = r.json()
        else:
            found = search(payload)
        t_search = (time.perf_counter() - t0) * 1000
        results = found.get("results") or []
        if not results:
            return None
        top = results[0]
        domain = top["url"].split("/")[2].removeprefix("www.")
        if domain not in ALLOWLIST:
            return None
        t1 = time.perf_counter()
        if extract is None:  # pragma: no cover - live path, never in pytest
            r2 = requests.post(
                askcfg.TAVILY_EXTRACT_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={"urls": [top["url"]], "extract_depth": "basic"},
                timeout=askcfg.EXTRACT_TIMEOUT_S,
            )
            r2.raise_for_status()
            extracted = r2.json()
        else:
            extracted = extract(top["url"])
        t_extract = (time.perf_counter() - t1) * 1000
        raw = (extracted.get("results") or [{}])[0].get("raw_content") or ""
        if not raw:
            return None
        usage = found.get("usage") or {}
        ev = Evidence(
            url=top["url"],
            domain=domain,
            title=top.get("title", ""),
            seen_date=datetime.now(UTC).strftime("%d %b %Y"),
            passage=pick_passage(raw, route),
            content_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            receipt_id=str(found.get("request_id", "")),
            credits=float(usage.get("credits", 0) or 0),
            latency_ms={"search": round(t_search, 1), "extract": round(t_extract, 1)},
        )
        askcfg.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(asdict(ev), sort_keys=True))
        return ev
    except Exception:
        return None


def latest_cached(institution: str) -> Evidence | None:
    """Newest cached evidence for an institution (refusal cards borrow its receipts)."""
    if not askcfg.CACHE_DIR.exists():
        return None
    hits = sorted(askcfg.CACHE_DIR.glob(f"*_{institution}_*.json"), reverse=True)
    for h in hits:
        try:
            return Evidence(**json.loads(h.read_text()))
        except Exception:
            continue
    return None
