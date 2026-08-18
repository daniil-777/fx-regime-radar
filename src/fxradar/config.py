"""Central configuration: the ACTIVE universe (pairs, tickers, splits) and artifact paths.

Everything that is "a decision" rather than "a computation" lives here or in `universes.py`.
The active universe is chosen with the FXRADAR_UNIVERSE environment variable (default "fx");
its artifacts live under data/<subdir>, models/<subdir>, reports/<subdir> — the FX universe uses
the repository defaults so nothing that shipped moves.
"""

from __future__ import annotations

import os
from pathlib import Path

from fxradar import universes

# ---- user-facing text ----------------------------------------------------------------
# CLAUDE.md rule 7: every user-facing surface carries this exact line.
DISCLAIMER = "Educational tool. Not investment advice."

# ---- active universe --------------------------------------------------------------------
UNIVERSE_NAME = os.environ.get("FXRADAR_UNIVERSE", "fx")
UNIVERSE = universes.get(UNIVERSE_NAME)

PAIRS: list[str] = list(UNIVERSE.pairs)
YF_TICKERS: dict[str, str] = dict(UNIVERSE.tickers)
USD_BASE_PAIRS: frozenset[str] = UNIVERSE.usd_base_pairs  # returns sign-flipped in corr_20
PRICE_BOUNDS: dict[str, tuple[float, float]] = dict(UNIVERSE.price_bounds)
START_DATE = UNIVERSE.start_date
TRADING_DAYS = UNIVERSE.trading_days  # 252 (FX) or 365 (crypto): annualisation day-count

# ---- time-ordered splits (CLAUDE.md rule 2) --------------------------------------------
TRAIN_END = UNIVERSE.train_end  # train: dates <= TRAIN_END
VAL_START = UNIVERSE.val_start
VAL_END = UNIVERSE.val_end
TEST_START = UNIVERSE.test_start  # test: scored once, frozen
EMBARGO_DAYS = 5  # trading days dropped after every split boundary

# ---- paths -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"


def universe_dirs(name: str) -> dict[str, Path]:
    """data/models/reports directories for a universe (fx = repository defaults)."""
    u = universes.get(name)
    sub = Path(u.subdir) if u.subdir else Path()
    return {
        "data": ROOT / "data" / sub,
        "models": ROOT / "models" / sub,
        "reports": ROOT / "reports" / sub,
    }


_dirs = universe_dirs(UNIVERSE_NAME)
DATA_DIR = _dirs["data"]
MODELS_DIR = _dirs["models"]
REPORTS_DIR = _dirs["reports"]

PRICES_PATH = DATA_DIR / "prices.parquet"
FEATURES_PATH = DATA_DIR / "features.parquet"
REGIMES_PATH = DATA_DIR / "regimes.parquet"
REPORT_PATH = DATA_DIR / "report.json"

# ---- data contract: prices.parquet -----------------------------------------------------
PRICE_COLUMNS: list[str] = ["date", "pair", "open", "high", "low", "close"]

# ---- official cross-validation (phase 01) — FX only; frankfurter.app redirects here ------
FRANKFURTER_URL = "https://api.frankfurter.dev/v1"
ECB_CHECKS: dict[str, tuple[str, str]] = dict(UNIVERSE.ecb_checks)
ECB_LOOKBACK_YEARS = 3
ECB_WARN_MEAN_PCT = 0.5  # log a WARNING above this mean absolute % deviation
ECB_FAIL_MEAN_PCT = 2.0  # raise above this

# ---- corrupted-print filters (phase 01), sized per universe ------------------------------
BAD_TICK_JUMP = (
    UNIVERSE.bad_tick_jump
)  # reverting close jumps > x in AND back out (close outside neighbours)
BAD_TICK_JUMP_BAR = UNIVERSE.bad_tick_jump_bar  # ... or > y each way when the WHOLE bar is disjoint
BAD_TICK_REVERT = UNIVERSE.bad_tick_revert  # ... while the two-day through-move stays < z
BAD_EXTREME_TOL = (
    UNIVERSE.bad_extreme_tol
)  # a high/low this far beyond anything around it is not a price
