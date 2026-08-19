"""Phase 23 tests: events calendar, countdown features, lagged context alignment, the COT release
lag, Yang-Zhang, train-only scaler and the truncation-invariance (causality) proof for EVERY
features_ext column. No network: context series are synthetic frames."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fxradar import calendar_ext, config, features_ext

# --------------------------------------------------------------------------------------
# fixtures (synthetic context, toy events)
# --------------------------------------------------------------------------------------


def _synthetic_context(start="2014-01-01", end="2016-03-31", seed=0) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, end)
    ctx = {}
    for name, level in [("dxy", 100.0), ("vix", 15.0), ("eurchf", 1.1), ("epu", 120.0)]:
        x = level * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
        ctx[name] = pd.DataFrame({"date": days, "value": x})
    ctx["us2y"] = pd.DataFrame(
        {"date": days, "value": 1.0 + np.cumsum(rng.normal(0, 0.02, len(days)))}
    )
    tuesdays = pd.date_range(start, end, freq="W-TUE")
    ctx["cot_eur_lev"] = pd.DataFrame(
        {
            "report_date": tuesdays,
            "lev_money_long": rng.integers(20_000, 120_000, len(tuesdays)).astype(float),
            "lev_money_short": rng.integers(20_000, 120_000, len(tuesdays)).astype(float),
        }
    )
    return ctx


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return calendar_ext.load_events()  # the committed data/events.csv (small, hand-built)


@pytest.fixture(scope="module")
def context() -> dict[str, pd.DataFrame]:
    return _synthetic_context()


@pytest.fixture(scope="module")
def built(prices_sample, context, events):
    ext, scaler = features_ext.build_features_ext(
        prices_sample, context, events, scaler=None, train_end="2015-06-30"
    )
    return ext, scaler


# --------------------------------------------------------------------------------------
# events.csv + calendar features
# --------------------------------------------------------------------------------------
def test_events_csv_is_sane(events) -> None:
    assert list(events.columns) == ["date", "type", "source"]
    assert set(events["type"]) == set(calendar_ext.EVENT_TYPES)
    assert not events.duplicated(["date", "type"]).any()
    assert events["date"].dt.weekday.lt(5).all()  # decisions / releases fall on weekdays
    years = events.groupby("type")["date"].agg(lambda s: s.dt.year.nunique())
    assert (years >= 22).all()  # 2005..2026 for every type
    per_year = events.groupby(["type", events["date"].dt.year]).size()
    assert (
        per_year.loc["FOMC"].between(7, 8).all()
    )  # 8 scheduled meetings (2020: 7 — one cancelled)
    assert per_year.loc["SNB"].eq(4).all()  # quarterly assessments
    assert (events.loc[events["type"] == "SNB", "date"].dt.weekday == 3).all()  # Thursdays
    # spot checks against the official calendars
    have = set(zip(events["type"], events["date"].dt.strftime("%Y-%m-%d"), strict=True))
    for t, d in [
        ("FOMC", "2022-06-15"), ("FOMC", "2008-12-16"), ("FOMC", "2026-12-09"),
        ("ECB", "2022-07-21"), ("ECB", "2016-12-08"), ("SNB", "2015-03-19"),
        ("SNB", "2026-12-10"), ("BOE", "2016-08-04"), ("BOE", "2026-12-17"),
        ("NFP", "2024-01-05"), ("NFP", "2013-10-22"), ("CPI", "2022-06-10"),
    ]:  # fmt: skip
        assert (t, d) in have, (t, d)
    # unscheduled events are deliberately absent: the honest limit of a calendar feature
    assert ("SNB", "2015-01-15") not in have and ("FOMC", "2020-03-15") not in have


def test_days_to_and_since_semantics() -> None:
    ev = pd.DataFrame({"date": pd.to_datetime(["2020-01-10", "2020-02-14"]), "type": "FOMC"})
    dates = pd.Series(
        pd.to_datetime(["2020-01-08", "2020-01-10", "2020-01-13", "2020-02-14", "2020-03-01"])
    )
    to = calendar_ext.days_to_next(dates, ev["date"])
    since = calendar_ext.days_since_last(dates, ev["date"])
    assert to.tolist()[:4] == [2.0, 0.0, 32.0, 0.0] and np.isnan(to.iloc[4])  # schedule ran out
    assert np.isnan(since.iloc[0]) and since.tolist()[1:] == [0.0, 3.0, 0.0, 16.0]


def test_calendar_features_never_negative_and_only_schedule(built, events) -> None:
    ext, _ = built
    cal = ext[calendar_ext.CALENDAR_FEATURES]
    assert (cal.fillna(0) >= 0).all().all()
    # on every row, date + days_to is a scheduled date of that type (and nothing else)
    for t in calendar_ext.EVENT_TYPES:
        sched = set(events.loc[events["type"] == t, "date"])
        nxt = ext["date"] + pd.to_timedelta(ext[f"days_to_{t}"], unit="D")
        assert nxt.isin(sched).all()
        prev = ext["date"] - pd.to_timedelta(ext[f"days_since_{t}"], unit="D")
        assert prev.isin(sched).all()
    # the SNB floor removal day was NOT a scheduled assessment: countdown still pointed to March
    row = ext[(ext["pair"] == "USDCHF") & (ext["date"] == "2015-01-15")].iloc[0]
    assert row["days_to_SNB"] == 63 and row["days_since_SNB"] == 35


# --------------------------------------------------------------------------------------
# lagged alignment + the COT release lag
# --------------------------------------------------------------------------------------
def test_align_asof_respects_publication_lag() -> None:
    tab = pd.DataFrame({"date": pd.to_datetime(["2020-01-06", "2020-01-07"]), "x": [1.0, 2.0]})
    t = pd.Series(
        pd.to_datetime(["2020-01-06", "2020-01-07", "2020-01-08", "2020-01-14", "2020-01-15"])
    )
    out = features_ext.align_asof(t, tab, "date", lag_days=8)["x"].tolist()
    assert np.isnan(out[0]) and np.isnan(out[1]) and np.isnan(out[2])  # nothing published yet
    assert out[3] == 1.0 and out[4] == 2.0  # Jan 6 value usable from Jan 14, Jan 7 from Jan 15


def test_cot_release_lag_tuesday_report_visible_from_friday() -> None:
    cot = pd.DataFrame(
        {
            "report_date": pd.to_datetime(["2023-12-26", "2024-01-02"]),
            "lev_money_long": [100.0, 150.0],
            "lev_money_short": [40.0, 50.0],
        }
    )
    lagged = features_ext.apply_release_lag(cot, "report_date", release_offset_days=3)
    assert lagged["release_date"].tolist() == list(pd.to_datetime(["2023-12-29", "2024-01-05"]))
    tab = features_ext.cot_transforms(cot)
    days = pd.Series(pd.bdate_range("2024-01-02", "2024-01-08"))  # Tue .. Mon
    net = features_ext.align_asof(days, tab, "release_date", 0)["cot_eur_net"]
    by_day = dict(zip(days.dt.strftime("%a %d"), net.tolist(), strict=True))
    assert by_day["Tue 02"] == 60.0 and by_day["Wed 03"] == 60.0 and by_day["Thu 04"] == 60.0
    assert by_day["Fri 05"] == 100.0 and by_day["Mon 08"] == 100.0  # known only from the release


# --------------------------------------------------------------------------------------
# Yang-Zhang
# --------------------------------------------------------------------------------------
def _yz_by_hand(ohlc: pd.DataFrame, n: int) -> float:
    """Literal Yang-Zhang (2000) for the LAST window of `ohlc`."""
    g = ohlc.tail(n + 1).reset_index(drop=True)
    o = np.log(g["open"][1:].to_numpy() / g["close"][:-1].to_numpy())
    c = np.log(g["close"][1:].to_numpy() / g["open"][1:].to_numpy())
    u = np.log(g["high"][1:].to_numpy() / g["open"][1:].to_numpy())
    d = np.log(g["low"][1:].to_numpy() / g["open"][1:].to_numpy())
    rs = np.mean(u * (u - c) + d * (d - c))
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    var = np.var(o, ddof=1) + k * np.var(c, ddof=1) + (1 - k) * rs
    return float(np.sqrt(var * config.TRADING_DAYS))


def test_yang_zhang_matches_literal_formula(prices_sample) -> None:
    g = prices_sample[prices_sample["pair"] == "EURUSD"].sort_values("date").reset_index(drop=True)
    yz = features_ext.yang_zhang(g, window=20)
    assert np.isnan(yz.iloc[:20]).all() and np.isfinite(yz.iloc[20:]).all()
    assert abs(yz.iloc[-1] - _yz_by_hand(g, 20)) < 1e-12
    assert abs(yz.iloc[100] - _yz_by_hand(g.iloc[:101], 20)) < 1e-12


def test_yang_zhang_zero_for_flat_prices() -> None:
    flat = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=range(40))
    assert features_ext.yang_zhang(flat, 20).iloc[-1] == 0.0


def test_yang_zhang_truncation_invariant(prices_sample) -> None:
    g = prices_sample[prices_sample["pair"] == "GBPUSD"].sort_values("date").reset_index(drop=True)
    full = features_ext.yang_zhang(g, 20)
    part = features_ext.yang_zhang(g.iloc[:-30], 20)
    pd.testing.assert_series_equal(full.iloc[:-30], part, check_exact=True)


# --------------------------------------------------------------------------------------
# assembly, scaler, causality
# --------------------------------------------------------------------------------------
def test_build_has_contract_columns_and_scaled_train(built) -> None:
    ext, scaler = built
    assert list(ext.columns) == features_ext.EXT_COLUMNS
    assert scaler["train_end"] == "2015-06-30"
    tr = ext[ext["date"] <= "2015-06-30"]
    for col in ["dxy_chg_1d", "vix_z20", "us2y_chg_5d", "epu_chg_1d", "eurchf_chg_1d"]:
        assert abs(tr[col].mean()) < 1e-9 and abs(tr[col].std() - 1.0) < 1e-9  # train-only z
    assert (ext["vol_20_yz"].dropna() >= 0).all()


def test_scaler_uses_train_rows_only(prices_sample, context, events) -> None:
    ctx2 = {k: v.copy() for k, v in context.items()}
    after = ctx2["vix"]["date"] > "2015-06-30"
    ctx2["vix"].loc[after, "value"] *= 3.0  # corrupt the FUTURE only
    _, s1 = features_ext.build_features_ext(prices_sample, context, events, None, "2015-06-30")
    _, s2 = features_ext.build_features_ext(prices_sample, ctx2, events, None, "2015-06-30")
    assert s1["columns"]["vix_chg_1d"] == s2["columns"]["vix_chg_1d"]
    assert s1["columns"]["vix_z20"]["mean"] == s2["columns"]["vix_z20"]["mean"]


def test_missing_context_degrades_to_nan(prices_sample, events) -> None:
    ext, scaler = features_ext.build_features_ext(prices_sample, {}, events, None, "2015-06-30")
    assert ext[features_ext.CONTEXT_FEATURES].isna().all().all()
    assert ext[calendar_ext.CALENDAR_FEATURES].notna().any().any()
    assert ext["vol_20_yz"].notna().any()
    assert np.isnan(scaler["columns"]["dxy_chg_1d"]["std"])  # no silent numbers


def test_every_features_ext_column_is_truncation_invariant(
    prices_sample, context, events, built
) -> None:
    """Causality proof (CLAUDE.md rule 1): cut prices AND every context series at T, rebuild with the
    frozen scaler, and every column must reproduce the rows <= T exactly — bit for bit."""
    _, scaler = built
    T = pd.Timestamp("2015-09-30")
    full, _ = features_ext.build_features_ext(prices_sample, context, events, scaler)
    cut_prices = prices_sample[prices_sample["date"] <= T]
    cut_ctx = {}
    for name, df in context.items():
        col = "report_date" if name == "cot_eur_lev" else "date"
        cut_ctx[name] = df[df[col] <= T]
    part, _ = features_ext.build_features_ext(cut_prices, cut_ctx, events, scaler)
    assert len(part) < len(full) and part["date"].max() <= T
    ov = full.merge(part[["date", "pair"]], on=["date", "pair"])
    pd.testing.assert_frame_equal(
        ov.reset_index(drop=True), part.reset_index(drop=True), check_exact=True
    )
    assert list(part.columns) == features_ext.EXT_COLUMNS  # every column covered


def test_align_to_features_keeps_feature_rows(built, prices_sample) -> None:
    ext, _ = built
    feats = prices_sample[["date", "pair"]].groupby("pair").tail(50)
    aligned = features_ext.align_to_features(ext, feats)
    assert len(aligned) == len(feats)
    assert set(aligned.columns) == set(features_ext.EXT_COLUMNS)


_have = features_ext.FEATURES_EXT_PATH.exists() and config.FEATURES_PATH.exists()


@pytest.mark.skipif(not _have, reason="features_ext.parquet not built")
def test_committed_features_ext_matches_features_rows() -> None:
    ext = pd.read_parquet(features_ext.FEATURES_EXT_PATH)
    feats = pd.read_parquet(config.FEATURES_PATH)
    assert list(ext.columns) == features_ext.EXT_COLUMNS
    assert len(ext) == len(feats)
    assert ext.merge(feats[["date", "pair"]], on=["date", "pair"]).shape[0] == len(feats)
    assert (ext[calendar_ext.CALENDAR_FEATURES].fillna(0) >= 0).all().all()
    assert features_ext.SCALER_PATH.exists()
