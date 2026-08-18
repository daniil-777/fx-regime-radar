"""Universes: the instrument sets the pipeline can run on. Selected with FXRADAR_UNIVERSE.

The pipeline is universe-agnostic; everything that differs between markets — tickers, plausible
price bounds, split dates, day-count for annualisation, corrupted-print thresholds, cost model,
which official cross-check exists, and the named storms — lives here in ONE record per universe.
`fx` keeps every value the project shipped with (its bundle/goldens must keep replaying).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Universe:
    name: str
    label: str
    pairs: list[str]
    tickers: dict[str, str]
    price_bounds: dict[str, tuple[float, float]]
    usd_base_pairs: frozenset[str]
    start_date: str
    train_end: str
    val_start: str
    val_end: str
    test_start: str
    trading_days: int  # 252 for FX (weekdays), 365 for crypto (7-day markets)
    bad_tick_jump: float
    bad_tick_jump_bar: float
    bad_tick_revert: float
    bad_extreme_tol: float
    cost_base_bps: float
    cost_vol_mult: float
    ecb_checks: dict[str, tuple[str, str]]  # pair -> (base, quote) for the frankfurter cross-check
    pair_dummies: list[
        str
    ]  # forecaster one-hots (base pair dropped) — explicit so FX stays identical
    known_events: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # siren audit
    pair_words: dict[str, str] = field(default_factory=dict)  # narrator: "this being sterling"
    subdir: str = ""  # artifact sub-directory ("" = repo defaults, used by fx)

    def display(self, pair: str) -> str:
        """Human label for a pair: EURUSD -> EUR/USD, BTC-USD -> BTC/USD."""
        p = pair.replace("-", "")
        return f"{p[:3]}/{p[3:]}" if len(p) == 6 else pair


FX = Universe(
    name="fx",
    label="FX majors",
    pairs=["EURUSD", "USDCHF", "GBPUSD"],
    tickers={"EURUSD": "EURUSD=X", "USDCHF": "CHF=X", "GBPUSD": "GBPUSD=X"},
    price_bounds={"EURUSD": (0.7, 2.0), "USDCHF": (0.5, 2.0), "GBPUSD": (0.9, 2.5)},
    usd_base_pairs=frozenset({"USDCHF"}),
    start_date="2005-01-01",
    train_end="2016-12-31",
    val_start="2017-01-01",
    val_end="2018-12-31",
    test_start="2019-01-01",
    trading_days=252,
    bad_tick_jump=0.04,
    bad_tick_jump_bar=0.02,
    bad_tick_revert=0.02,
    bad_extreme_tol=0.20,
    cost_base_bps=1.0,
    cost_vol_mult=80.0,
    ecb_checks={"EURUSD": ("EUR", "USD"), "USDCHF": ("USD", "CHF")},
    pair_dummies=["pair_GBPUSD", "pair_USDCHF"],
    known_events={
        "USDCHF": [("2015-01-15", "SNB floor removal")],
        "GBPUSD": [("2016-06-24", "Brexit vote"), ("2016-10-07", "sterling flash crash")],
        "EURUSD": [("2020-03-16", "March 2020 (COVID)")],
    },
    pair_words={
        "GBPUSD": "this being sterling",
        "USDCHF": "this being the Swiss franc",
        "EURUSD": "this being the euro",
    },
    subdir="",
)

# Crypto: 7-day markets with 65–120 % annualised vol. Longest histories on Yahoo: BTC and LTC from
# 2014-09, ETH from 2017-11. Splits give train ~6 years (BTC/LTC), a full crash cycle in validation
# (2021 top → 2022 Terra/FTX), and 2023+ as the frozen test. Corrupted-print thresholds are sized
# for a market where a 4 % day is Tuesday, and costs reflect exchange taker fees + wide books.
CRYPTO = Universe(
    name="crypto",
    label="Crypto majors",
    pairs=["BTC-USD", "ETH-USD", "LTC-USD"],
    tickers={"BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD", "LTC-USD": "LTC-USD"},
    price_bounds={
        "BTC-USD": (50.0, 1_000_000.0),
        "ETH-USD": (0.2, 100_000.0),
        "LTC-USD": (0.5, 10_000.0),
    },
    usd_base_pairs=frozenset(),
    start_date="2014-09-17",
    train_end="2020-12-31",
    val_start="2021-01-01",
    val_end="2022-12-31",
    test_start="2023-01-01",
    trading_days=365,
    bad_tick_jump=0.30,
    bad_tick_jump_bar=0.15,
    bad_tick_revert=0.05,
    bad_extreme_tol=0.60,
    cost_base_bps=8.0,
    cost_vol_mult=20.0,
    ecb_checks={},
    pair_dummies=["pair_ETH-USD", "pair_LTC-USD"],
    known_events={
        "BTC-USD": [("2020-03-12", "COVID 'Black Thursday'"), ("2022-11-09", "FTX collapse")],
        "ETH-USD": [("2021-05-19", "May 2021 crash"), ("2022-05-12", "Terra/LUNA collapse")],
        "LTC-USD": [("2018-01-16", "2018 crypto winter begins")],
    },
    pair_words={
        "BTC-USD": "this being bitcoin",
        "ETH-USD": "this being ether",
        "LTC-USD": "this being litecoin",
    },
    subdir="crypto",
)

UNIVERSES: dict[str, Universe] = {"fx": FX, "crypto": CRYPTO}


def get(name: str) -> Universe:
    try:
        return UNIVERSES[name]
    except KeyError as exc:
        raise KeyError(f"unknown universe {name!r}; choose from {sorted(UNIVERSES)}") from exc
