"""Public metrics (phase 27/28): the five numbers investors ask about, honest zeros otherwise.

Gathers ledger days live, report subscribers, active API keys, design partners and MRR (plus a
few supporting counts) into `data/metrics.json`. Every value is read from an artifact that already
exists; when a source is absent the number is 0 — a real zero, never a placeholder. Privacy: the
project stores NO subscriber data; `report_subscribers` stays 0 until an opt-in list with a
privacy note exists (see docs/PRIVACY.md and docs/EMAIL_HOOK.md).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fxradar import config

log = logging.getLogger(__name__)

METRICS_PATH = config.DATA_DIR / "metrics.json"
LIVE_RECORD_PATH = config.DATA_DIR / "live_record.json"
LEDGER_PATH = config.DATA_DIR / "ledger.parquet"
SUBSCRIBERS_PATH = config.DATA_DIR / "subscribers.json"
KEYS_DB_PATH = Path(os.environ.get("FXRADAR_KEYS_DB", str(config.DATA_DIR / "keys.db")))
TRACKING_PATH = config.DOCS_DIR / "outreach" / "tracking.csv"
WEEKLY_DIR = config.DOCS_DIR / "weekly"

# The headline five, in the order the metrics page and the README table show them.
HEADLINE = [
    ("ledger_days_live", "Ledger days live"),
    ("report_subscribers", "Report subscribers"),
    ("active_api_keys", "Active API keys"),
    ("design_partners", "Design partners"),
    ("mrr_chf", "MRR (CHF)"),
]


def _ledger_days(live_record_path: Path, ledger_path: Path) -> int:
    if live_record_path.exists():
        try:
            return int(json.loads(live_record_path.read_text()).get("days_recorded") or 0)
        except (ValueError, TypeError):  # unreadable json → fall through to the ledger itself
            pass
    if ledger_path.exists():
        return int(pd.read_parquet(ledger_path, columns=["date"])["date"].nunique())
    return 0


def _forecast_counts(live_record_path: Path) -> tuple[int, int]:
    if not live_record_path.exists():
        return 0, 0
    try:
        lr = json.loads(live_record_path.read_text())
    except ValueError:
        return 0, 0
    return int(lr.get("n_forecasts") or 0), int(lr.get("n_resolved") or 0)


def _subscribers(path: Path) -> int:
    """Count of an opt-in list (`{"subscribers": [...]}` or a list); we store none today → 0."""
    if not path.exists():
        return 0
    try:
        obj = json.loads(path.read_text())
    except ValueError:
        return 0
    items = obj.get("subscribers", []) if isinstance(obj, dict) else obj
    return int(len(items)) if isinstance(items, list) else 0


def _active_keys(db_path: Path) -> int:
    """Rows of `api_keys` with revoked = 0 (schema owned by the axum service); 0 when absent."""
    if not db_path.exists():
        return 0
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            row = con.execute("SELECT COUNT(*) FROM api_keys WHERE revoked = 0").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error as exc:  # missing table, locked file, different schema
        log.info("keys.db unreadable (%s) — reporting 0 active keys", type(exc).__name__)
        return 0


def _partners(tracking_path: Path) -> tuple[int, float]:
    """(signed partners, sum of their monthly_chf) from docs/outreach/tracking.csv."""
    if not tracking_path.exists():
        return 0, 0.0
    n, chf = 0, 0.0
    with tracking_path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("status") or "").strip().lower() != "signed":
                continue
            n += 1
            try:
                chf += float(row.get("monthly_chf") or 0)
            except ValueError:
                pass
    return n, round(chf, 2)


def build_metrics(
    data_dir: Path | None = None,
    docs_dir: Path | None = None,
    keys_db: Path | None = None,
    generated_at: str | None = None,
) -> dict:
    """All metrics as one JSON-able dict. Paths default to the committed artifact locations."""
    data_dir = data_dir or config.DATA_DIR
    docs_dir = docs_dir or config.DOCS_DIR
    keys_db = keys_db or (KEYS_DB_PATH if data_dir == config.DATA_DIR else data_dir / "keys.db")
    live_path, ledger_path = data_dir / "live_record.json", data_dir / "ledger.parquet"
    n_forecasts, n_resolved = _forecast_counts(live_path)
    partners, mrr = _partners(docs_dir / "outreach" / "tracking.csv")
    weekly_dir = docs_dir / "weekly"
    reports = sorted(weekly_dir.glob("????-??-??.md")) if weekly_dir.exists() else []
    return {
        "ledger_days_live": _ledger_days(live_path, ledger_path),
        "forecasts_recorded": n_forecasts,
        "forecasts_resolved": n_resolved,
        "report_subscribers": _subscribers(data_dir / "subscribers.json"),
        "active_api_keys": _active_keys(keys_db),
        "design_partners": partners,
        "mrr_chf": mrr,
        "weekly_reports_published": len(reports),
        "latest_weekly_report": reports[-1].stem if reports else None,
        "generated_at": generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Zeros are real zeros: each number is read from an artifact, never estimated. "
        "No subscriber data is stored (docs/PRIVACY.md).",
    }


def _fmt(key: str, value) -> str:
    if key == "mrr_chf":
        return f"{float(value):,.0f}"
    return str(value)


def readme_table(metrics: dict | None = None) -> str:
    """A README-ready markdown table of the headline five (+ the two supporting counts)."""
    m = metrics if metrics is not None else build_metrics()
    rows = [(label, _fmt(k, m.get(k, 0))) for k, label in HEADLINE]
    rows += [
        (
            "Forecasts recorded / resolved",
            f"{m.get('forecasts_recorded', 0)} / {m.get('forecasts_resolved', 0)}",
        ),
        ("Weekly reports published", str(m.get("weekly_reports_published", 0))),
    ]
    lines = ["| Metric | Value |", "|---|---:|"] + [f"| {a} | {b} |" for a, b in rows]
    lines.append("")
    lines.append(
        f"_Zeros are real zeros — updated {m.get('generated_at', '—')} by `make metrics`._"
    )
    return "\n".join(lines)


def write_metrics(metrics: dict, path: Path = METRICS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2) + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    metrics = build_metrics()
    write_metrics(metrics)
    print(readme_table(metrics))
    print(f"wrote {METRICS_PATH.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
