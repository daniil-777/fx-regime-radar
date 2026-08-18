"""Central configuration: pairs, tickers, date splits, and artifact paths.

Everything that is "a decision" rather than "a computation" lives here so that an
interviewer (or you, in six months) can find it in one place.
"""

from __future__ import annotations

from pathlib import Path

# ---- user-facing text ----------------------------------------------------------------
# CLAUDE.md rule 7: every user-facing surface carries this exact line.
DISCLAIMER = "Educational tool. Not investment advice."

# ---- universe --------------------------------------------------------------------------
PAIRS: list[str] = ["EURUSD", "USDCHF", "GBPUSD"]

# Yahoo Finance tickers. Note that USD/CHF is quoted as "CHF=X" on Yahoo (USD base).
YF_TICKERS: dict[str, str] = {
    "EURUSD": "EURUSD=X",
    "USDCHF": "CHF=X",
    "GBPUSD": "GBPUSD=X",
}

# Pairs quoted with USD as the BASE currency (price = foreign units per 1 USD). Their returns
# have the opposite sign to EURUSD/GBPUSD for the same "dollar move"; corr_20 flips them.
USD_BASE_PAIRS: frozenset[str] = frozenset({"USDCHF"})

# Plausible price ranges used as sanity bounds (a broken feed fails loudly, not silently).
PRICE_BOUNDS: dict[str, tuple[float, float]] = {
    "EURUSD": (0.7, 2.0),
    "USDCHF": (0.5, 2.0),
    "GBPUSD": (0.9, 2.5),
}

START_DATE = "2005-01-01"

# ---- time-ordered splits (CLAUDE.md rule 2) --------------------------------------------
TRAIN_END = "2016-12-31"  # train: dates <= TRAIN_END
VAL_START = "2017-01-01"  # validation: 2017-2018
VAL_END = "2018-12-31"
TEST_START = "2019-01-01"  # test: 2019+
EMBARGO_DAYS = 5  # trading days dropped after every split boundary

# ---- paths -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
DOCS_DIR = ROOT / "docs"

PRICES_PATH = DATA_DIR / "prices.parquet"
FEATURES_PATH = DATA_DIR / "features.parquet"
REGIMES_PATH = DATA_DIR / "regimes.parquet"
REPORT_PATH = DATA_DIR / "report.json"

# ---- data contract: prices.parquet -----------------------------------------------------
PRICE_COLUMNS: list[str] = ["date", "pair", "open", "high", "low", "close"]

# ---- ECB cross-validation (phase 01) ---------------------------------------------------
# frankfurter.app redirects here; we call the canonical host directly.
FRANKFURTER_URL = "https://api.frankfurter.dev/v1"
ECB_LOOKBACK_YEARS = 3
ECB_WARN_MEAN_PCT = 0.5  # log a WARNING above this mean absolute % deviation
ECB_FAIL_MEAN_PCT = 2.0  # raise above this

# ---- corrupted-print filters (phase 01) ------------------------------------------------
BAD_TICK_JUMP = 0.04  # reverting close jumps > 4% in AND > 4% back out (close outside neighbours)
BAD_TICK_JUMP_BAR = 0.02  # ... or > 2% each way when the WHOLE bar is disjoint from its neighbours
BAD_TICK_REVERT = 0.02  # ... while the two-day through-move stays < 2%
BAD_EXTREME_TOL = 0.20  # a high/low > 20% beyond anything printed around it is not a price
