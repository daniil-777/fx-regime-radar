#!/usr/bin/env python3
"""Score the golden set and write a pinned report (phase 39).

Runs hermetically: retrieval is computed here in Python against the snapshot's own registry, and
every other metric is scored over RECORDED system outputs (`eval/fixtures/responses.jsonl`). No
network, no model, no clock dependence — so CI can run it in seconds and a result can be compared
with last week's.

The report header pins model id and version, judge, prompt version, gate-rules version, registry
version, snapshot hash, git SHA and seeds. `docs/eval_process.md` makes the rule explicit and
`--diff` enforces it: two reports whose pinned fields differ are not comparable, and the tool
refuses to subtract them rather than printing a reassuring delta that means nothing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

import harness as H  # noqa: E402

from fxradar import visuals as V  # noqa: E402

GATE_TO_ROUTE = {
    "pass": "answer",
    "regenerated": "answer",
    "open:ungrounded": "answer",
    "refused:direction": "refuse_direction",
    "refused:advice": "refuse_advice",
    "refused:off_topic": "refuse_off_topic",
    "refused:not_in_pack": "refuse_not_in_pack",
    "blocked": "refuse_not_in_pack",
}
PINNED = (
    "model",
    "model_version",
    "judge",
    "prompt_version",
    "gate_rules_version",
    "registry_version",
    "snapshot_hash",
    "git_sha",
    "seed",
)


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def pinned_header(snap: H.Snapshot, fixtures: dict) -> dict:
    any_fix = next(iter(fixtures.values()), {})
    return {
        "model": any_fix.get("model", "keyless-templates"),
        "model_version": any_fix.get("model_version", "n/a (no ANTHROPIC_API_KEY at record time)"),
        "judge": "not run",
        "prompt_version": any_fix.get("prompt_version", "v2"),
        "gate_rules_version": any_fix.get("gate_rules_version", "phase-38"),
        "registry_version": json.loads((snap.path / "data" / "visual_index.json").read_text()).get(
            "registry_version", "—"
        ),
        "snapshot_hash": snap.hash(),
        "snapshot": snap.label,
        "git_sha": git_sha(),
        "seed": "0 (deterministic: no sampling in the scored path)",
    }


def score(snap: H.Snapshot, items: list[H.GoldItem], fixtures: dict) -> dict:
    reg = V.load_registry(snap.path / "config" / "visual_registry.yaml")
    per_family: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    per_locale: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    failures: list[dict] = []
    latencies: list[float] = []

    for item in items:
        fam, loc = item.family, item.locale
        fix = fixtures.get(item.id)

        # --- retrieval, computed here: does the expected card reach the candidate slice? --------
        if item.expected_primary_card:
            query = (
                (item.turn_context + " " + item.question) if item.turn_context else item.question
            )
            ranked = [c.id for c in reg.retrieve(query, k=len(reg.built()))]
            r6 = H.recall_at_k(ranked, item.expected_primary_card, 6)
            per_family[fam]["recall@6"].append(r6)
            per_locale[loc]["recall@6"].append(r6)
            per_family[fam]["mrr"].append(H.reciprocal_rank(ranked, item.expected_primary_card))
            if item.expected_support_cards:
                per_family[fam]["ndcg@6"].append(
                    H.ndcg(ranked, set(item.expected_support_cards) | {item.expected_primary_card})
                )
            if not r6:
                failures.append(
                    {
                        "id": item.id,
                        "cause": "retrieval",
                        "detail": f"{item.expected_primary_card} not in top 6: {ranked[:4]}",
                    }
                )

        if not fix:
            per_family[fam]["recorded"].append(0.0)
            continue
        per_family[fam]["recorded"].append(1.0)
        text = fix.get("text", "")
        gate = fix.get("gate", "")
        board = fix.get("board") or []
        latencies.append(float(fix.get("latency_ms") or 0))

        # --- routing -----------------------------------------------------------------------------
        got_route = GATE_TO_ROUTE.get(gate, "answer")
        ok_route = float(got_route == item.expected_route)
        per_family[fam]["routing"].append(ok_route)
        per_locale[loc]["routing"].append(ok_route)
        if not ok_route:
            failures.append(
                {
                    "id": item.id,
                    "cause": "routing",
                    "detail": f"expected {item.expected_route}, got {got_route} ({gate})",
                }
            )

        # --- numeric exactness: the most important number in the suite ---------------------------
        for gv in item.gold_values:
            expected = item.resolved[gv["name"]]
            hit = float(H.number_matches(expected, text, loc, item.tolerance))
            per_family[fam]["numeric"].append(hit)
            per_locale[loc]["numeric"].append(hit)
            if not hit:
                failures.append(
                    {
                        "id": item.id,
                        "cause": "generation/missing data",
                        "detail": f"{gv['name']}={expected!r} ({gv['source_ref']}) absent "
                        f"from: {text[:70]}",
                    }
                )

        # --- banned vocabulary -------------------------------------------------------------------
        low = text.lower()
        bad = [w for w in item.must_not_contain if w.lower() in low]
        per_family[fam]["clean"].append(float(not bad))
        if bad:
            failures.append(
                {"id": item.id, "cause": "gate", "detail": f"said banned word(s) {bad}"}
            )

        # --- card selection + provenance ---------------------------------------------------------
        if item.expected_primary_card:
            got = board[0]["component"] if board else ""
            sel = float(got == item.expected_primary_card)
            per_family[fam]["selection"].append(sel)
            if not sel and got:
                failures.append(
                    {
                        "id": item.id,
                        "cause": "selection",
                        "detail": f"rendered {got}, expected {item.expected_primary_card}",
                    }
                )
        wanted_visual = bool(item.expected_primary_card)
        per_family[fam]["coverage"].append(
            float(bool(board)) if wanted_visual else float(not board)
        )
        for card in board:
            has_record = bool(card.get("asof")) and card.get("data") not in (None, {}, [])
            per_family[fam]["provenance"].append(float(has_record))
            if not has_record:
                failures.append(
                    {
                        "id": item.id,
                        "cause": "provenance",
                        "detail": f"{card.get('component')} carried no as-of or no data",
                    }
                )

        # --- reference resolution, the multi-turn question -----------------------------------------
        if fam == "multi_turn_followup":
            target = item.notes.upper()
            pairs = [
                p
                for p in ("EURUSD", "USDCHF", "GBPUSD", "USDJPY", "USDRUB", "BTC-USD")
                if p in target or p.replace("-", "/") in target
            ]
            if pairs:
                resolved_ok = float(
                    any(
                        p.replace("-", "").lower() in text.lower().replace("/", "").replace("-", "")
                        for p in pairs
                    )
                )
                per_family[fam]["reference_resolution"].append(resolved_ok)
                if not resolved_ok:
                    failures.append(
                        {
                            "id": item.id,
                            "cause": "reference resolution",
                            "detail": f"follow-up should resolve to {pairs}, said: {text[:60]}",
                        }
                    )

    return {
        "per_family": per_family,
        "per_locale": per_locale,
        "failures": failures,
        "latencies": latencies,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def render(snap: H.Snapshot, items: list[H.GoldItem], fixtures: dict, res: dict) -> str:
    head = pinned_header(snap, fixtures)
    pf, pl = res["per_family"], res["per_locale"]
    fam_order = [f for f in H.FAMILY_MINIMUMS if f in pf] + [
        f for f in pf if f not in H.FAMILY_MINIMUMS
    ]
    out: list[str] = []
    w = out.append
    w("# Evaluation baseline")
    w("")
    w(
        f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}Z from "
        f"`eval/snapshot/{snap.label}`. Scored over recorded outputs — hermetic, no network._"
    )
    w("")
    w("## Pinned versions")
    w("")
    w("A change to any field below invalidates comparison: re-baseline before reading a delta.")
    w("")
    w("| field | value |")
    w("|---|---|")
    for k in (
        "model",
        "model_version",
        "judge",
        "prompt_version",
        "gate_rules_version",
        "registry_version",
        "snapshot",
        "snapshot_hash",
        "git_sha",
        "seed",
    ):
        w(f"| {k} | `{head[k]}` |")
    w("")
    recorded = sum(1 for i in items if i.id in fixtures)
    w(
        f"**{len(items)} golden items**, {recorded} with recorded outputs "
        f"({recorded / max(1, len(items)):.0%}). "
        f"{sum(len(i.gold_values) for i in items)} computed gold values across "
        f"{sum(1 for i in items if i.gold_values)} items."
    )
    w("")
    w("## By family")
    w("")
    w(
        "| family | n | recall@6 | MRR | routing | no banned words | numeric | selection | coverage | provenance |"
    )
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    fmt = lambda v: "—" if v != v else f"{v:.0%}"  # noqa: E731
    for fam in fam_order:
        m = pf[fam]
        n = len(m.get("recorded", [])) or len(m.get("recall@6", []))
        mrr = _mean(m.get("mrr", []))
        w(
            f"| `{fam}` | {n} | {fmt(_mean(m.get('recall@6', [])))} | "
            f"{'—' if mrr != mrr else f'{mrr:.2f}'} | {fmt(_mean(m.get('routing', [])))} | "
            f"{fmt(_mean(m.get('clean', [])))} | "
            f"{fmt(_mean(m.get('numeric', [])))} | {fmt(_mean(m.get('selection', [])))} | "
            f"{fmt(_mean(m.get('coverage', [])))} | {fmt(_mean(m.get('provenance', [])))} |"
        )
    w("")
    w("## By locale")
    w("")
    w("| locale | n | recall@6 | routing | numeric |")
    w("|---|---:|---:|---:|---:|")
    for loc in ("en", "de", "fr"):
        m = pl.get(loc, {})
        n = sum(1 for i in items if i.locale == loc)
        w(
            f"| {loc} | {n} | {fmt(_mean(m.get('recall@6', [])))} | "
            f"{fmt(_mean(m.get('routing', [])))} | {fmt(_mean(m.get('numeric', [])))} |"
        )
    w("")
    w("## Compliance families — 100% required")
    w("")
    w("Two different things are measured here and conflating them would misread the system badly.")
    w("**Leak** asks whether a banned claim actually reached the user — a direction statement, a")
    w(
        "recommendation. **Named the refusal** asks whether the system said *why* it would not answer."
    )
    w(
        "A leak is a compliance failure; an unnamed refusal is a quality failure that reads as evasion."
    )
    w("")
    w("| family | named the refusal | no banned words | verdict |")
    w("|---|---:|---:|---|")
    for fam in H.MUST_BE_PERFECT:
        m = pf.get(fam, {})
        route_v, clean_v = _mean(m.get("routing", [])), _mean(m.get("clean", []))
        if route_v != route_v:
            verdict = "—"
        elif clean_v == clean_v and clean_v < 1.0:
            verdict = "**LEAK — compliance failure**"
        elif route_v < 1.0:
            verdict = "**FAIL (quality): answered instead of refusing**"
        else:
            verdict = "PASS"
        w(f"| `{fam}` | {fmt(route_v)} | {fmt(clean_v)} | {verdict} |")
    w("")
    lat = res["latencies"]
    w("## Latency")
    w("")
    w("| metric | ms |")
    w("|---|---:|")
    for label, q in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99)):
        w(f"| {label} | {H.percentile(lat, q):.0f} |")
    w(f"| max | {max(lat) if lat else 0:.0f} |")
    w("")
    w(
        "_Server-side answer latency only, keyless path. Cost is CHF 0 per answer in this "
        "configuration: no model call is made. Both figures move once a key is configured, which is "
        "itself a pinned-field change requiring a re-baseline._"
    )
    w("")
    w("## Judge")
    w("")
    w(
        "Not run. The judge metric is bounded to phrasing and relevance and requires a second model; "
        "with no key configured there is nothing to measure and no κ to report. Reporting an "
        "unvalidated judge score would be worse than omitting it — per the phase rule, a judge below "
        "κ 0.6 is dropped rather than dressed up."
    )
    w("")
    causes: dict[str, int] = defaultdict(int)
    for f in res["failures"]:
        causes[f["cause"]] += 1
    w("## Failures by root cause")
    w("")
    w("| cause | count |")
    w("|---|---:|")
    for cause, n in sorted(causes.items(), key=lambda kv: -kv[1]):
        w(f"| {cause} | {n} |")
    w("")
    w("### The ten worst")
    w("")
    for f in res["failures"][:10]:
        w(f"- **{f['id']}** — _{f['cause']}_ — {f['detail']}")
    w("")
    w("_Educational tool. Not investment advice._")
    return "\n".join(out) + "\n"


def diff(a: Path, b: Path) -> int:
    """Refuse to compare reports whose pinned fields differ."""

    def header(p: Path) -> dict:
        out = {}
        for line in p.read_text().splitlines():
            if line.startswith("| ") and line.count("|") == 3 and "`" in line:
                _, k, v, _ = [c.strip() for c in line.split("|")]
                out[k] = v.strip("`")
        return out

    ha, hb = header(a), header(b)
    drifted = [k for k in PINNED if k in ha and k in hb and ha[k] != hb[k]]
    if drifted:
        print("REFUSING to diff: pinned fields differ — re-baseline first.")
        for k in drifted:
            print(f"  {k}: {ha[k]!r} -> {hb[k]!r}")
        return 2
    print("pinned fields match; reports are comparable.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", help="snapshot label (default: newest)")
    ap.add_argument("--out", default="reports/eval_baseline.md")
    ap.add_argument("--fixtures", default=str(H.FIXTURES_PATH))
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"), help="compare two reports")
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero on a REGRESSION against eval/baseline_thresholds.json",
    )
    ap.add_argument(
        "--write-thresholds",
        action="store_true",
        help="record the current numbers as the floor CI must not fall below",
    )
    args = ap.parse_args()

    if args.diff:
        raise SystemExit(diff(Path(args.diff[0]), Path(args.diff[1])))

    snap = H.load_snapshot(args.snapshot)
    items = H.load_golden(snap)
    fixtures = H.load_fixtures(Path(args.fixtures))
    res = score(snap, items, fixtures)
    report = render(snap, items, fixtures, res)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(
        f"wrote {out.relative_to(ROOT)} — {len(items)} items, "
        f"{len(fixtures)} recorded, {len(res['failures'])} failures"
    )

    # The floor, not the goal. A suite that fails on day one because the system is not yet perfect
    # teaches the team to ignore it; a suite that fails the moment something gets WORSE gets read.
    # The 100% compliance target lives in the report, where it is tracked rather than enforced.
    thresholds_path = ROOT / "eval" / "baseline_thresholds.json"
    current = {
        f"{fam}.{metric}": _mean(vals)
        for fam, metrics in res["per_family"].items()
        for metric, vals in metrics.items()
        if vals and metric in ("routing", "clean", "numeric", "recall@6", "selection", "provenance")
    }
    if args.write_thresholds:
        thresholds_path.write_text(
            json.dumps(
                {
                    "note": "Floors recorded from the committed baseline. CI fails on a drop, not on "
                    "imperfection. Re-record only alongside a deliberate re-baseline.",
                    "generated_from": args.out,
                    "floors": {k: round(v, 4) for k, v in current.items()},
                },
                indent=1,
            )
        )
        print(f"wrote {thresholds_path.relative_to(ROOT)}: {len(current)} floors")

    if args.check:
        if not thresholds_path.exists():
            print("no baseline_thresholds.json — run with --write-thresholds first")
            raise SystemExit(1)
        floors = json.loads(thresholds_path.read_text())["floors"]
        TOL = 0.02  # a two-point slip is noise in a 255-item suite; a real regression is bigger
        drops = [
            f"{k}: {floors[k]:.0%} -> {current[k]:.0%}"
            for k in floors
            if k in current and current[k] < floors[k] - TOL
        ]
        leaks = [
            fam
            for fam in H.MUST_BE_PERFECT
            if (v := _mean(res["per_family"].get(fam, {}).get("clean", []))) == v and v < 1.0
        ]
        if leaks:
            print("COMPLIANCE LEAK — a banned claim reached the user: " + ", ".join(leaks))
            raise SystemExit(1)
        if drops:
            print("REGRESSION against the committed baseline:")
            for d in drops:
                print(f"  {d}")
            raise SystemExit(1)
        print(f"no regression against {len(floors)} recorded floors; no compliance leak")


if __name__ == "__main__":
    main()
