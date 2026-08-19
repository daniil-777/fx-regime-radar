"""Live forward-test ledger — the number that matters after ship day.

A backtest, however honest, is a claim about the past. This module keeps the record that a
reviewer can actually trust: every weekday the pipeline writes the forecasts it just published
(regime, 5-day change risk, siren percentile — one row per pair for the newest date only) into an
APPEND-ONLY, SHA-256 hash-chained ledger *before* the outcome exists. Five trading days later each
row is resolved against the regimes that actually arrived, and the resolved rows are scored with
the very same function the frozen test used (`forecaster.metrics`: PR-AUC, precision/recall at the
frozen threshold, Brier — never accuracy).

Rules baked in:
* Nothing is ever backfilled. A forecast for day t counts only if it was recorded while t was
  the newest observation. Miss a day (pipeline down) and that day is simply absent.
* Rows are immutable once written; the chain (`prev_hash` → `row_hash`) proves it. Outcome
  columns are filled exactly once and are recomputable by anyone from regimes.parquet.
* The label is `forecaster.build_labels`' definition verbatim: 1 if the filtered regime at any of
  t+1..t+5 differs from the regime recorded at t.
* A model refit starts a new segment (rows carry `model_version`); the headline scores the
  current segment only, so a refit can never launder an old record.
* Degenerate metrics are null, never 0 (fewer than MIN_RESOLVED rows, or a single class).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fxradar import config, forecaster

log = logging.getLogger(__name__)

LEDGER_PATH = config.DATA_DIR / "ledger.parquet"
LIVE_RECORD_PATH = config.DATA_DIR / "live_record.json"
BADGE_PATH = config.DATA_DIR / "badges" / "live_record.json"
README_PATH = config.ROOT / "README.md"

HORIZON = forecaster.HORIZON  # 5 trading days, same as the forecaster label
MIN_RESOLVED = 20  # below this the live column says "warming up" instead of a number
GENESIS = "0" * 64  # prev_hash of the first row

# schema 1 (rows written before phase 20): the original six forecast fields
FORECAST_COLUMNS_V1 = [
    "date",
    "pair",
    "regime",
    "change_risk_5d",
    "anomaly_pct",
    "model_version",
    "recorded_at_utc",
    "prev_hash",
    "row_hash",
]
# schema 2 (phase 20+): filtered probabilities, conformal band (22), BOCPD + votes (21), git SHA,
# correction pointer. Old rows keep schema 1 and hash exactly as they always did — nothing is
# ever rewritten or migrated; `schema` tells the verifier which field set a row's hash covers.
SCHEMA = 2
PROB_COLUMNS = ["p_calm", "p_trend", "p_chop", "p_crisis"]
INTERVAL_COLUMNS = ["risk_lo", "risk_hi", "conformal_q"]
BOCPD_COLUMNS = ["bocpd_run_length", "bocpd_p_change_5d"]
VOTE_COLUMNS = ["vote_hmm", "vote_bocpd", "vote_vol", "agreement"]
EXTRA_FORECAST_COLUMNS = [
    *PROB_COLUMNS,
    *INTERVAL_COLUMNS,
    *BOCPD_COLUMNS,
    *VOTE_COLUMNS,
    "git_sha",
    "schema",
    "correction_of",
]
FORECAST_COLUMNS_V2 = [
    "date",
    "pair",
    "regime",
    *PROB_COLUMNS,
    "change_risk_5d",
    *INTERVAL_COLUMNS,
    "anomaly_pct",
    *BOCPD_COLUMNS,
    *VOTE_COLUMNS,
    "model_version",
    "git_sha",
    "schema",
    "correction_of",
    "recorded_at_utc",
    "prev_hash",
    "row_hash",
]
FORECAST_COLUMNS = FORECAST_COLUMNS_V2
OUTCOME_COLUMNS = ["outcome", "resolved_at_utc"]
COLUMNS = FORECAST_COLUMNS + OUTCOME_COLUMNS
FLOAT_COLUMNS = [
    *PROB_COLUMNS,
    "change_risk_5d",
    *INTERVAL_COLUMNS,
    "anomaly_pct",
    "bocpd_p_change_5d",
    "outcome",
]
HEAD_PATH = config.DATA_DIR / "ledger_head.txt"
SCOREBOARD_MD = config.REPORTS_DIR / "live_scoreboard.md"
SCOREBOARD_JSON = config.REPORTS_DIR / "live_scoreboard.json"

START_MARK, END_MARK = "<!-- live-record:start -->", "<!-- live-record:end -->"


# --------------------------------------------------------------------------------------
# hash chain
# --------------------------------------------------------------------------------------
def _canon(value) -> object:
    """Canonical JSON-able value: floats rounded to 10 dp, NaN -> None, timestamps -> ISO date,
    numpy ints -> int. Deterministic across pandas/numpy versions on purpose."""
    if isinstance(value, pd.Timestamp | datetime):
        return value.strftime("%Y-%m-%d")
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, np.floating | float):
        return None if np.isnan(value) else round(float(value), 10)
    if isinstance(value, np.integer):
        return int(value)
    return value


def git_sha() -> str:
    """Short git SHA of the code that produced a row ('unknown' outside a checkout)."""
    import subprocess

    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short=12", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=config.ROOT,
                check=False,
            ).stdout.strip()
            or "unknown"
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _schema_of(record: dict) -> int:
    v = record.get("schema")
    return 1 if v is None or (isinstance(v, float) and np.isnan(v)) else int(v)


def hashed_fields(schema: int) -> list[str]:
    cols = FORECAST_COLUMNS_V1 if schema == 1 else FORECAST_COLUMNS_V2
    return [c for c in cols if c not in ("prev_hash", "row_hash")]


def row_hash(prev_hash: str, record: dict) -> str:
    """SHA-256 over the previous hash and the canonical sorted-key JSON of the forecast fields
    (never the outcome). The field set depends on the row's schema version."""
    fields = hashed_fields(_schema_of(record))
    payload = json.dumps({c: _canon(record.get(c)) for c in fields}, sort_keys=True)
    return hashlib.sha256(f"{prev_hash}|{payload}".encode()).hexdigest()


def verify_chain(ledger: pd.DataFrame) -> bool:
    """True iff every row's hash recomputes from its predecessor (an edited or deleted row breaks it)."""
    prev = GENESIS
    for rec in ledger.to_dict("records"):
        if rec["prev_hash"] != prev or row_hash(prev, rec) != rec["row_hash"]:
            return False
        prev = rec["row_hash"]
    return True


# --------------------------------------------------------------------------------------
# io
# --------------------------------------------------------------------------------------
def empty_ledger() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNS})
    return _typed(df)


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    """Stable dtypes: floats for numbers, nullable Int64 for run length / votes / schema."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    for c in FLOAT_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    for c in ["bocpd_run_length", *VOTE_COLUMNS, "schema"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def load(path: Path | None = None) -> pd.DataFrame:
    """The ledger on disk (older schema-1 files are widened with empty columns — the stored rows
    and their hashes are untouched), or an empty one (first run)."""
    path = LEDGER_PATH if path is None else path
    if not Path(path).exists():
        return empty_ledger()
    df = pd.read_parquet(path)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = _typed(df)
    df.loc[df["schema"].isna(), "schema"] = 1  # pre-phase-20 rows
    return df[COLUMNS]


def save(ledger: pd.DataFrame, path: Path | None = None) -> None:
    path = LEDGER_PATH if path is None else path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ledger[COLUMNS].to_parquet(path, index=False)


# --------------------------------------------------------------------------------------
# append + resolve
# --------------------------------------------------------------------------------------
def append_latest(
    ledger: pd.DataFrame, regimes: pd.DataFrame, recorded_at_utc: str, sha: str | None = None
) -> tuple[pd.DataFrame, int]:
    """Record the newest date's forecast per pair, if the ledger has not seen it yet.

    Only the newest date per pair is ever written — that is what makes a row a *forward*
    forecast — and only if it is newer than the pair's last recorded date (the ledger moves
    forward or not at all). Returns (ledger, rows_added). Idempotent within a day.
    """
    latest = regimes.sort_values("date").groupby("pair").tail(1).sort_values("pair")
    fam = ledger["model_version"].astype(str).map(_family) if len(ledger) else pd.Series(dtype=str)
    last_seen = (
        ledger.assign(_fam=fam).groupby(["pair", "_fam"])["date"].max()
        if len(ledger)
        else pd.Series(dtype="datetime64[ns]")
    )
    prev = ledger["row_hash"].iloc[-1] if len(ledger) else GENESIS
    sha = sha if sha is not None else git_sha()
    new_rows: list[dict] = []
    for r in latest.to_dict("records"):
        key = (r["pair"], _family(str(r["model_version"])))
        if key in last_seen.index and pd.Timestamp(r["date"]) <= last_seen[key]:
            continue
        rec = _forecast_record(r, recorded_at_utc, sha, prev)
        prev = rec["row_hash"]
        new_rows.append(rec)
    if not new_rows:
        return ledger, 0
    out = pd.concat([ledger, _typed(pd.DataFrame(new_rows)[COLUMNS])], ignore_index=True)
    return out, len(new_rows)


def _family(model_version: str) -> str:
    """Champion rows and challenger rows (phase 23) keep separate 'newest date' pointers."""
    return "challenger" if model_version.startswith("challenger") else "champion"


def _num(value, cast=float):
    if value is None:
        return np.nan if cast is float else None
    if isinstance(value, float) and np.isnan(value):
        return np.nan if cast is float else None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return np.nan if cast is float else None


def _forecast_record(
    r: dict, recorded_at_utc: str, sha: str, prev: str, correction_of=None
) -> dict:
    """One schema-2 row from a regimes row (missing optional columns become null)."""
    rec = {
        "date": pd.Timestamp(r["date"]),
        "pair": r["pair"],
        "regime": r["regime"],
        "change_risk_5d": _num(r.get("change_risk_5d")),
        "anomaly_pct": _num(r.get("anomaly_pct")),
        "model_version": str(r["model_version"]),
        "git_sha": sha,
        "schema": SCHEMA,
        "correction_of": correction_of,
        "recorded_at_utc": recorded_at_utc,
        "prev_hash": prev,
    }
    for c in [*PROB_COLUMNS, *INTERVAL_COLUMNS, "bocpd_p_change_5d"]:
        rec[c] = _num(r.get(c))
    for c in ["bocpd_run_length", *VOTE_COLUMNS]:
        rec[c] = _num(r.get(c), int)
    rec["row_hash"] = row_hash(prev, rec)
    rec["outcome"], rec["resolved_at_utc"] = np.nan, None
    return rec


def append_correction(
    ledger: pd.DataFrame,
    original_row_hash: str,
    corrected: dict,
    recorded_at_utc: str,
    sha: str | None = None,
) -> pd.DataFrame:
    """Corrections are NEW rows that point at the original row's hash — the original is never
    edited. `corrected` holds the replacement forecast fields (date/pair/regime/... as a regimes row).
    """
    if not (ledger["row_hash"] == original_row_hash).any():
        raise KeyError(f"no ledger row with hash {original_row_hash[:12]}…")
    prev = ledger["row_hash"].iloc[-1]
    rec = _forecast_record(
        corrected, recorded_at_utc, sha or git_sha(), prev, correction_of=original_row_hash
    )
    return pd.concat([ledger, _typed(pd.DataFrame([rec])[COLUMNS])], ignore_index=True)


def resolve(
    ledger: pd.DataFrame, regimes: pd.DataFrame, resolved_at_utc: str, horizon: int = HORIZON
) -> tuple[pd.DataFrame, int]:
    """Fill `outcome` for every pending row whose next `horizon` trading days now exist.

    outcome = 1.0 if the filtered regime at any of t+1..t+horizon differs from the regime recorded
    at t (identical to `forecaster.build_labels`); rows with an incomplete window stay NaN.
    """
    ledger = ledger.copy()
    n = 0
    for pair, g in regimes.sort_values("date").groupby("pair"):
        dates, regs = g["date"].to_numpy(), g["regime"].to_numpy()
        pending = ledger.index[(ledger["pair"] == pair) & ledger["outcome"].isna()]
        for i in pending:
            start = np.searchsorted(dates, np.datetime64(ledger.at[i, "date"]), side="right")
            future = regs[start : start + horizon]
            if len(future) < horizon:
                continue
            ledger.at[i, "outcome"] = float((future != ledger.at[i, "regime"]).any())
            ledger.at[i, "resolved_at_utc"] = resolved_at_utc
            n += 1
    return ledger, n


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------
def frozen_from_meta(meta: dict) -> dict:
    """The frozen test-set numbers (scored once, phase 07) from the forecaster's meta json."""
    board = {row["model"]: row for row in meta.get("test_scoreboard", [])}
    ours = board.get("XGBoost (ours, calibrated)", {})
    base = board.get("base_rate", {})
    return {
        "pr_auc": ours.get("pr_auc"),
        "precision": ours.get("precision"),
        "recall": ours.get("recall"),
        "brier": ours.get("brier"),
        "base_rate_pr_auc": base.get("pr_auc"),
        "base_rate_brier": base.get("brier"),
        "pos_rate": ours.get("pos_rate"),
        "n": ours.get("n"),
        "test_start": str(config.TEST_START),
        "threshold": meta.get("threshold"),
    }


def summarize(
    ledger: pd.DataFrame,
    threshold: float,
    base_rate_p: float,
    frozen: dict | None = None,
    min_resolved: int = MIN_RESOLVED,
    generated_at_utc: str | None = None,
) -> dict:
    """The live record as one JSON-able dict (what the README, the badge and the app read).

    Scores the CURRENT model segment only (rows whose model_version equals the last recorded one).
    Metrics are null until `min_resolved` rows have resolved; PR-AUC is also null when only one
    class has been observed. `base_rate_p` is the frozen base-rate forecast (train positive rate).
    """
    version = str(ledger["model_version"].iloc[-1]) if len(ledger) else None
    seg = ledger[ledger["model_version"] == version] if version else ledger
    resolved = seg[seg["outcome"].notna()]
    out = {
        "generated_at_utc": generated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_version": version,
        "since": str(seg["date"].min().date()) if len(seg) else None,
        "through": str(seg["date"].max().date()) if len(seg) else None,
        "days_recorded": int(seg["date"].nunique()) if len(seg) else 0,
        "n_forecasts": int(len(seg)),
        "n_resolved": int(len(resolved)),
        "n_pending": int(seg["outcome"].isna().sum()) if len(seg) else 0,
        "n_all_segments": int(len(ledger)),
        "threshold": float(threshold),
        "min_resolved": int(min_resolved),
        "chain_ok": verify_chain(ledger),
        "metrics": None,
        "status": "warming up",
        "frozen_test": frozen,
    }
    if len(resolved) >= min_resolved:
        y = resolved["outcome"].to_numpy(dtype=float)
        p = np.clip(resolved["change_risk_5d"].to_numpy(dtype=float), 0, 1)
        both_classes = 0 < y.mean() < 1
        if both_classes:  # the frozen test's metric code, verbatim
            m = forecaster.metrics(y, p, threshold)
        else:  # ranking metrics are undefined with one class: null, never 0
            hit = p >= threshold
            m = {
                "pr_auc": None,
                "precision": float(y[hit].mean()) if hit.any() else 0.0,
                "recall": None,
                "brier": float(np.mean((p - y) ** 2)),
                "n": int(len(y)),
                "pos_rate": float(y.mean()),
            }
        out["metrics"] = {**m, "base_rate_brier": float(np.mean((base_rate_p - y) ** 2))}
        out["status"] = "live"
    return out


def scoreboard(
    ledger: pd.DataFrame, threshold: float, base_rate_p: float, min_resolved: int = MIN_RESOLVED
) -> list[dict]:
    """Live scores per model_version segment (champion and challenger rows never mix)."""
    rows = []
    for version, seg in ledger.groupby("model_version", sort=False):
        resolved = seg[seg["outcome"].notna()]
        rec = {
            "model_version": str(version),
            "family": _family(str(version)),
            "since": str(seg["date"].min().date()),
            "through": str(seg["date"].max().date()),
            "n_forecasts": int(len(seg)),
            "n_resolved": int(len(resolved)),
            "brier": None,
            "pr_auc": None,
            "precision": None,
            "recall": None,
            "base_rate_brier": None,
        }
        if len(resolved) >= min_resolved:
            y = resolved["outcome"].to_numpy(dtype=float)
            p = np.clip(resolved["change_risk_5d"].to_numpy(dtype=float), 0, 1)
            rec["brier"] = float(np.mean((p - y) ** 2))
            rec["base_rate_brier"] = float(np.mean((base_rate_p - y) ** 2))
            if 0 < y.mean() < 1:
                m = forecaster.metrics(y, p, threshold)
                rec.update({k: m.get(k) for k in ("pr_auc", "precision", "recall")})
        rows.append(rec)
    return rows


def scoreboard_markdown(board: list[dict], frozen: dict | None) -> str:
    fz = frozen or {}
    lines = [
        "# Live scoreboard — forward forecasts scored after maturity",
        "",
        "Only rows whose 5-trading-day window has completed are scored; each model version is a",
        "separate segment so a refit can never launder an earlier record. Metrics appear at "
        f"{MIN_RESOLVED} resolved rows; null means not yet defined, never 0.",
        "",
        f"Frozen test (2019+, scored once): PR-AUC {_fmt(fz.get('pr_auc'))} · Brier {_fmt(fz.get('brier'))} "
        f"(base rate {_fmt(fz.get('base_rate_brier'))}) · n = {fz.get('n', 0)}",
        "",
        "| model version | family | since | through | forecasts | resolved | Brier ↓ | base-rate Brier | PR-AUC ↑ | precision | recall |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in board:
        lines.append(
            f"| `{r['model_version']}` | {r['family']} | {r['since']} | {r['through']} | {r['n_forecasts']} | {r['n_resolved']} | "
            f"{_fmt(r['brier'])} | {_fmt(r['base_rate_brier'])} | {_fmt(r['pr_auc'])} | {_fmt(r['precision'], '{:.2f}')} | {_fmt(r['recall'], '{:.2f}')} |"
        )
    return "\n".join(lines) + "\n"


def to_jsonl(ledger: pd.DataFrame) -> str:
    """Canonical JSON-lines mirror of the ledger (same rows, hashed fields already canonical) so
    `scripts/verify_ledger.py` can re-verify the chain with the standard library alone."""
    lines = []
    for rec in ledger.to_dict("records"):
        fields = hashed_fields(_schema_of(rec))
        row = {c: _canon(rec.get(c)) for c in fields}
        row["prev_hash"], row["row_hash"] = rec["prev_hash"], rec["row_hash"]
        row["outcome"] = _canon(rec.get("outcome"))
        lines.append(json.dumps(row, sort_keys=True))
    return "\n".join(lines) + ("\n" if lines else "")


def head_line(ledger: pd.DataFrame) -> str:
    """'<head hash> <newest date> <rows>' — committed daily so GitHub timestamps the chain head."""
    if not len(ledger):
        return f"{GENESIS} none 0\n"
    return f"{ledger['row_hash'].iloc[-1]} {ledger['date'].max():%Y-%m-%d} {len(ledger)}\n"


# --------------------------------------------------------------------------------------
# renderers: badge (shields.io endpoint schema) + README block
# --------------------------------------------------------------------------------------
def badge(summary: dict) -> dict:
    """shields.io 'endpoint' JSON so the README badge updates with every daily commit."""
    m = summary.get("metrics")
    if m and m.get("brier") is not None:
        message = f"Brier {m['brier']:.3f} · {summary['n_resolved']} resolved"
        color = "34D399" if (m.get("base_rate_brier") or 1) > m["brier"] else "FBBF24"
    else:
        message = f"warming up · {summary['n_resolved']}/{summary['min_resolved']} resolved"
        color = "8A94A6"
    return {"schemaVersion": 1, "label": "live record", "message": message, "color": color}


def _fmt(x, spec: str = "{:.3f}") -> str:
    return "—" if x is None else spec.format(x)


def readme_block(summary: dict) -> str:
    """The headline table: frozen test beside the live forward record, plus the honesty footnote."""
    fz, m = summary.get("frozen_test") or {}, summary.get("metrics")
    thr = summary.get("threshold")
    n_res, n_all = summary["n_resolved"], summary["n_forecasts"]
    live_head = (
        f"**live forward record** · since {summary['since']} · {n_res} resolved of {n_all}"
        if summary.get("since")
        else "**live forward record** · starts with the first daily run"
    )
    fz_head = (
        f"frozen test · {fz.get('test_start', '')[:4]}+ · scored once (n = {fz.get('n', 0):,})"
        if fz
        else "frozen test"
    )
    rows = [
        (
            "PR-AUC ↑",
            f"{_fmt(fz.get('pr_auc'))} (base rate {_fmt(fz.get('base_rate_pr_auc'))})",
            _fmt(m and m.get("pr_auc")),
        ),
        (
            "Brier ↓",
            f"{_fmt(fz.get('brier'))} (base rate {_fmt(fz.get('base_rate_brier'))})",
            f"{_fmt(m and m.get('brier'))}"
            + (f" (base rate {_fmt(m.get('base_rate_brier'))})" if m else ""),
        ),
        (
            f"precision · recall @ {_fmt(thr, '{:.2f}')}",
            f"{_fmt(fz.get('precision'), '{:.2f}')} · {_fmt(fz.get('recall'), '{:.2f}')}",
            f"{_fmt(m and m.get('precision'), '{:.2f}')} · {_fmt(m and m.get('recall'), '{:.2f}')}",
        ),
        (
            "positive rate",
            _fmt(fz.get("pos_rate"), "{:.0%}"),
            _fmt(m and m.get("pos_rate"), "{:.0%}"),
        ),
    ]
    table = "\n".join(
        [f"| 5-day regime-change forecaster | {fz_head} | {live_head} |", "|---|---|---|"]
        + [f"| {a} | {b} | {c} |" for a, b, c in rows]
    )
    if m:
        state = (
            f"**Since {summary['since']}: live PR-AUC {_fmt(m.get('pr_auc'))} / Brier {_fmt(m.get('brier'))} "
            f"on {n_res} unseen forecasts, vs frozen test PR-AUC {_fmt(fz.get('pr_auc'))} / Brier {_fmt(fz.get('brier'))}.**"
        )
    else:
        state = (
            f"**Warming up:** {n_all} forecasts recorded, {n_res} resolved — numbers appear at "
            f"{summary['min_resolved']} resolved (≈ {max(1, -(-summary['min_resolved'] // 3))} trading days after the first entry + 5-day horizon)."
        )
    chain = "✓ verified" if summary.get("chain_ok") else "**✗ BROKEN**"
    note = (
        f"{state} Every weekday the pipeline appends its just-published forecasts (one row per pair, "
        f"newest date only, never backfilled) to an append-only SHA-256 hash-chained ledger "
        f"(`data/ledger.parquet`) *before* the outcome exists; five trading days later each row is "
        f"resolved against the regimes that actually arrived and scored with the same code as the "
        f"frozen test. A model refit starts a new segment — it cannot rewrite this one. "
        f"Chain {chain} · updated {summary['generated_at_utc'][:10]}."
    )
    return f"{START_MARK}\n{table}\n\n{note}\n{END_MARK}"


def update_readme(text: str, block: str) -> str:
    """Replace what sits between the markers (idempotent; text outside the markers is untouched).
    If the markers are absent the text is returned unchanged."""
    pattern = re.compile(re.escape(START_MARK) + r".*?" + re.escape(END_MARK), re.DOTALL)
    if not pattern.search(text):
        return text
    return pattern.sub(lambda _: block, text, count=1)


# --------------------------------------------------------------------------------------
# one call for the pipeline
# --------------------------------------------------------------------------------------
def record(
    regimes: pd.DataFrame,
    meta: dict,
    now_utc: str | None = None,
    ledger_path: Path | None = None,
) -> tuple[pd.DataFrame, dict]:
    """load → append today's forecasts → resolve matured rows → summarise. Pure w.r.t. disk
    (returns the new ledger + summary; the caller writes)."""
    now_utc = now_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger_path = LEDGER_PATH if ledger_path is None else ledger_path
    ledger = load(ledger_path)
    if not verify_chain(ledger):
        raise RuntimeError(f"ledger hash chain broken in {ledger_path} — refusing to append")
    ledger, added = append_latest(ledger, regimes, now_utc)
    ledger, resolved = resolve(ledger, regimes, now_utc)
    base_p = float(meta.get("train_pos_rate", 0.17))
    summary = summarize(
        ledger, float(meta["threshold"]), base_p, frozen_from_meta(meta), generated_at_utc=now_utc
    )
    summary["added_today"], summary["resolved_today"] = added, resolved
    summary["scoreboard"] = scoreboard(ledger, float(meta["threshold"]), base_p)
    summary["head_hash"] = ledger["row_hash"].iloc[-1] if len(ledger) else GENESIS
    return ledger, summary


def write_outputs(
    ledger: pd.DataFrame,
    summary: dict,
    ledger_path: Path | None = None,
    record_path: Path | None = None,
    badge_path: Path | None = None,
    readme_path: Path | None = README_PATH,
    reports_dir: Path | None = None,
) -> None:
    """Persist ledger + summary + badge, and refresh the README block (fx universe only).
    Paths default to the module-level ones at call time (so tests can redirect them)."""
    ledger_path = LEDGER_PATH if ledger_path is None else ledger_path
    record_path = LIVE_RECORD_PATH if record_path is None else record_path
    badge_path = BADGE_PATH if badge_path is None else badge_path
    save(ledger, ledger_path)
    Path(record_path).write_text(json.dumps(summary, indent=1, default=str))
    Path(badge_path).parent.mkdir(parents=True, exist_ok=True)
    Path(badge_path).write_text(json.dumps(badge(summary)))
    head_path = Path(ledger_path).with_name("ledger_head.txt")
    head_path.write_text(head_line(ledger))
    Path(ledger_path).with_suffix(".jsonl").write_text(to_jsonl(ledger))
    if "scoreboard" in summary:
        rdir = Path(reports_dir) if reports_dir is not None else SCOREBOARD_MD.parent
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / SCOREBOARD_MD.name).write_text(
            scoreboard_markdown(summary["scoreboard"], summary.get("frozen_test"))
        )
        (rdir / SCOREBOARD_JSON.name).write_text(
            json.dumps(summary["scoreboard"], indent=1, default=str)
        )
    if readme_path is not None and Path(readme_path).exists():
        text = Path(readme_path).read_text()
        new = update_readme(text, readme_block(summary))
        if new != text:
            Path(readme_path).write_text(new)


def main() -> None:
    ap = argparse.ArgumentParser(description="Live forward-test ledger")
    ap.add_argument(
        "--record",
        action="store_true",
        help="append the newest forecasts from data/regimes.parquet, resolve, and write outputs",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    meta = json.loads(forecaster.meta_path().read_text())
    if args.record:
        regimes = pd.read_parquet(config.REGIMES_PATH)
        ledger, summary = record(regimes, meta)
        write_outputs(
            ledger, summary, readme_path=README_PATH if config.UNIVERSE_NAME == "fx" else None
        )
        log.info("added %d, resolved %d", summary["added_today"], summary["resolved_today"])
    else:
        ledger = load()
        summary = summarize(
            ledger, float(meta["threshold"]), float(meta["train_pos_rate"]), frozen_from_meta(meta)
        )
    print(json.dumps({k: v for k, v in summary.items() if k != "frozen_test"}, indent=1))


if __name__ == "__main__":
    main()
