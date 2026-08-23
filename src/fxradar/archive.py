"""The archive: the history and aggregates the serving side may answer from, bounded by design.

Written because an audit found the assistant answering historical, aggregation and comparative
questions with `gate pass` and a card about **today** — "how many crisis days has EUR/USD had this
year?" came back with a picture of the current regime. Nothing was fabricated, but a confident
non-answer is worse than a refusal: the user has no way to tell that the question was never
addressed, and the failure is invisible in every metric that counts gates.

This artifact is what makes those questions answerable at all, and it is deliberately a CLOSED SET
of shapes rather than a query engine. The serving side can count, look up a date, quote a typical
duration and compare two periods — and when a question falls outside those shapes it must say so
rather than reach for something adjacent. A bounded archive that admits its limits is worth more
than an open one that improvises.

Size is bounded on purpose: daily history for the three majors (the markets carrying the frozen
record), monthly granularity for the other twenty. A treasurer asking "what was the regime on 15
January 2015" means a major; asking it about the zloty is a research question, and research belongs
in the lab rather than in a voice answer.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pandas as pd

from fxradar import config

log = logging.getLogger(__name__)

ARCHIVE_PATH = config.DATA_DIR / "archive.json"
DAILY_PAIRS = ("EURUSD", "USDCHF", "GBPUSD")
DAILY_YEARS = 15


def build(
    regimes: pd.DataFrame, cube: pd.DataFrame | None, pack: dict, storms: dict | None = None
) -> dict:
    """Everything the archive room may answer from, and nothing else."""
    df = regimes.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["year"] = df["date"].dt.year.astype(str)

    latest = df.sort_values("date").groupby("pair").tail(1)

    # --- today, across every board ---------------------------------------------------------------
    by_regime_today: dict[str, list[str]] = {}
    for row in latest.itertuples():
        by_regime_today.setdefault(str(row.regime), []).append(str(row.pair))
    # the pack knows about markets the regimes frame for this universe does not carry
    for board in (pack.get("markets") or {}).values():
        for code, blk in (board.get("pairs") or {}).items():
            regime = str(blk.get("regime") or "")
            if regime and code not in [p for ps in by_regime_today.values() for p in ps]:
                by_regime_today.setdefault(regime, []).append(code)

    pairs: dict[str, dict] = {}
    for pair, rows in df.groupby("pair"):
        rows = rows.sort_values("date")
        # monthly counts by regime
        months: dict[str, dict[str, int]] = {}
        for (month, regime), n in rows.groupby(["month", "regime"]).size().items():
            months.setdefault(str(month), {})[str(regime)] = int(n)
        years: dict[str, dict[str, int]] = {}
        for (year, regime), n in rows.groupby(["year", "regime"]).size().items():
            years.setdefault(str(year), {})[str(regime)] = int(n)
        entry: dict = {
            "months": months,
            "years": years,
            "first_date": f"{rows['date'].min():%Y-%m-%d}",
            "last_date": f"{rows['date'].max():%Y-%m-%d}",
        }
        if pair in DAILY_PAIRS:
            cutoff = rows["date"].max() - pd.DateOffset(years=DAILY_YEARS)
            recent = rows[rows["date"] >= cutoff]
            entry["daily"] = {f"{r.date:%Y-%m-%d}": str(r.regime) for r in recent.itertuples()}
            entry["daily_risk"] = {
                f"{r.date:%Y-%m-%d}": (
                    None if pd.isna(r.change_risk_5d) else round(float(r.change_risk_5d), 4)
                )
                for r in recent.itertuples()
            }
            entry["daily_siren"] = {
                f"{r.date:%Y-%m-%d}": (
                    None if pd.isna(r.anomaly_pct) else round(float(r.anomaly_pct), 1)
                )
                for r in recent.itertuples()
            }
        pairs[str(pair)] = entry

    # --- typical durations, from the cube where available ------------------------------------------
    runs: dict[str, dict[str, dict]] = {}
    if cube is not None and not cube.empty:
        rr = cube[cube["rollup"] == "regime_runs"]
        for row in rr.itertuples():
            runs.setdefault(str(row.pair), {})[str(row.regime)] = {
                "episodes": int(row.episodes),
                "mean_days": round(float(row.mean_days), 1),
                "median_days": round(float(row.median_days), 1),
                "longest_days": int(row.longest_days),
            }

    events: dict[str, dict] = {}
    if cube is not None and not cube.empty and "event_type" in cube.columns:
        ew = cube[cube["rollup"] == "event_window"]
        for row in ew.itertuples():
            key = str(row.event_type)
            entry = events.setdefault(key, {"pairs": {}, "n_events": int(row.n_events)})
            before = getattr(row, "mean_change_risk_before", None)
            after = getattr(row, "mean_change_risk_after", None)
            entry["pairs"][str(row.pair)] = {
                "mean_change_risk_before": (
                    None if before is None or pd.isna(before) else round(float(before), 4)
                ),
                "mean_change_risk_after": (
                    None if after is None or pd.isna(after) else round(float(after), 4)
                ),
            }

    episodes: dict[str, dict] = {}
    for name, ep in (storms or {}).items():
        episodes[str(name)] = {
            "title": ep.get("title", name),
            "pair": ep.get("pair", ""),
            "start": ep.get("start", ""),
            "end": ep.get("end", ""),
        }

    # Today's reading for EVERY market, so the archive can answer "which is the most X" without a
    # scan and without the caller having to chain two lookups by hand.
    today: dict[str, dict] = {}
    for row in latest.itertuples():
        today[str(row.pair)] = {
            "regime": str(row.regime),
            "risk": None if pd.isna(row.change_risk_5d) else round(float(row.change_risk_5d), 4),
            "siren": None if pd.isna(row.anomaly_pct) else round(float(row.anomaly_pct), 1),
        }
    for board in (pack.get("markets") or {}).values():
        for code, blk in (board.get("pairs") or {}).items():
            today.setdefault(
                str(code),
                {
                    "regime": str(blk.get("regime") or ""),
                    "risk": blk.get("change_risk_5d"),
                    "siren": blk.get("anomaly_pct"),
                },
            )

    led = pack.get("ledger") or {}
    return {
        "today": today,
        "ledger": {
            "days_live": led.get("days_live"),
            "n_forecasts": led.get("n_forecasts"),
            "n_resolved": led.get("n_resolved"),
            "chain_head_short": led.get("chain_head_short"),
            "live_brier": led.get("live_brier"),
            "frozen_brier": led.get("frozen_brier"),
        },
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": str(pack.get("data_through") or ""),
        "note": (
            "A closed set of shapes, not a query engine. The serving side may count today's "
            "regimes, look up a date, quote a typical duration, compare two periods and read "
            "an event window — and must refuse anything else rather than answer with an "
            "adjacent number."
        ),
        "daily_pairs": list(DAILY_PAIRS),
        "daily_years": DAILY_YEARS,
        "markets_total": sum(len(v) for v in by_regime_today.values()),
        "counts_today": {k: len(v) for k, v in sorted(by_regime_today.items())},
        "by_regime_today": {k: sorted(v) for k, v in sorted(by_regime_today.items())},
        "pairs": pairs,
        "runs": runs,
        "events": events,
        "episodes": episodes,
    }


def stage(ctx: dict) -> None:
    regimes = ctx.get("regimes")
    pack = ctx.get("avatar_context")
    if regimes is None or not pack:
        return
    cube = ctx.get("rollups")
    if cube is None and (config.DATA_DIR / "rollups.parquet").exists():
        cube = pd.read_parquet(config.DATA_DIR / "rollups.parquet")
    storms = None
    storm_path = config.DATA_DIR / "storm_replays.json"
    if storm_path.exists():
        raw = json.loads(storm_path.read_text())
        storms = (
            raw if isinstance(raw, dict) else {e.get("id", str(i)): e for i, e in enumerate(raw)}
        )
    archive = build(regimes, cube, pack, storms)
    ctx["archive"] = archive
    ctx.setdefault("extra_writers", {})["archive.json"] = lambda c: ARCHIVE_PATH.write_text(
        json.dumps(c["archive"], indent=1)
    )
    log.info(
        "archive: %d markets, %d with daily history, %d event types",
        len(archive["pairs"]),
        len(archive["daily_pairs"]),
        len(archive["events"]),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    data = config.DATA_DIR
    regimes = pd.read_parquet(data / "regimes.parquet")
    cube = (
        pd.read_parquet(data / "rollups.parquet") if (data / "rollups.parquet").exists() else None
    )
    pack = json.loads((data / "avatar_context.json").read_text())
    storms = None
    if (data / "storm_replays.json").exists():
        raw = json.loads((data / "storm_replays.json").read_text())
        storms = (
            raw if isinstance(raw, dict) else {e.get("id", str(i)): e for i, e in enumerate(raw)}
        )
    archive = build(regimes, cube, pack, storms)
    ARCHIVE_PATH.write_text(json.dumps(archive, indent=1))
    size = ARCHIVE_PATH.stat().st_size / 1e6
    print(f"wrote {ARCHIVE_PATH.name}: {size:.2f} MB")
    print(f"  today: {archive['counts_today']} across {archive['markets_total']} markets")
    print(f"  daily history: {archive['daily_pairs']} ({archive['daily_years']}y)")
    print(f"  durations for {len(archive['runs'])} markets · {len(archive['events'])} event types")


if __name__ == "__main__":
    main()
