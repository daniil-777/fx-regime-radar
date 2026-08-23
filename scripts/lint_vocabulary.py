#!/usr/bin/env python3
"""No machinery word may reach a customer surface, in any locale (phase 43).

Engineers find the machinery fascinating and customers do not. Worse, a customer reading "querying
cube (142 ms)" does not learn that the system is fast and careful — they learn that it is
complicated and that something might be failing. The words below are ours, not theirs.

Scanned: the widget's user-visible strings, the registry's captions and ARIA labels in EN/DE/FR, the
answer packs' speech, and the archive's spoken sentences. Not scanned: comments, code identifiers,
operator surfaces and metric names, which are allowed — and required — to say exactly what they mean.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Machinery vocabulary. Each of these has a customer-facing synonym, or belongs only in a trace.
BANNED = [
    "slip",
    "retrieval",
    "retriever",
    "embedding",
    "token",
    "latency",
    "cache",
    "cached",
    "query",
    "queried",
    "querying",
    "endpoint",
    "payload",
    "schema",
    "bm25",
    # NOT bare "index": a macro uncertainty index and a communication tone index are things a
    # treasurer says. The machinery sense always appears qualified, so ban the phrases instead —
    # a banned-word list that cries wolf on domain vocabulary gets switched off within a week.
    "search index",
    "retrieval index",
    "vector index",
    "classifier",
    "inference",
    "prompt",
    "parquet",
    "duckdb",
    "rollup",
    "pipeline stage",
    "tool call",
    "room",
    "ms)",
    "milliseconds",
]
# Words that are legitimate in customer copy despite containing a banned substring, or that are
# domain vocabulary a treasurer uses. Checked as whole words, so these are exemptions by meaning.
ALLOWED_EXACT = {
    "indexed",  # "the index" as a market term never appears; this is defensive
}

WIDGET = ROOT / "rust/fxradar-serve/static/avatar.html"
REGISTRY = ROOT / "config/visual_registry.yaml"
PACKS = ROOT / "data/answer_packs.json"
ARCHIVE_RS = ROOT / "rust/fxradar-serve/src/archive.rs"


def customer_strings() -> list[tuple[str, str]]:
    """(where, text) for every string a customer can actually read."""
    out: list[tuple[str, str]] = []

    if WIDGET.exists():
        html = WIDGET.read_text()
        # visible text nodes and the wait-line / status tables, not the code around them
        for m in re.finditer(r">([^<>{}\n]{8,})<", html):
            out.append(("widget", m.group(1)))
        for m in re.finditer(r'(?:addMsg|textContent\s*=|placeholder=")\s*"([^"]{8,})"', html):
            out.append(("widget", m.group(1)))

    if REGISTRY.exists():
        import yaml  # noqa: PLC0415

        doc = yaml.safe_load(REGISTRY.read_text())
        for card in doc.get("cards", []):
            for field in ("caption", "aria"):
                for locale, text in (card.get(field) or {}).items():
                    out.append((f"registry:{card['id']}:{field}:{locale}", str(text)))

    if PACKS.exists():
        packs = json.loads(PACKS.read_text()).get("packs", {})
        for key, pack in packs.items():
            for variant, text in (pack.get("speech") or {}).items():
                out.append((f"pack:{key}:{variant}", str(text)))

    if ARCHIVE_RS.exists():
        # the archive's spoken sentences are string literals inside format! calls
        for m in re.finditer(r'"([^"\\\n]{20,})"', ARCHIVE_RS.read_text()):
            text = m.group(1)
            if any(c.isalpha() for c in text) and " " in text:
                out.append(("archive", text))

    return out


def offenders() -> list[str]:
    found: list[str] = []
    for where, text in customer_strings():
        low = text.lower()
        words = set(re.findall(r"[a-zà-ÿ]+", low))
        for banned in BANNED:
            if " " in banned or ")" in banned:
                hit = banned in low
            else:
                hit = banned in words and banned not in ALLOWED_EXACT
            if hit:
                found.append(f"{where}: {banned!r} in {text[:90]!r}")
                break
    return found


def main() -> int:
    bad = offenders()
    if bad:
        print("lint-vocabulary: machinery words on a customer surface")
        for line in bad[:25]:
            print(f"  {line}")
        if len(bad) > 25:
            print(f"  … and {len(bad) - 25} more")
        return 1
    n = len(customer_strings())
    print(f"lint-vocabulary: ok — {n} customer-facing strings, no machinery vocabulary")
    return 0


if __name__ == "__main__":
    sys.exit(main())
