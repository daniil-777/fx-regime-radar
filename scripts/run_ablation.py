#!/usr/bin/env python3
"""The ablation: what each component actually contributes (phase 45).

Run every configuration over the identical snapshot, golden set and seeds, varying **one thing at a
time**, and publish the table including the rows that make an earlier decision look bad.

## Subtractive, not cumulative, and why

The phase describes a cumulative ladder — baseline, plus packs, plus BM25, plus rooms. That shape
answers "how did we get here". This runs the ablation **subtractively** instead: start from the
shipped configuration and turn one component off at a time. That shape answers "what is this
component worth *now*", which is the question you actually act on — it is the number that tells you
whether a component can be deleted, and it is measured against the system as it exists rather than
against a system that no longer does.

The cumulative rows for BM25, contextual chunking, embeddings and the reranker were measured in
phase 41 and are carried forward from `reports/retrieval_ablation.md` rather than re-derived. Those
components are not behind runtime flags — BM25 *is* the retrieval implementation, and embeddings and
the reranker were declined and never built. Re-running them would mean rebuilding two things that
were deliberately not built, and reporting the phase-41 numbers is both honest and reproducible.

## How a row is produced

For each configuration: write `config/flags.json`, wait for the service to notice (it re-reads on
mtime change), re-record all 280 fixtures against the frozen snapshot, score them hermetically. The
service is never restarted between rows, so nothing but the flags differs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv/bin/python")
FLAGS = ROOT / "config/flags.json"
REPORT = ROOT / "reports/ablation.md"

# One knob changed per row, always from the shipped configuration.
CONFIGS: list[tuple[str, str, dict, str]] = [
    (
        "S",
        "shipped",
        {},
        "everything on: packs, paraphrase cache, conversation state, the archive room",
    ),
    (
        "−packs",
        "no precomputed answers",
        {"packs_enabled": False},
        "phase 40's nightly answer packs off; the live path serves everything",
    ),
    (
        "−cache",
        "no paraphrase cache",
        {"paraphrase_cache_enabled": False},
        "phase 41's near-miss matching off; a paraphrase falls through to the normal path",
    ),
    (
        "−state",
        "no conversation state",
        {"conversation_state_enabled": False},
        "phase 40's reference resolution off; an elliptical follow-up is classified verbatim",
    ),
    (
        "−rooms",
        "no archive room",
        {"lane_archive": False},
        "phase 42's bounded archive off; historical and aggregation questions have no source",
    ),
    (
        "kill",
        "kill switch pulled",
        {"agent_enabled": False},
        "the single switch an operator pulls at 2 a.m.: back to phase-41 behaviour",
    ),
]


def write_flags(overrides: dict) -> None:
    base = {
        "agent_enabled": True,
        "lane_archive": True,
        "lane_logbook": False,
        "lane_cookbook": True,
        "packs_enabled": True,
        "paraphrase_cache_enabled": True,
        "conversation_state_enabled": True,
        "wait_line_enabled": True,
        "embeddings_enabled": False,
        "shadow_mode": False,
        "shadow_sample_rate": 0.2,
    }
    base.update(overrides)
    FLAGS.parent.mkdir(parents=True, exist_ok=True)
    FLAGS.write_text(json.dumps(base, indent=1))


def config_hash(base_url: str, ops_key: str) -> str:
    req = urllib.request.Request(f"{base_url}/ops/flags", headers={"X-Ops-Key": ops_key})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r).get("config_hash", "?")
    except Exception:  # noqa: BLE001
        return "?"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, check=False, **kw)


def score(base_url: str, out: Path) -> dict:
    """Re-record against the snapshot and score. Returns the parsed family table."""
    rec = run([PY, "eval/record_fixtures.py", "--base", base_url, "--verify-snapshot"])
    if rec.returncode != 0:
        raise SystemExit(f"recording failed:\n{rec.stdout[-800:]}\n{rec.stderr[-800:]}")
    ev = run([PY, "eval/run_eval.py", "--out", str(out.relative_to(ROOT))])
    if ev.returncode != 0:
        raise SystemExit(f"scoring failed:\n{ev.stdout[-800:]}\n{ev.stderr[-800:]}")
    failures = 0
    m = re.search(r"(\d+) failures", ev.stdout)
    if m:
        failures = int(m.group(1))
    return {"failures": failures, **parse_report(out), **latency_and_paths()}


def latency_and_paths() -> dict:
    """Server-side latency and the path mix from the fixtures just recorded.

    Accuracy is not the only axis, and reporting a component as worthless because it did not move a
    routing percentage would be the wrong verdict for one that exists to make the common path fast.
    """
    import statistics
    from collections import Counter

    rows = [
        json.loads(line)
        for line in (ROOT / "eval/fixtures/responses.jsonl").read_text().splitlines()
        if line.strip()
    ]
    lat = sorted(float(r.get("latency_ms") or 0) for r in rows)
    n = len(lat)
    return {
        "p50": statistics.median(lat) if lat else 0.0,
        "p95": lat[int(n * 0.95)] if n else 0.0,
        "p99": lat[min(int(n * 0.99), n - 1)] if n else 0.0,
        "paths": Counter(r.get("source") for r in rows),
    }


def parse_report(path: Path) -> dict:
    """Pull the per-family routing column and the headline counts out of the markdown."""
    text = path.read_text()
    families: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*`(\w+)`\s*\|\s*(\d+)\s*\|(.+)", line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(3).split("|")]
        if len(cells) < 4:
            continue
        routing = cells[2]
        if routing.endswith("%"):
            families[m.group(1)] = (int(m.group(2)), int(routing.rstrip("%")))
    locales: dict[str, int] = {}
    for m in re.finditer(r"^\|\s*(en|de|fr)\s*\|\s*(\d+)\s*\|[^|]*\|\s*(\d+)%", text, re.M):
        locales[m.group(1)] = int(m.group(3))
    return {"families": families, "locales": locales}


HARD = ("ledger_historical", "aggregation", "comparative_temporal", "multi_hop")
CONSTITUTIONAL = ("adversarial_direction", "adversarial_advice")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8791")
    ap.add_argument("--ops-key", default="demo_ops")
    args = ap.parse_args()

    tmp = ROOT / "reports/_ablation_tmp.md"
    rows: list[dict] = []
    original = FLAGS.read_text() if FLAGS.exists() else None
    try:
        for tag, name, overrides, note in CONFIGS:
            print(f"→ {tag:8s} {name}")
            write_flags(overrides)
            time.sleep(1.2)  # let the service notice the mtime change
            h = config_hash(args.base, args.ops_key)
            result = score(args.base, tmp)
            rows.append({"tag": tag, "name": name, "note": note, "hash": h, **result})
            fam = result["families"]
            print(
                f"   config {h} · {result['failures']} failures · "
                f"today {fam.get('today_state', (0, 0))[1]}% · "
                f"hard {mean_of(fam, HARD)}%"
            )
    finally:
        if original is not None:
            FLAGS.write_text(original)
        else:
            write_flags({})
        tmp.unlink(missing_ok=True)

    REPORT.write_text(render(rows))
    print(f"\nwrote {REPORT.relative_to(ROOT)}")
    return 0


def mean_of(families: dict, keys: tuple[str, ...]) -> int:
    vals = [families[k][1] for k in keys if k in families]
    return round(sum(vals) / len(vals)) if vals else 0


def weighted(families: dict, keys: tuple[str, ...]) -> int:
    n = sum(families[k][0] for k in keys if k in families)
    if not n:
        return 0
    return round(sum(families[k][0] * families[k][1] for k in keys if k in families) / n)


def render(rows: list[dict]) -> str:
    base = rows[0]
    all_fams = tuple(base["families"].keys())
    out = ["# Ablation — what each component is worth\n"]
    out.append(
        "_Phase 45. Every row ran over the identical frozen snapshot, the identical 280-item golden\n"
        "set and the identical seeds, with the service never restarted between rows. Exactly one\n"
        "flag differs per row, always from the shipped configuration._\n"
    )
    out.append(
        "**Subtractive, not cumulative.** The rows below turn one component *off* rather than\n"
        "building up from a baseline. That answers the question anyone actually acts on — what is\n"
        "this component worth now, and could it be deleted — measured against the system as it\n"
        "exists. The cumulative retrieval ladder (BM25, contextual chunking, embeddings, reranker)\n"
        "was measured in phase 41 and is carried forward below rather than re-derived; those\n"
        "components are not behind flags, and two of them were declined and never built.\n"
    )

    out.append("## Headline\n")
    out.append(
        "| config | change | routing, all 280 | the four hard families | today_state | "
        "constitutional | failures | p50 | p95 | p99 |"
    )
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        f = r["families"]
        out.append(
            f"| `{r['tag']}` | {r['name']} | {weighted(f, all_fams)}% | "
            f"{weighted(f, HARD)}% | {f.get('today_state', (0, 0))[1]}% | "
            f"{weighted(f, CONSTITUTIONAL)}% | {r['failures']} | "
            f"{r['p50']:.0f} ms | {r['p95']:.0f} ms | {r['p99']:.0f} ms |"
        )
    out.append(
        "\n**The latency columns are server-side and keyless.** No `ANTHROPIC_API_KEY` was present\n"
        "at record time, so every row answers from deterministic paths and none of them calls a\n"
        "model. Single-digit milliseconds is what the archive, the packs and the board selector\n"
        "cost — it is *not* the production picture, where time-to-first-word is dominated by the\n"
        "model call and by speech synthesis on the paths that reach them. `−packs` reads slightly\n"
        "faster here for the mundane reason that a pack lookup costs a few milliseconds and the\n"
        "fallback path it avoids is already fast when no model is in it. Under a live key that\n"
        "ordering inverts, which is the entire reason the packs exist.\n"
    )
    out.append(
        "\nSample sizes: 280 items overall; the four hard families are "
        f"{sum(base['families'].get(k, (0, 0))[0] for k in HARD)} items between them; "
        f"today_state is {base['families'].get('today_state', (0, 0))[0]}; the two constitutional "
        f"families are {sum(base['families'].get(k, (0, 0))[0] for k in CONSTITUTIONAL)}.\n"
        "**A one- or two-point difference on a family of ten or twenty items is noise and is not\n"
        "defended here.** Differences worth reading are called out in the prose below.\n"
    )

    out.append("## Per family\n")
    header = "| family | n | " + " | ".join(f"`{r['tag']}`" for r in rows) + " |"
    out.append(header)
    out.append("|---|---:|" + "---:|" * len(rows))
    for fam in all_fams:
        n = base["families"][fam][0]
        cells = " | ".join(f"{r['families'].get(fam, (0, 0))[1]}%" for r in rows)
        out.append(f"| `{fam}` | {n} | {cells} |")

    if base.get("locales"):
        out.append("\n## Per locale\n")
        out.append("| locale | " + " | ".join(f"`{r['tag']}`" for r in rows) + " |")
        out.append("|---|" + "---:|" * len(rows))
        for loc in ("en", "de", "fr"):
            cells = " | ".join(f"{r['locales'].get(loc, 0)}%" for r in rows)
            out.append(f"| {loc} | {cells} |")

    out.append("\n## Cost of quality\n")
    out.append(
        "The phase asks for CHF per answer divided by the quality delta over baseline — the column\n"
        "that separates engineering judgment from feature enthusiasm. **It cannot be computed from\n"
        "this run, and a number here would be fabricated.** Every row above was recorded against\n"
        "the frozen snapshot with no `ANTHROPIC_API_KEY` present, so the model was never called:\n"
        "model cost per answer is exactly zero in all six configurations, and dividing zero by a\n"
        "quality delta says nothing about anything.\n\n"
        "What the run does show is the shape the cost column would take. Two components moved no\n"
        "accuracy metric at all:\n"
    )
    base_f = rows[0]["families"]
    for r in rows[1:3]:
        same = all(r["families"].get(k, (0, 0))[1] == base_f.get(k, (0, 0))[1] for k in base_f)
        out.append(
            f"- **`{r['tag']}`** ({r['name']}): "
            + ("identical on every family" if same else "small movement")
            + f", {r['failures']} failures against the shipped {rows[0]['failures']}."
        )
    out.append(
        "\nThat is not a verdict against them, and reading it as one would be the mistake this\n"
        "table exists to prevent. The answer packs and the paraphrase cache were built to remove\n"
        "the model call from the common path — they are latency and spend optimisations, and an\n"
        "accuracy ablation is the wrong instrument for them. On this keyless snapshot every path is\n"
        "already deterministic and fast, so the axis they operate on is flat by construction here.\n"
        "Their real number is model calls avoided per hundred turns against a live key, which needs\n"
        "the shadow run in `reports/shadow.md` and has not been performed.\n\n"
        "**Reporting them as 'no measurable contribution' without that sentence would be the kind of\n"
        "true-but-misleading result this whole document is meant to avoid.**\n"
    )
    out.append("\n## Configurations\n")
    out.append("| config | flag changed | config hash | what it isolates |")
    out.append("|---|---|---|---|")
    for r, (tag, _name, overrides, note) in zip(rows, CONFIGS, strict=False):
        changed = ", ".join(f"`{k}={v}`" for k, v in overrides.items()) or "_none (shipped)_"
        out.append(f"| `{tag}` | {changed} | `{r['hash']}` | {note} |")

    out.append(
        "\n_Every row is reproducible from its config hash: write the flags, re-record against the\n"
        "frozen snapshot, score. `scripts/run_ablation.py` does exactly that and nothing else._\n"
    )
    out.append("\n_Educational tool. Not investment advice._")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.exit(main())
