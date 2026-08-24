#!/usr/bin/env python3
"""Live ask-router evaluation (network; never in CI) — `make ask-eval`.

Pre-registered targets, recorded before any run: >= 27/30 correct routes; 0 gate violations;
rules p50 < 5 ms; model p50 < 1500 ms; official_fact end-to-end p50 < 3000 ms. If a target
fails, the number is the point: it goes to the CHANGELOG untuned.

Forces the model call on every question (even where rules decided) so rules-versus-model
agreement is measured, and writes docs/ask-eval.md with the tables and the pinned header.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from ask import config as askcfg  # noqa: E402
from ask import render as R  # noqa: E402
from ask import retrieve as RET  # noqa: E402
from ask.route import _call_token_factory, parse_model_slip, route_with_meta  # noqa: E402

from fxradar import config as fxconfig  # noqa: E402

TARGETS = {
    "routes": 27,
    "gates": 0,
    "rules_p50_ms": 5.0,
    "model_p50_ms": 1500.0,
    "fact_p50_ms": 3000.0,
}


def p(vals, q):
    return statistics.quantiles(vals, n=100)[q - 1] if len(vals) > 1 else (vals[0] if vals else 0.0)


def main() -> None:
    if not askcfg.nebius_key() or not askcfg.tavily_key():
        raise SystemExit(
            "ask-eval needs NEBIUS_API_KEY and TAVILY_API_KEY (env or .streamlit/secrets.toml)"
        )
    import pandas as pd

    rows = [
        json.loads(x)
        for x in (ROOT / "tests/fixtures/ask_routes.jsonl").read_text().splitlines()
        if x.strip()
    ]
    reg = pd.read_parquet(fxconfig.REGIMES_PATH)
    latest = reg[reg["date"] == reg["date"].max()]
    stats = latest[latest["pair"] == fxconfig.PAIRS[0]].iloc[0].to_dict()
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()

    correct, gates, agree_n, agree_hit, credits = 0, 0, 0, 0, 0.0
    lat = {"rules": [], "model": [], "fact": []}
    confusion: dict[str, dict[str, int]] = {}
    for row in rows:
        q, want = row["q"], row["kind"]
        t0 = time.perf_counter()
        routed, meta = route_with_meta(q)
        lat["rules"].append(meta["latency_rules_ms"])
        # force the model even where rules decided, for the agreement table
        t1 = time.perf_counter()
        try:
            model_kind = parse_model_slip(_call_token_factory(q)).kind
        except Exception:
            model_kind = "unclear"
        lat["model"].append((time.perf_counter() - t1) * 1000)
        if routed.router == "rules":
            agree_n += 1
            agree_hit += int(model_kind == routed.kind)
        evidence = None
        if routed.kind == "official_fact":
            evidence = RET.find_official(routed)
            if evidence is not None:
                credits += evidence.credits
            lat["fact"].append((time.perf_counter() - t0) * 1000)
        card = R.apply_gates(
            routed,
            R.render(routed, evidence, stats, list(fxconfig.PAIRS), "2.41.0"),
            evidence,
            stats,
            "2.41.0",
        )
        gates += int(card.gate != "none")
        correct += int(routed.kind == want)
        confusion.setdefault(want, {}).setdefault(routed.kind, 0)
        confusion[want][routed.kind] += 1

    lines = [
        "# Ask router — live evaluation",
        "",
        f"model `{askcfg.ASK_MODEL}` · prompt `{askcfg.PROMPT_VERSION}` · git `{sha}` · "
        f"{datetime.now(UTC):%Y-%m-%d %H:%M UTC} · credits {credits:g}",
        "",
        f"Route accuracy: **{correct}/30** (target ≥ {TARGETS['routes']}) · gate violations: "
        f"**{gates}** (target {TARGETS['gates']}) · rules-vs-model agreement: {agree_hit}/{agree_n}",
        "",
        "| expected \\ got | "
        + " | ".join(sorted({k for v in confusion.values() for k in v} | set(confusion)))
        + " |",
    ]
    kinds = sorted({k for v in confusion.values() for k in v} | set(confusion))
    lines.append("|" + "---|" * (len(kinds) + 1))
    for want in sorted(confusion):
        lines.append(
            "| " + want + " | " + " | ".join(str(confusion[want].get(k, 0)) for k in kinds) + " |"
        )
    lines += [
        "",
        f"latency p50/p95 ms — rules {p(lat['rules'],50):.1f}/{p(lat['rules'],95):.1f} · "
        f"model {p(lat['model'],50):.0f}/{p(lat['model'],95):.0f} · "
        f"official_fact end-to-end {p(lat['fact'],50):.0f}/{p(lat['fact'],95):.0f}",
        "",
        f"Pre-registered pass: routes {'PASS' if correct >= TARGETS['routes'] else 'FAIL'} · "
        f"gates {'PASS' if gates == TARGETS['gates'] else 'FAIL'} · "
        f"rules p50 {'PASS' if p(lat['rules'],50) < TARGETS['rules_p50_ms'] else 'FAIL'} · "
        f"model p50 {'PASS' if p(lat['model'],50) < TARGETS['model_p50_ms'] else 'FAIL'} · "
        f"fact p50 {'PASS' if (not lat['fact'] or p(lat['fact'],50) < TARGETS['fact_p50_ms']) else 'FAIL'}",
        "",
        "_Educational tool. Not investment advice._",
    ]
    out = ROOT / "docs" / "ask-eval.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
