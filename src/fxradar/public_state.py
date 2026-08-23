"""`public/state.json` — the one file the static customer surface fetches (phase 44).

Everything a page needs to render, in a single request, safe to serve to the open internet. This is
a deliberately different artifact from `data/avatar_context.json`: that one carries the FAQ, the
refusal texts, the allowed-number set and a pointer to the knowledge pack, all of which exist to
serve the assistant and none of which a reader needs. Publishing the context pack would have been
easier and would have put our gate configuration on a CDN.

Two properties are load-bearing.

**One fetch.** A page that needs three requests to show the regime has three chances to be slow and
three chances to fail. Everything a treasurer reads in the first three seconds is in this file.

**Safe by test, not by care.** `tests/test_public_state.py` asserts the file carries no key
material, no internal path, no personal data and nothing from the research lab — because this file
will be on a CDN, and "we were careful" is not a property anyone can verify a year from now.

Size is capped at 50 KB uncompressed and the build fails past it, so the artifact cannot quietly
grow into the thing it replaced.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fxradar import config

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
PUBLIC_DIR = config.ROOT / "public"
STATE_PATH = PUBLIC_DIR / "state.json"
MAX_BYTES = 50_000

# Only these fields of a market block travel. An allow-list rather than a deny-list: a field added
# to the context pack next year must be opted in by a person, not published by default.
PAIR_FIELDS = (
    "label",
    "regime",
    "regime_prob",
    "days_in_regime",
    "change_risk_5d",
    "risk_lo",
    "risk_hi",
    "anomaly_pct",
    "agreement",
    "consensus_text",
)
LEDGER_FIELDS = (
    "days_live",
    "n_forecasts",
    "n_resolved",
    "since",
    "live_brier",
    "frozen_brier",
    "frozen_pr_auc",
    "coverage_live",
    "coverage_frozen",
    "chain_head_short",
    "chain_ok",
)


def _round(value: object, places: int) -> object:
    """Round for the wire, keeping None as None. Nulls mean 'not yet', never zero."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), places)
    return value


def build(pack: dict, treasury: dict | None = None) -> dict:
    """The published state, from the context pack the pipeline already wrote."""
    markets: dict[str, dict] = {}
    for name, uni in (pack.get("markets") or {}).items():
        pairs: dict[str, dict] = {}
        for code, blk in (uni.get("pairs") or {}).items():
            row = {k: blk.get(k) for k in PAIR_FIELDS if blk.get(k) is not None}
            for key, places in (
                ("regime_prob", 3),
                ("change_risk_5d", 3),
                ("risk_lo", 3),
                ("risk_hi", 3),
                ("anomaly_pct", 1),
            ):
                if key in row:
                    row[key] = _round(row[key], places)
            pairs[code] = row
        markets[name] = {
            "label": uni.get("label", name),
            "data_through": uni.get("data_through", ""),
            "pairs": pairs,
        }

    # The treasury light and its one-line reason. The full reason paragraph is long and repeats the
    # numbers already on the page; the page shows the light and links to the detail.
    lights: dict[str, dict] = {}
    for code, blk in (treasury or pack.get("treasury") or {}).items():
        if not isinstance(blk, dict):
            continue
        reason = str(blk.get("reason") or "")
        lights[code] = {
            "light": blk.get("light"),
            "reason": reason[:400],
        }

    ledger = {k: (pack.get("ledger") or {}).get(k) for k in LEDGER_FIELDS}

    return {
        "schema_version": SCHEMA_VERSION,
        "context_version": str(pack.get("data_through") or ""),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": str(pack.get("data_through") or ""),
        "disclaimer": "Educational tool. Not investment advice.",
        "markets": markets,
        "treasury": lights,
        "events": [
            {"type": e.get("type"), "date": e.get("date"), "days": e.get("days")}
            for e in (pack.get("events") or [])[:8]
        ],
        "ledger": ledger,
        "drift": {"model_stale": bool((pack.get("drift") or {}).get("model_stale"))},
    }


def write(state: dict, path: Path = STATE_PATH) -> int:
    """Write the artifact, refusing to publish one that has outgrown its cap."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Separators without spaces: this file is fetched by every visitor on every cold load, and the
    # whitespace is a fifth of it.
    body = json.dumps(state, separators=(",", ":"), sort_keys=True)
    size = len(body.encode())
    if size > MAX_BYTES:
        raise ValueError(
            f"public/state.json is {size} bytes, over the {MAX_BYTES} cap. "
            "The cap exists so the one-fetch page stays a one-fetch page; trim a field "
            "rather than raising it."
        )
    path.write_text(body)
    return size


def stage(ctx: dict) -> None:
    pack = ctx.get("avatar_context")
    if not pack:
        return
    state = build(pack, ctx.get("treasury_risk"))
    ctx["public_state"] = state
    ctx.setdefault("extra_writers", {})["public/state.json"] = lambda c: write(c["public_state"])
    log.info(
        "public state: %d markets, %d pairs, context %s",
        len(state["markets"]),
        sum(len(m["pairs"]) for m in state["markets"].values()),
        state["context_version"],
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pack = json.loads((config.DATA_DIR / "avatar_context.json").read_text())
    treasury = None
    tpath = config.DATA_DIR / "treasury_risk.json"
    if tpath.exists():
        treasury = json.loads(tpath.read_text())
    state = build(pack, treasury)
    size = write(state)
    pairs = sum(len(m["pairs"]) for m in state["markets"].values())
    print(f"wrote {STATE_PATH.relative_to(config.ROOT)}: {size:,} bytes of {MAX_BYTES:,}")
    print(f"  {len(state['markets'])} markets · {pairs} pairs · context {state['context_version']}")


if __name__ == "__main__":
    main()
