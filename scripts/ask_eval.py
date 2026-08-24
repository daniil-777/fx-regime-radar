#!/usr/bin/env python3
"""Live ask-router evaluation (network; never in CI) — `make ask-eval`.

Pre-registered targets, recorded before any run: >= 27/30 correct routes; 0 gate violations;
rules p50 < 5 ms; model p50 < 1500 ms; official_fact end-to-end p50 < 3000 ms. If a target
fails, the number is the point: it goes to the CHANGELOG untuned.

The model lane is optional: rule (d) decides every registered shape deterministically, so a
keyless run measures rules and retrieval and records "model: not run". When a lane exists
(NEBIUS_API_KEY, else ANTHROPIC_API_KEY), the model is forced on every question — even where
rules decided — so rules-versus-model agreement is measured. Writes docs/ask-eval.md.
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
from ask.route import default_model_lane, parse_model_slip, route_with_meta  # noqa: E402

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
    if not askcfg.tavily_key():
        raise SystemExit("ask-eval needs TAVILY_API_KEY (env or .streamlit/secrets.toml)")
    lane = default_model_lane()  # optional: rules decide every registered shape without a key
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
    lat: dict[str, list[float]] = {"rules": [], "model": [], "fact": []}
    confusion: dict[str, dict[str, int]] = {}
    for row in rows:
        q, want = row["q"], row["kind"]
        t0 = time.perf_counter()
        routed, meta = route_with_meta(q)
        lat["rules"].append(meta["latency_rules_ms"])
        if lane is not None:  # forced model call for the agreement table
            t1 = time.perf_counter()
            try:
                model_kind = parse_model_slip(lane[1](q)).kind
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

    kinds = sorted({k for v in confusion.values() for k in v} | set(confusion))
    model_line = (
        f"model {p(lat['model'], 50):.0f}/{p(lat['model'], 95):.0f}"
        if lat["model"]
        else "model — (no lane)"
    )
    model_pass = (
        ("PASS" if p(lat["model"], 50) < TARGETS["model_p50_ms"] else "FAIL")
        if lat["model"]
        else "NOT RUN (no model key)"
    )
    fact_pass = (
        "PASS" if (not lat["fact"] or p(lat["fact"], 50) < TARGETS["fact_p50_ms"]) else "FAIL"
    )
    lines = [
        "# Ask router — live evaluation",
        "",
        f"model `{lane[0] if lane else 'none — rules-only run (no model key configured)'}` · "
        f"prompt `{askcfg.PROMPT_VERSION}` · git `{sha}` · "
        f"{datetime.now(UTC):%Y-%m-%d %H:%M UTC} · credits {credits:g}",
        "",
        f"Route accuracy: **{correct}/30** (target ≥ {TARGETS['routes']}) · gate violations: "
        f"**{gates}** (target {TARGETS['gates']}) · rules-vs-model agreement: "
        + (f"{agree_hit}/{agree_n}" if lane else "not measured (no model key)"),
        "",
        "| expected \\ got | " + " | ".join(kinds) + " |",
        "|" + "---|" * (len(kinds) + 1),
    ]
    for want in sorted(confusion):
        lines.append(
            "| " + want + " | " + " | ".join(str(confusion[want].get(k, 0)) for k in kinds) + " |"
        )
    lines += [
        "",
        f"latency p50/p95 ms — rules {p(lat['rules'], 50):.2f}/{p(lat['rules'], 95):.2f} · "
        f"{model_line} · official_fact end-to-end {p(lat['fact'], 50):.0f}/{p(lat['fact'], 95):.0f}",
        "",
        f"Pre-registered pass: routes {'PASS' if correct >= TARGETS['routes'] else 'FAIL'} · "
        f"gates {'PASS' if gates == TARGETS['gates'] else 'FAIL'} · "
        f"rules p50 {'PASS' if p(lat['rules'], 50) < TARGETS['rules_p50_ms'] else 'FAIL'} · "
        f"model p50 {model_pass} · fact p50 {fact_pass}",
        "",
        "_Educational tool. Not investment advice._",
    ]
    out = ROOT / "docs" / "ask-eval.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
