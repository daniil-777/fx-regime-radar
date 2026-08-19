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

# G10: the ten most important FREE-FLOATING pairs. Ranking source: BIS Triennial Survey, April 2025
# turnover shares — EUR/USD 21.2 %, USD/JPY 14.3 %, GBP/USD 7.6 %, USD/CAD 5.3 %, AUD/USD 4.9 %,
# USD/CHF 4.9 %, then EUR/GBP, EUR/JPY, NZD/USD (~1.5–2 % each). USD/CNY (8.1 %), USD/HKD (3.6 %),
# USD/SGD (2.2 %) and USD/INR (1.9 %) rank higher by turnover but are managed floats / pegs — a
# volatility-regime model is blind to a managed currency by construction (the EUR/CHF-floor lesson),
# so they are deliberately excluded. EUR/CHF — the Swiss treasurer's own cross — was tried as the
# tenth pair and REJECTED by the data: its 2011–2015 floor sits inside the training years, returns
# there are ~0, and EM collapses a state onto a singular covariance (the fit raises). A pegged
# instrument cannot be a vol-regime instrument; it stays a context series (phase 23). The tenth
# pair is USD/SEK, the most traded remaining G10 currency. Same splits, day-count, cleaning
# thresholds and cost model as `fx`; `fx` itself stays byte-identical (its bundle / goldens / ledger).
G10 = Universe(
    name="g10",
    label="FX G10",
    pairs=[
        "EURUSD",
        "USDJPY",
        "GBPUSD",
        "USDCAD",
        "AUDUSD",
        "USDCHF",
        "NZDUSD",
        "EURGBP",
        "EURJPY",
        "USDSEK",
    ],
    tickers={
        "EURUSD": "EURUSD=X",
        "USDJPY": "JPY=X",
        "GBPUSD": "GBPUSD=X",
        "USDCAD": "CAD=X",
        "AUDUSD": "AUDUSD=X",
        "USDCHF": "CHF=X",
        "NZDUSD": "NZDUSD=X",
        "EURGBP": "EURGBP=X",
        "EURJPY": "EURJPY=X",
        "USDSEK": "SEK=X",
    },
    price_bounds={
        "EURUSD": (0.7, 2.0),
        "USDJPY": (70.0, 200.0),
        "GBPUSD": (0.9, 2.5),
        "USDCAD": (0.8, 1.8),
        "AUDUSD": (0.4, 1.2),
        "USDCHF": (0.5, 2.0),
        "NZDUSD": (0.35, 1.0),
        "EURGBP": (0.5, 1.1),
        "EURJPY": (80.0, 200.0),
        "USDSEK": (5.0, 14.0),
    },
    # corr_20 sign convention: returns are flipped for USD-base pairs so that "dollar weakens" reads
    # as a positive return everywhere a dollar leg exists; euro crosses carry no dollar leg and are
    # left as quoted (a cross can correlate either way with the dollar by construction).
    usd_base_pairs=frozenset({"USDJPY", "USDCAD", "USDCHF", "USDSEK"}),
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
    ecb_checks={
        "EURUSD": ("EUR", "USD"),
        "USDJPY": ("USD", "JPY"),
        "GBPUSD": ("GBP", "USD"),
        "USDCAD": ("USD", "CAD"),
        "AUDUSD": ("AUD", "USD"),
        "USDCHF": ("USD", "CHF"),
        "NZDUSD": ("NZD", "USD"),
        "EURGBP": ("EUR", "GBP"),
        "EURJPY": ("EUR", "JPY"),
        "USDSEK": ("USD", "SEK"),
    },
    pair_dummies=[
        "pair_USDJPY",
        "pair_GBPUSD",
        "pair_USDCAD",
        "pair_AUDUSD",
        "pair_USDCHF",
        "pair_NZDUSD",
        "pair_EURGBP",
        "pair_EURJPY",
        "pair_USDSEK",
    ],
    known_events={
        "EURUSD": [("2020-03-16", "March 2020 (COVID)")],
        "USDJPY": [("2024-08-05", "yen carry unwind"), ("2022-10-21", "MoF intervention")],
        "GBPUSD": [
            ("2016-06-24", "Brexit vote"),
            ("2016-10-07", "sterling flash crash"),
            ("2022-09-26", "mini-budget gilt crisis"),
        ],
        "USDCAD": [("2020-03-19", "March 2020 (COVID)")],
        "AUDUSD": [("2020-03-19", "March 2020 (COVID)")],
        "USDCHF": [("2015-01-15", "SNB floor removal")],
        "NZDUSD": [("2020-03-19", "March 2020 (COVID)")],
        "EURGBP": [("2016-06-24", "Brexit vote")],
        "EURJPY": [("2024-08-05", "yen carry unwind")],
        "USDSEK": [("2020-03-19", "March 2020 (COVID)")],
    },
    pair_words={
        "EURUSD": "this being the euro",
        "USDJPY": "this being the yen",
        "GBPUSD": "this being sterling",
        "USDCAD": "this being the Canadian dollar",
        "AUDUSD": "this being the Australian dollar",
        "USDCHF": "this being the Swiss franc",
        "NZDUSD": "this being the New Zealand dollar",
        "EURGBP": "this being the euro–sterling cross",
        "EURJPY": "this being the euro–yen cross",
        "USDSEK": "this being the Swedish krona",
    },
    subdir="g10",
)

# Crypto: 7-day markets with 65–120 % annualised vol. Instruments = the five largest
# non-stablecoin assets by market capitalisation (2026: BTC, ETH, XRP, BNB, SOL, then ADA …) that
# have at least three years of history BEFORE the frozen split: SOL (listed 2020-04) would leave
# ~205 usable training days for a ~50-parameter HMM, so it is excluded until the next split
# revision and ADA takes the fifth slot; LTC (2014 history, no longer top-10) was retired on
# 2026-08-19. History starts 2017-11-09, the first day all five trade (BTC alone before that would
# have an undefined cross-pair correlation feature); that still leaves ~3 years of training. Splits give a full
# crash cycle in validation (2021 top → 2022 Terra/FTX) and 2023+ as the frozen test. Corrupted-
# print thresholds are sized for a market where a 4 % day is Tuesday; costs reflect exchange taker
# fees + wide books. The 2026-08-19 redefinition refit the models under hmm 0.4.1 — its live ledger
# therefore carries the old three-coin rows as a closed segment and a new one from that date.
CRYPTO = Universe(
    name="crypto",
    label="Crypto majors",
    pairs=["BTC-USD", "ETH-USD", "XRP-USD", "BNB-USD", "ADA-USD"],
    tickers={
        "BTC-USD": "BTC-USD",
        "ETH-USD": "ETH-USD",
        "XRP-USD": "XRP-USD",
        "BNB-USD": "BNB-USD",
        "ADA-USD": "ADA-USD",
    },
    price_bounds={
        "BTC-USD": (50.0, 1_000_000.0),
        "ETH-USD": (0.2, 100_000.0),
        "XRP-USD": (0.001, 100.0),
        "BNB-USD": (0.05, 10_000.0),
        "ADA-USD": (0.001, 100.0),
    },
    usd_base_pairs=frozenset(),
    start_date="2017-11-09",
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
    pair_dummies=["pair_ETH-USD", "pair_XRP-USD", "pair_BNB-USD", "pair_ADA-USD"],
    known_events={
        "BTC-USD": [("2020-03-12", "COVID 'Black Thursday'"), ("2022-11-09", "FTX collapse")],
        "ETH-USD": [("2021-05-19", "May 2021 crash"), ("2022-05-12", "Terra/LUNA collapse")],
        "XRP-USD": [("2020-12-23", "SEC lawsuit filed"), ("2023-07-13", "SEC ruling")],
        "BNB-USD": [("2023-06-05", "SEC v. Binance"), ("2022-11-09", "FTX collapse")],
        "ADA-USD": [("2021-05-19", "May 2021 crash"), ("2022-05-12", "Terra/LUNA collapse")],
    },
    pair_words={
        "BTC-USD": "this being bitcoin",
        "ETH-USD": "this being ether",
        "XRP-USD": "this being XRP",
        "BNB-USD": "this being BNB",
        "ADA-USD": "this being cardano",
    },
    subdir="crypto",
)

UNIVERSES: dict[str, Universe] = {"fx": FX, "g10": G10, "crypto": CRYPTO}


def get(name: str) -> Universe:
    try:
        return UNIVERSES[name]
    except KeyError as exc:
        raise KeyError(f"unknown universe {name!r}; choose from {sorted(UNIVERSES)}") from exc
