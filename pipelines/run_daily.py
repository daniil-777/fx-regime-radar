"""Daily pipeline: data -> features -> HMM scoring -> (later: forecaster, siren, narrator) -> write.

The only place heavy compute happens (CLAUDE.md rule 8). Rules baked in:
* Models are LOADED, never fitted here (refits are a separate, deliberate action: `make refit`).
* Every stage runs in memory; artifacts are written in the final stage only, so a failure
  anywhere leaves data/ exactly as it was (the app keeps showing the last good state).
* Idempotent: the data layer excludes the in-progress day, so two runs on the same day
  produce identical files.
* Nonzero exit on any stage failure, with per-stage timings in the log.

Later phases register their scoring step with one line: `register("forecaster", stage_fn)`.
Set FXRADAR_SIMULATE_FAILURE=<stage> to rehearse the failure path (used by tests/docs).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime

import pandas as pd

from fxradar import config, data, features, forecaster, siren
from fxradar import hmm_model as hm

log = logging.getLogger("pipeline")
Stage = Callable[[dict], None]
STAGES: list[tuple[str, Stage]] = []
STATUS_PATH = config.DATA_DIR / "pipeline_status.json"


def register(name: str, fn: Stage) -> None:
    """Add a stage (runs in registration order, before the final write stage)."""
    STAGES.append((name, fn))


# --------------------------------------------------------------------------------------
# stages (each takes the shared context dict and mutates it)
# --------------------------------------------------------------------------------------
def stage_data(ctx: dict) -> None:
    prices, dropped = data.clean_prices(data.download_prices())
    try:
        ctx["ecb"] = data.validate_against_ecb(prices)
    except (data.requests.RequestException, RuntimeError) as exc:  # ECB API unreachable: soft
        log.warning("ECB cross-check skipped: %s", exc)
        ctx["ecb"] = {"skipped": str(exc)}
    ctx["prices"], ctx["dropped"] = prices, dropped
    log.info(
        "data: %d rows through %s (%d corrupted bars dropped)",
        len(prices),
        prices["date"].max().date(),
        len(dropped),
    )


def stage_features(ctx: dict) -> None:
    ctx["features"] = features.build_features(ctx["prices"])
    log.info("features: %d rows x %d cols", *ctx["features"].shape)


def stage_hmm(ctx: dict) -> None:
    bundles = hm.load_bundles()  # LOAD saved models — never refit in the daily path
    scored = hm.score_all(ctx["features"], bundles)
    ctx["regimes"] = scored[hm.REGIME_COLUMNS]  # contract columns; later phases add theirs
    ctx["features"] = ctx["features"].merge(
        scored[["date", "pair", *hm.POST_HMM_FEATURES]], on=["date", "pair"], how="left"
    )
    ctx["model_versions"] = {"hmm": next(iter(bundles.values())).version}
    latest = ctx["regimes"].sort_values("date").groupby("pair").tail(1)
    log.info(
        "hmm: %s",
        ", ".join(f"{r.pair}={r.regime} ({r.regime_prob:.2f})" for r in latest.itertuples()),
    )


def stage_forecaster(ctx: dict) -> None:
    model, meta = forecaster.load_model()  # saved xgboost json + meta (threshold, calibration)
    matrix = forecaster.build_matrix(ctx["features"], ctx["regimes"])
    scored = forecaster.score(model, matrix, meta)
    ctx["regimes"] = ctx["regimes"].merge(scored, on=["date", "pair"], how="left")
    ctx["regimes"]["model_version"] = ctx["regimes"]["model_version"] + f"|fc={meta['version']}"
    ctx["model_versions"]["forecaster"] = meta["version"]
    latest = ctx["regimes"].sort_values("date").groupby("pair").tail(1)
    log.info(
        "forecaster: %s",
        ", ".join(
            f"{r.pair} risk={r.change_risk_5d:.2f} {r.top_drivers}" for r in latest.itertuples()
        ),
    )


def stage_siren(ctx: dict) -> None:
    bundle = siren.load_bundle()
    contract, detail = siren.score(bundle, siren.joined(ctx["features"], ctx["regimes"]))
    ctx["regimes"] = ctx["regimes"].merge(contract, on=["date", "pair"], how="left")
    ctx["regimes"]["model_version"] = (
        ctx["regimes"]["model_version"] + f"|siren={bundle['version']}"
    )
    ctx["model_versions"]["siren"] = bundle["version"]
    ctx.setdefault("extra_writers", {})["siren_detail.parquet"] = lambda c, d=detail: d.to_parquet(
        siren.DETAIL_PATH, index=False
    )
    latest = ctx["regimes"].sort_values("date").groupby("pair").tail(1)
    log.info(
        "siren: %s", ", ".join(f"{r.pair} pct={r.anomaly_pct:.0f}" for r in latest.itertuples())
    )


def stage_write(ctx: dict) -> None:
    """Write every artifact at once (only reached when all compute stages succeeded)."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    data.save_prices(ctx["prices"], config.PRICES_PATH)
    ctx["features"].to_parquet(config.FEATURES_PATH, index=False)
    ctx["regimes"].to_parquet(config.REGIMES_PATH, index=False)
    for name, writer in ctx.get("extra_writers", {}).items():  # later phases add their own files
        writer(ctx)
        log.info("wrote %s", name)
    status = {
        "last_run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": str(ctx["prices"]["date"].max().date()),
        "rows": {
            "prices": int(len(ctx["prices"])),
            "features": int(len(ctx["features"])),
            "regimes": int(len(ctx["regimes"])),
        },
        "model_versions": ctx.get("model_versions", {}),
        "ecb_check": ctx.get("ecb", {}),
        "stage_seconds": ctx.get("timings", {}),
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2, default=str))
    log.info("wrote prices/features/regimes parquet + %s", STATUS_PATH.name)


register("data", stage_data)
register("features", stage_features)
register("hmm", stage_hmm)
register("forecaster", stage_forecaster)
register("siren", stage_siren)


# --------------------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------------------
def run(stages: list[tuple[str, Stage]] | None = None) -> int:
    """Run all stages then the write stage. Returns 0 on success, 1 on the first failure."""
    stages = list(stages if stages is not None else STAGES) + [("write", stage_write)]
    simulate = os.environ.get("FXRADAR_SIMULATE_FAILURE")
    ctx: dict = {"timings": {}}
    t_all = time.perf_counter()
    for name, fn in stages:
        t0 = time.perf_counter()
        try:
            if simulate == name:
                raise RuntimeError(f"simulated failure in stage '{name}'")
            fn(ctx)
        except Exception as exc:
            log.error("stage '%s' FAILED after %.1fs: %s", name, time.perf_counter() - t0, exc)
            log.error("artifacts untouched — the app keeps serving the last good state")
            return 1
        ctx["timings"][name] = round(time.perf_counter() - t0, 2)
        log.info("stage '%s' ok in %.1fs", name, ctx["timings"][name])
    log.info("pipeline ok in %.1fs", time.perf_counter() - t_all)
    return 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    pd.set_option("display.width", 160)
    sys.exit(run())


if __name__ == "__main__":
    main()
