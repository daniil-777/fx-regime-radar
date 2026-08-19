"""Free cross-asset / mood context series with an offline cache (phase 23).

Everything here is CONTEXT for the challenger forecaster only — nothing crosses the Rust wall
(CLAUDE.md rule 11) and nothing is a scored pair. Sources, all free, no API key:

* FRED CSV endpoint `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>`:
    - DTWEXBGS  Nominal Broad U.S. Dollar Index (the free DXY proxy: a trade-weighted basket
                published by the Fed in the weekly H.10 release — daily values, released once a
                week on Monday for the prior week, hence the long publication lag below).
    - VIXCLS    Cboe VIX close (FRED posts it the next day).
    - DGS2      2-year Treasury constant-maturity yield (H.15, posted next business day).
    - USEPUINDXD  daily US Economic Policy Uncertainty index (Baker-Bloom-Davis; computed from
                the next morning's newspapers, so it is known the day AFTER its date).
* Yahoo Finance `EURCHF=X` close via yfinance — a context series, NOT a scored pair.
* CFTC Traders in Financial Futures (TFF), EURO FX (CME, contract code 099741), leveraged-money
  long/short positions "as of Tuesday", released Friday 15:30 ET. Only the report date is
  stored here; the release lag is applied in `features_ext.apply_release_lag`.

Cache-first: every loader reads `data/context/*.csv`; the network is touched only when
`refresh=True` (CLI / daily stage) and every failure degrades to the cache with a log line,
never an exception — pytest and offline runs never need the network (brief rule 3).
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from fxradar import config

log = logging.getLogger(__name__)

CONTEXT_DIR: Path = config.DATA_DIR / "context"
CONTEXT_START = "2004-01-01"  # one year of warm-up before the price history starts (2005)

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_SERIES: dict[str, str] = {  # short name -> FRED id
    "dxy": "DTWEXBGS",
    "vix": "VIXCLS",
    "us2y": "DGS2",
    "epu": "USEPUINDXD",
}
EURCHF_TICKER = "EURCHF=X"

COT_URL_YEAR = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
COT_URL_2006_2016 = "https://www.cftc.gov/files/dea/history/fin_fut_txt_2006_2016.zip"
COT_EUR_CODE = "099741"  # EURO FX - CHICAGO MERCANTILE EXCHANGE
COT_COLUMNS = ["report_date", "lev_money_long", "lev_money_short"]
TIMEOUT = 60


# --------------------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------------------
def cache_path(name: str, context_dir: Path = CONTEXT_DIR) -> Path:
    """data/context/<name>.csv — one small CSV per raw series."""
    return context_dir / f"{name}.csv"


def _read_cache(name: str, context_dir: Path) -> pd.DataFrame | None:
    p = cache_path(name, context_dir)
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=[0])
    return df


def _write_cache(name: str, df: pd.DataFrame, context_dir: Path) -> None:
    context_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path(name, context_dir), index=False)


# --------------------------------------------------------------------------------------
# FRED
# --------------------------------------------------------------------------------------
def fetch_fred(series_id: str, start: str = CONTEXT_START) -> pd.DataFrame:
    """Download one FRED series as (date, value); missing prints ('.') are dropped, never filled."""
    r = requests.get(FRED_URL.format(series=series_id), timeout=TIMEOUT)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df = df[df["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    if df.empty:
        raise RuntimeError(f"FRED {series_id}: empty download")
    return df


# --------------------------------------------------------------------------------------
# EURCHF via yfinance (context only)
# --------------------------------------------------------------------------------------
def fetch_eurchf(start: str = CONTEXT_START) -> pd.DataFrame:
    """EURCHF=X daily close as (date, value). Same Yahoo snapshot timing as the scored pairs."""
    import yfinance as yf  # lazy: tests never import the network client

    raw = yf.download(
        EURCHF_TICKER,
        start=start,
        progress=False,
        auto_adjust=False,
        multi_level_index=False,
        threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("EURCHF=X: empty download")
    df = raw.rename(columns=str.lower)[["close"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df.dropna()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index < pd.Timestamp(datetime.now().date())]  # completed days only
    out = df.reset_index().rename(columns={"Date": "date", "index": "date", "close": "value"})
    out.columns = ["date", "value"]
    return out


# --------------------------------------------------------------------------------------
# CFTC TFF — EUR leveraged money
# --------------------------------------------------------------------------------------
def _parse_tff_zip(content: bytes) -> pd.DataFrame:
    """Trim one TFF history zip to the EUR FX rows we keep: report_date, lev long, lev short."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
        df = pd.read_csv(z.open(name), low_memory=False)
    code = df["CFTC_Contract_Market_Code"].astype(str).str.strip()
    eur = df[code == COT_EUR_CODE]
    out = pd.DataFrame(
        {
            "report_date": pd.to_datetime(
                eur["Report_Date_as_YYYY-MM-DD"], format="mixed", errors="coerce"
            ),
            "lev_money_long": pd.to_numeric(eur["Lev_Money_Positions_Long_All"], errors="coerce"),
            "lev_money_short": pd.to_numeric(eur["Lev_Money_Positions_Short_All"], errors="coerce"),
        }
    )
    # the 2006-2016 combined file uses "m/d/yyyy 12:00:00 AM"; to_datetime handles both formats,
    # but be explicit about dropping anything unparseable rather than guessing
    return out.dropna(subset=["report_date"]).reset_index(drop=True)


def fetch_cot_eur(
    first_year: int = 2017, last_year: int | None = None, cached: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Download and trim the TFF history (2006-2016 combined + one zip per later year).

    With a `cached` frame, only the zips from the cache's last report year onward are fetched and
    merged (the daily refresh then costs one ~0.5 MB zip, not the whole history)."""
    last_year = last_year or datetime.now().year
    parts = []
    if cached is not None and len(cached):
        parts.append(cached[COT_COLUMNS].copy())
        first_year = max(first_year, int(pd.to_datetime(cached["report_date"]).max().year))
    else:
        r = requests.get(COT_URL_2006_2016, timeout=TIMEOUT * 3)
        r.raise_for_status()
        parts.append(_parse_tff_zip(r.content))
    for year in range(first_year, last_year + 1):
        r = requests.get(COT_URL_YEAR.format(year=year), timeout=TIMEOUT)
        if r.status_code == 404:  # a year not yet published
            continue
        r.raise_for_status()
        parts.append(_parse_tff_zip(r.content))
    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates("report_date", keep="last").sort_values("report_date")
    return df[COT_COLUMNS].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# cache-first loader
# --------------------------------------------------------------------------------------
CONTEXT_NAMES: list[str] = [*FRED_SERIES, "eurchf", "cot_eur_lev"]


def _download(name: str, cached: pd.DataFrame | None = None) -> pd.DataFrame:
    if name in FRED_SERIES:
        return fetch_fred(FRED_SERIES[name])
    if name == "eurchf":
        return fetch_eurchf()
    if name == "cot_eur_lev":
        return fetch_cot_eur(cached=cached)
    raise KeyError(name)


def load_context(refresh: bool = False, context_dir: Path = CONTEXT_DIR) -> dict[str, pd.DataFrame]:
    """All context series as {name: DataFrame}. Cache-first; with `refresh=True` each series is
    re-downloaded and the cache overwritten ONLY on success — any failure logs and keeps the cached
    copy (a missing cache AND a failed download yield an empty frame, never an exception)."""
    out: dict[str, pd.DataFrame] = {}
    for name in CONTEXT_NAMES:
        cached = _read_cache(name, context_dir)
        if refresh:
            try:
                fresh = _download(name, cached)
                _write_cache(name, fresh, context_dir)
                cached = _read_cache(name, context_dir)  # use exactly what the disk holds: the
                # CSV round-trip is then the same in the daily stage and in an offline rebuild
                log.info("context %s: refreshed (%d rows)", name, len(fresh))
            except Exception as exc:  # network / parsing: degrade to cache, never crash
                log.warning("context %s: refresh failed (%s) — using cache", name, exc)
        if cached is None:
            log.warning("context %s: no cache and no download — feature will be NaN", name)
            cols = COT_COLUMNS if name == "cot_eur_lev" else ["date", "value"]
            cached = pd.DataFrame(
                {
                    c: pd.Series(dtype="datetime64[ns]" if i == 0 else "float64")
                    for i, c in enumerate(cols)
                }
            )
        out[name] = cached
    return out


def main() -> None:
    """CLI: refresh every context cache from the network (falls back per series)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ctx = load_context(refresh=True)
    for name, df in ctx.items():
        first = df.iloc[0, 0].date() if len(df) else None
        last = df.iloc[-1, 0].date() if len(df) else None
        print(f"{name:12s} {len(df):6d} rows  {first} -> {last}  ({cache_path(name)})")


if __name__ == "__main__":
    main()
