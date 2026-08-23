"""The rollup cube: the aggregations people actually ask for, computed once (phase 40).

"How many of the 23 are calm?", "how many crisis days this year?", "how long does a storm usually
last?" — each is a full scan of the history, and each is the kind of question that makes a
conversational product feel slow at exactly the moment somebody is evaluating it.

The cube covers a documented set of SHAPES rather than a set of questions, so the archive room of
phase 42 can answer from it and fall back to a live scan only for ranges the cube does not cover.
Every row carries the rollup definition that produced it, so a number quoted from the cube traces
back to its recipe rather than to "the cube said so".

Covered shapes (this list is the contract):
  1. `pair × month × regime` — day counts and mean change risk, siren and volatility.
  2. `pair × regime` run lengths — count, mean, median and longest episode.
  3. `pair × month` siren exceedances at the 90th and 98th percentiles.
  4. `pair × event_type` windows — mean change risk and siren in the five days before and after.
  5. `window` ledger scoreboard — forecasts, resolved, Brier over 7/30/90/all days.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pandas as pd

from fxradar import config

log = logging.getLogger(__name__)

ROLLUPS_PATH = config.DATA_DIR / "rollups.parquet"
DEFINITIONS_PATH = config.DATA_DIR / "rollup_definitions.json"

DEFINITIONS = {
    "regime_month": {
        "shape": "pair × month × regime",
        "recipe": "count of days, mean change_risk_5d, mean anomaly_pct, mean vol_20 per calendar "
        "month and regime label, from regimes.parquet joined to features.parquet",
    },
    "regime_runs": {
        "shape": "pair × regime",
        "recipe": "consecutive same-label stretches: count, mean length in trading days, median, "
        "and the longest observed episode",
    },
    "siren_exceedance": {
        "shape": "pair × month",
        "recipe": "days with anomaly_pct >= 90 and >= 98, and the month's maximum",
    },
    "event_window": {
        "shape": "pair × event_type",
        "recipe": "mean change_risk_5d and anomaly_pct over the five trading days before and the "
        "five after each scheduled event in events.csv",
    },
    "ledger_window": {
        "shape": "window",
        "recipe": "forecasts, resolved count and Brier score over the last 7, 30, 90 days and all "
        "sealed rows",
    },
}


def _runs(df: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    for pair, rows in df.sort_values("date").groupby("pair"):
        current, length = None, 0
        lengths: dict[str, list[int]] = {}
        for label in rows["regime"]:
            if label == current:
                length += 1
            else:
                if current is not None:
                    lengths.setdefault(current, []).append(length)
                current, length = label, 1
        if current is not None:
            lengths.setdefault(current, []).append(length)
        for regime, ls in lengths.items():
            s = pd.Series(ls)
            out.append(
                {
                    "rollup": "regime_runs",
                    "pair": pair,
                    "regime": regime,
                    "episodes": len(ls),
                    "mean_days": float(s.mean()),
                    "median_days": float(s.median()),
                    "longest_days": int(s.max()),
                }
            )
    return out


def build(
    regimes: pd.DataFrame,
    features: pd.DataFrame | None,
    events: pd.DataFrame | None,
    ledger: pd.DataFrame | None,
) -> pd.DataFrame:
    rows: list[dict] = []
    df = regimes.copy()
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
    if features is not None and "vol_20" in features.columns:
        df = df.merge(features[["date", "pair", "vol_20"]], on=["date", "pair"], how="left")

    # 1 — pair × month × regime
    agg = (
        df.groupby(["pair", "month", "regime"])
        .agg(
            days=("date", "count"),
            mean_change_risk=("change_risk_5d", "mean"),
            mean_siren=("anomaly_pct", "mean"),
            mean_vol=("vol_20", "mean") if "vol_20" in df.columns else ("anomaly_pct", "mean"),
        )
        .reset_index()
    )
    for r in agg.to_dict("records"):
        rows.append({"rollup": "regime_month", **r})

    # 2 — run lengths
    rows += _runs(regimes)

    # 3 — siren exceedances
    if "anomaly_pct" in df.columns:
        ex = (
            df.groupby(["pair", "month"])
            .agg(
                days_over_90=("anomaly_pct", lambda s: int((s >= 90).sum())),
                days_over_98=("anomaly_pct", lambda s: int((s >= 98).sum())),
                max_siren=("anomaly_pct", "max"),
            )
            .reset_index()
        )
        for r in ex.to_dict("records"):
            rows.append({"rollup": "siren_exceedance", **r})

    # 4 — event windows
    if events is not None and not events.empty and "date" in events.columns:
        ev = events.copy()
        ev["date"] = pd.to_datetime(ev["date"])
        by_pair = {
            p: g.sort_values("date").reset_index(drop=True)
            for p, g in regimes.assign(date=pd.to_datetime(regimes["date"])).groupby("pair")
        }
        for etype, group in ev.groupby(ev.columns[1] if "type" not in ev.columns else "type"):
            for pair, prices in by_pair.items():
                before, after = [], []
                for when in group["date"]:
                    idx = prices["date"].searchsorted(when)
                    before += prices.iloc[max(0, idx - 5) : idx]["change_risk_5d"].dropna().tolist()
                    after += prices.iloc[idx : idx + 5]["change_risk_5d"].dropna().tolist()
                if before or after:
                    rows.append(
                        {
                            "rollup": "event_window",
                            "pair": pair,
                            "event_type": str(etype),
                            "mean_change_risk_before": (
                                float(pd.Series(before).mean()) if before else None
                            ),
                            "mean_change_risk_after": (
                                float(pd.Series(after).mean()) if after else None
                            ),
                            "n_events": int(len(group)),
                        }
                    )

    # 5 — ledger windows
    if ledger is not None and not ledger.empty and "date" in ledger.columns:
        led = ledger.copy()
        led["date"] = pd.to_datetime(led["date"])
        newest = led["date"].max()
        for window in (7, 30, 90, 10_000):
            sub = led[led["date"] >= newest - pd.Timedelta(days=window)]
            resolved = (
                sub[sub.get("outcome").notna()] if "outcome" in sub.columns else sub.iloc[0:0]
            )
            brier = None
            if len(resolved) and {"outcome", "change_risk_5d"} <= set(resolved.columns):
                brier = float(((resolved["change_risk_5d"] - resolved["outcome"]) ** 2).mean())
            rows.append(
                {
                    "rollup": "ledger_window",
                    "window_days": "all" if window > 5000 else str(window),
                    "forecasts": int(len(sub)),
                    "resolved": int(len(resolved)),
                    "brier": brier,
                }
            )

    out = pd.DataFrame(rows)
    out["definition_version"] = "1.0.0"
    return out


def stage(ctx: dict) -> None:
    regimes = ctx.get("regimes")
    if regimes is None:
        return
    data = config.DATA_DIR
    features = ctx.get("features")
    if features is None and (data / "features.parquet").exists():
        features = pd.read_parquet(data / "features.parquet")
    events = None
    if (data / "events.csv").exists():
        events = pd.read_csv(data / "events.csv")
    ledger = None
    if (data / "ledger.parquet").exists():
        ledger = pd.read_parquet(data / "ledger.parquet")
    cube = build(regimes, features, events, ledger)
    ctx["rollups"] = cube
    writers = ctx.setdefault("extra_writers", {})
    writers["rollups.parquet"] = lambda c: c["rollups"].to_parquet(ROLLUPS_PATH, index=False)
    writers["rollup_definitions.json"] = lambda c: DEFINITIONS_PATH.write_text(
        json.dumps(
            {
                "definition_version": "1.0.0",
                "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "note": "Every cube row carries `rollup` and `definition_version`; this file is the recipe "
                "each name refers to, so a number quoted from the cube can be traced to how it was "
                "computed rather than to the cube itself.",
                "definitions": DEFINITIONS,
            },
            indent=1,
        )
    )
    log.info("rollup cube: %d rows across %d shapes", len(cube), cube["rollup"].nunique())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    data = config.DATA_DIR
    regimes = pd.read_parquet(data / "regimes.parquet")
    features = (
        pd.read_parquet(data / "features.parquet") if (data / "features.parquet").exists() else None
    )
    events = pd.read_csv(data / "events.csv") if (data / "events.csv").exists() else None
    ledger = (
        pd.read_parquet(data / "ledger.parquet") if (data / "ledger.parquet").exists() else None
    )
    cube = build(regimes, features, events, ledger)
    cube.to_parquet(ROLLUPS_PATH, index=False)
    DEFINITIONS_PATH.write_text(
        json.dumps({"definition_version": "1.0.0", "definitions": DEFINITIONS}, indent=1)
    )
    print(f"wrote {ROLLUPS_PATH.name}: {len(cube)} rows")
    print(cube.groupby("rollup").size().to_string())


if __name__ == "__main__":
    main()
