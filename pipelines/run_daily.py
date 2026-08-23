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

from fxradar import (
    advisor,
    answer_packs,
    arcade,
    archive,
    avatar_context,
    bocpd,
    cb_features,
    challenger,
    config,
    conformal,
    data,
    decision,
    drift,
    features,
    features_ext,
    forecaster,
    ledger,
    narrate,
    regime_models,
    replay,
    rollups,
    siren,
    treasury,
    visual_boards,
)
from fxradar import hmm_model as hm

log = logging.getLogger("pipeline")
Stage = Callable[[dict], None]
STAGES: list[tuple[str, Stage]] = []
STATUS_PATH = config.DATA_DIR / "pipeline_status.json"


def register(name: str, fn: Stage) -> None:
    """Add a stage (runs in registration order, before the final write stage)."""
    STAGES.append((name, fn))


def fx_only(fn: Stage) -> Stage:
    """Wrap a stage that only makes sense for the FX universe (calendar, challenger, treasury in
    francs): other universes log one line and skip, so `FXRADAR_UNIVERSE=crypto` keeps running."""

    def wrapped(ctx: dict) -> None:
        if config.UNIVERSE_NAME != "fx":
            log.info("skipped for universe %r (FX-only stage)", config.UNIVERSE_NAME)
            return
        fn(ctx)

    wrapped.__name__ = getattr(fn, "__name__", "stage")
    return wrapped


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
    # LOAD saved models — never refit in the daily path. The regime model is selected per universe
    # via FXRADAR_REGIME_MODEL (default: the champion HMM; fx is hard-locked to it — see
    # regime_models.selected_model). "hmm" delegates to the exact champion code path.
    name = regime_models.selected_model()
    bundles = regime_models.load_bundles(name)
    scored = regime_models.score_all(ctx["features"], bundles)
    ctx["regimes"] = scored[hm.REGIME_COLUMNS]  # contract columns; later phases add theirs
    ctx["features"] = ctx["features"].merge(
        scored[["date", "pair", *hm.POST_HMM_FEATURES]], on=["date", "pair"], how="left"
    )
    first = next(iter(bundles.values()))
    ctx["model_versions"] = {"regime_model": name, "hmm": first.version}
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
    ctx["forecaster_meta"] = meta  # threshold + frozen scoreboard, reused by the ledger stage
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
    ctx["siren_detail"] = detail
    ctx.setdefault("extra_writers", {})["siren_detail.parquet"] = lambda c, d=detail: d.to_parquet(
        siren.DETAIL_PATH, index=False
    )
    latest = ctx["regimes"].sort_values("date").groupby("pair").tail(1)
    log.info(
        "siren: %s", ", ".join(f"{r.pair} pct={r.anomaly_pct:.0f}" for r in latest.itertuples())
    )


def stage_ledger(ctx: dict) -> None:
    """Live forward-test record: append today's forecasts (newest date per pair) to the append-only
    hash-chained ledger, resolve rows whose 5-day window has completed, score them like the frozen
    test. Files (ledger, live_record.json, badge, README block) are written in the write stage."""
    new_ledger, summary = ledger.record(
        ctx["regimes"], ctx["forecaster_meta"], challenger=ctx.get("challenger_scores")
    )
    ctx["ledger"], ctx["live_record"] = new_ledger, summary
    ctx.setdefault("extra_writers", {})[
        "ledger.parquet + head + live_record.json (+ README block)"
    ] = lambda c: ledger.write_outputs(
        c["ledger"],
        c["live_record"],
        readme_path=ledger.README_PATH if config.UNIVERSE_NAME == "fx" else None,
    )
    m = summary["metrics"]
    log.info(
        "ledger: +%d recorded, %d resolved today; %d/%d resolved since %s — %s",
        summary["added_today"],
        summary["resolved_today"],
        summary["n_resolved"],
        summary["n_forecasts"],
        summary["since"],
        f"Brier {m['brier']:.3f} PR-AUC {m['pr_auc']}" if m else summary["status"],
    )


def stage_narrator(ctx: dict) -> None:
    """After ALL scoring: three sentences per pair from computed numbers (LLM or template)."""
    detail = ctx.get("siren_detail")
    report = narrate.build_report(regimes=ctx["regimes"], detail=detail, prices=ctx["prices"])
    ctx["report"] = report
    ctx.setdefault("extra_writers", {})["report.json"] = lambda c: narrate.write_report(c["report"])
    log.info("narrator: %s", ", ".join(f"{p}={r['source']}" for p, r in report.items()))


def stage_advisor(ctx: dict) -> None:
    """Stability index, durability, risk budgets and allocation from the finished numbers."""
    if config.REGIME_MODEL == "hmm":
        diag = {
            p: {b.mapping[i]: float(b.model.transmat_[i, i]) for i in range(hm.N_STATES)}
            for p, b in hm.load_bundles().items()
        }
    else:  # alternative regime models have no transition matrix: use the empirical self-transition
        diag = {}
        for p, g in ctx["regimes"].sort_values("date").groupby("pair"):
            same = g["regime"].eq(g["regime"].shift(1))
            diag[p] = {
                r: float(same[g["regime"] == r].mean()) for r in g["regime"].unique() if pd.notna(r)
            }
    ctx["advisor"] = advisor.snapshot(
        ctx["regimes"], ctx["features"], ctx["prices"], transmat_diag=diag
    )
    ctx.setdefault("extra_writers", {})["advisor.json"] = lambda c: (
        config.DATA_DIR / "advisor.json"
    ).write_text(json.dumps(c["advisor"], indent=1, default=float))
    ms = ctx["advisor"]["markets"]
    log.info(
        "advisor: overall stability %.0f (%s); %s",
        ctx["advisor"]["overall_stability"],
        ctx["advisor"]["overall_word"],
        ", ".join(
            f"{p} {m['stability']:.0f}/{m['risk_budget']['budget']:.0%}" for p, m in ms.items()
        ),
    )


def stage_arcade(ctx: dict) -> None:
    """Resolve matured arcade calls (5 trading days elapsed) against the freshly scored regimes.
    The sqlite file is a state store, not an artifact; it is only touched if it exists."""
    if not arcade.DB_PATH.exists():
        log.info("arcade: no data/arcade.db yet — nothing to resolve")
        return

    def _resolve(c: dict) -> None:
        conn = arcade.connect()
        n = arcade.resolve_calls(conn, c["regimes"])
        conn.close()
        log.info("arcade: resolved %d matured calls", n)

    ctx.setdefault("extra_writers", {})["arcade.db (resolutions)"] = _resolve


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
# phase 29: lexicon tone features (date-level; challenger only) — FX universe only
register("cb_features", fx_only(cb_features.stage))
# phase 23: calendar / context / COT / Yang-Zhang → features_ext.parquet — FX universe only
register("features_ext", fx_only(features_ext.stage))
register("forecaster", stage_forecaster)
# phase 23: challenger forecaster on features + features_ext (ledger-raced) — FX universe only
register("challenger", fx_only(challenger.stage))
register("siren", stage_siren)
register("bocpd", bocpd.stage)  # phase 21: run-length posterior + three-voter consensus
register("conformal", conformal.stage)  # phase 22: Mondrian band on change risk + coverage receipt
register("drift", drift.stage)  # phase 20: PSI / KS / HMM staleness → status.json
register(
    "ledger", stage_ledger
)  # forward record of what was just published (before outcomes exist)
register("narrator", stage_narrator)  # narrates the finished numbers
register(
    "postmortem", replay.stage
)  # phase 26: DRAFT day-by-day report on a live entry into crisis
register(
    "advisor", stage_advisor
)  # stability / durability / risk budgets from the finished numbers
register("treasury", fx_only(treasury.stage))  # phase 25: regime-conditional VaR/ES + traffic light
register(
    "avatar", avatar_context.stage
)  # phase 35: the presenter's daily mind → avatar_context.json
register(
    "decision", fx_only(decision.stage)
)  # phase 36: deterministic hedging decision table → decision_table.json
register(
    "visuals", fx_only(visual_boards.stage)
)  # phase 36: resolve every card the artifacts can fill → visual_boards.json + visual_index.json
register(
    "packs", fx_only(answer_packs.stage)
)  # phase 40: precompute every answer that needs no user input, gates run at build time
register(
    "rollups", fx_only(rollups.stage)
)  # phase 40: the aggregation cube the archive queries first
register(
    "archive", fx_only(archive.stage)
)  # the archive room: history and aggregates the serving side answers from
register("arcade", stage_arcade)  # resolves matured calls (writes happen in the write stage)


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
