"""The decision engine: personal hedging decision support, computed — never generated.

Owner decision 2026-08-20: the presenter may give personal investment decision support. This module
is HOW that stays defensible: the decision is a DETERMINISTIC function of the app's published risk
calculations (treasury VaR/ES per regime, the treasury light, change risk with its conformal band,
consensus, scheduled events) plus the user's own inputs (exposure, horizon, risk tolerance) — the
LLM never invents a recommendation, it only voices what this engine computed, and every number is
traceable to an artifact or to arithmetic on the user's stated amount.

What it recommends: a HEDGE RATIO (how much of the exposure to cover) and a TRANCHE SCHEDULE
(when), with the expected shortfall of the uncovered remainder as the price tag. Direction is not
part of any output — hedging is insurance sizing, and this system has no direction model to lean
on (golden rule 5 stands).

The daily pipeline writes `data/decision_table.json`: one precomputed row per (pair × tolerance),
so the serving side personalises with arithmetic only (amount × ES × √weeks) — the wall stays
shut and rule 8 holds. Compliance note, unchanged and loud: offering this to third parties in
Switzerland likely constitutes financial advice under FinSA — confirm with a professional before
exposing it to clients; the flag ships OFF.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fxradar import config

log = logging.getLogger(__name__)

TABLE_PATH = config.DATA_DIR / "decision_table.json"
TOLERANCES = ("conservative", "balanced", "aggressive")

# base hedge ratio per treasury light — the light already encodes regime, risk, band and calendar
BASE_RATIO = {"hedge": 0.75, "ladder": 0.50, "wait": 0.25}
TOL_ADJ = {"conservative": 0.15, "balanced": 0.0, "aggressive": -0.15}
CONSENSUS_ADJ = 0.05  # two or more stress voters: nudge coverage up
RATIO_FLOOR, RATIO_CAP = 0.10, 0.95

ADVICE_DISCLOSURE = (
    "Before I answer: this is software-generated decision support computed from the radar's "
    "published risk numbers and your stated inputs — not advice from a licensed adviser, and "
    "never a view on direction."
)


def hedge_ratio(light: str, tolerance: str, agreement: int | None) -> float:
    """The deterministic core: light → base, tolerance shifts it, consensus nudges it."""
    base = BASE_RATIO.get(light, BASE_RATIO["ladder"])
    ratio = base + TOL_ADJ[tolerance] + (CONSENSUS_ADJ if (agreement or 0) >= 2 else 0.0)
    return round(max(RATIO_FLOOR, min(RATIO_CAP, ratio)) * 20) / 20  # steps of 5 %


def tranche_schedule(light: str, ratio: float, horizon_weeks: int) -> list[dict]:
    """When to put the cover on. hedge: front-loaded; ladder: equal weekly slices; wait: a single
    small tranche now, the rest left open with a weekly review."""
    horizon_weeks = max(1, min(int(horizon_weeks), 12))
    n = max(1, min(horizon_weeks, 4))
    if light == "hedge":
        if n == 1:  # no room to spread: the whole cover goes on now
            return [{"week": 0, "fraction": ratio}]
        first = round(ratio * 0.6, 2)
        rest = ratio - first
        out = [{"week": 0, "fraction": first}]
        for i in range(1, n):
            out.append({"week": i, "fraction": round(rest / (n - 1), 3)})
        return out
    if light == "wait":
        return [{"week": 0, "fraction": ratio}]
    return [{"week": i, "fraction": round(ratio / n, 3)} for i in range(n)]


def decide_row(pair_block: dict, tre_pair: dict, tolerance: str) -> dict:
    """One precomputed decision row from published artifacts (no user inputs yet)."""
    light = str(tre_pair.get("light") or "ladder")
    regime = str(tre_pair.get("current_regime") or pair_block.get("regime") or "calm")
    cell = (tre_pair.get("table") or {}).get(regime) or {}
    ratio = hedge_ratio(light, tolerance, pair_block.get("agreement"))
    return {
        "light": light,
        "regime": regime,
        "tolerance": tolerance,
        "hedge_ratio": ratio,
        "schedule_by_horizon": {
            str(w): tranche_schedule(light, ratio, w) for w in (1, 2, 4, 8, 12)
        },
        "es_99_1w": cell.get("es_99"),
        "es_95_1w": cell.get("es_95"),
        "var_99_1w": cell.get("var_99"),
        "review_trigger": (
            "revisit immediately if the regime flips, the consensus reaches 2 of 3, or the "
            "change risk leaves its band; otherwise review weekly"
        ),
    }


def build_table(avatar_pack: dict, treasury: dict) -> dict:
    """data/decision_table.json: rows per (pair × tolerance) + the fx crosses for conversion."""
    pairs = avatar_pack.get("pairs") or {}
    tre = (treasury or {}).get("pairs") or {}
    rows: dict = {}
    for pair, blk in pairs.items():
        if pair not in tre:
            continue
        rows[pair] = {tol: decide_row(blk, tre[pair], tol) for tol in TOLERANCES}
    return {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": avatar_pack.get("data_through"),
        "disclosure": ADVICE_DISCLOSURE,
        "method": (
            "deterministic: treasury light -> base hedge ratio (hedge 0.75 / ladder 0.50 / "
            "wait 0.25), risk tolerance +/-0.15, consensus >=2/3 +0.05, clipped to [0.10, 0.95] "
            "in 5% steps; tranches front-loaded under 'hedge', equal weekly under 'ladder'; "
            "price tag = ES of the UNCOVERED share, sqrt-of-time scaled (an approximation)"
        ),
        "fx": (treasury or {}).get("fx") or {},
        "pairs": rows,
        "compliance": (
            "software-generated decision support from published numbers; not a licensed adviser; "
            "direction is never modelled. Swiss FinSA review required before offering to clients."
        ),
    }


def stage(ctx: dict) -> None:
    """run_daily stage (after treasury + avatar): precompute the decision table artifact."""
    pack = ctx.get("avatar_context")
    treasury = None
    tre_path = config.DATA_DIR / "treasury_risk.json"
    if "avatar_context" not in ctx or pack is None:
        return
    if tre_path.exists():
        treasury = json.loads(tre_path.read_text())
    if ctx.get("extra_writers", {}).get("treasury_risk.json") and "treasury" in ctx:
        treasury = ctx["treasury"]
    table = build_table(pack, treasury or {})
    ctx["decision_table"] = table
    ctx.setdefault("extra_writers", {})["decision_table.json"] = lambda c: TABLE_PATH.write_text(
        json.dumps(c["decision_table"], indent=1)
    )
    log.info("decision table: %d pairs x %d tolerances", len(table["pairs"]), len(TOLERANCES))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pack_path = config.DATA_DIR / "avatar_context.json"
    tre_path = config.DATA_DIR / "treasury_risk.json"
    pack = json.loads(pack_path.read_text())
    treasury = json.loads(tre_path.read_text()) if tre_path.exists() else {}
    table = build_table(pack, treasury)
    TABLE_PATH.write_text(json.dumps(table, indent=1))
    print(f"wrote {TABLE_PATH}")
    for pair, tols in table["pairs"].items():
        b = tols["balanced"]
        print(
            f"  {pair}: light={b['light']} ratio(balanced)={b['hedge_ratio']:.0%} es99_1w={b['es_99_1w']}"
        )


if __name__ == "__main__":
    main()
