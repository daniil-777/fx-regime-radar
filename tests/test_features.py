"""Tests for the feature engine (phase 02) — including the truncation-invariance leakage test."""

import numpy as np
import pandas as pd
import pytest

from fxradar import config, features


def _prices(closes: dict[str, list[float]], start: str = "2020-01-01") -> pd.DataFrame:
    """Build a tidy price frame from per-pair close lists (open=high=low=close on business days)."""
    frames = []
    for pair, c in closes.items():
        dates = pd.bdate_range(start, periods=len(c))
        frames.append(
            pd.DataFrame({"date": dates, "pair": pair, "open": c, "high": c, "low": c, "close": c})
        )
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------------------
def test_schema_matches_contract(prices_sample: pd.DataFrame) -> None:
    feats = features.build_features(prices_sample)
    assert list(feats.columns) == features.FEATURE_COLUMNS
    assert features.FEATURE_COLUMNS == [
        "date", "pair", "ret_1d", "vol_20", "vol_60", "vol_ratio", "mom_20", "rng_hl", "corr_20", "ret_5d_abs",
    ]  # fmt: skip
    assert set(feats["pair"]) == set(config.PAIRS)
    for _, g in feats.groupby("pair"):
        assert g["date"].is_monotonic_increasing and g["date"].is_unique
        assert len(g) == (prices_sample["pair"] == g["pair"].iloc[0]).sum() - features.WARMUP_ROWS
    for col in features.BASE_FEATURES:
        assert feats[col].dtype == np.float64


def test_no_nans_after_warmup(prices_sample: pd.DataFrame) -> None:
    feats = features.build_features(prices_sample)
    assert int(features.nan_report(feats).sum()) == 0


# --------------------------------------------------------------------------------------
# toy correctness
# --------------------------------------------------------------------------------------
def test_constant_prices_give_zero_return_and_vol() -> None:
    n = 100
    prices = _prices({"EURUSD": [1.1] * n, "USDCHF": [0.9] * n, "GBPUSD": [1.3] * n})
    feats = features.build_features(prices)
    assert len(feats) == 3 * (n - features.WARMUP_ROWS)
    assert (feats["ret_1d"] == 0).all()
    assert (feats["vol_20"] == 0).all()
    assert (feats["vol_60"] == 0).all()
    assert (feats["mom_20"] == 0).all()
    assert (feats["ret_5d_abs"] == 0).all()
    assert (feats["rng_hl"] == 0).all()


def test_vol_20_matches_hand_computation() -> None:
    """A tiny deterministic series: vol_20 on the last row = std(last 20 log returns, ddof=1)*sqrt(252)."""
    rng = np.random.default_rng(0)
    n = 80
    closes = {p: list(1.0 + np.cumsum(rng.normal(0, 0.005, n))) for p in config.PAIRS}
    feats = features.build_features(_prices(closes))
    for pair, c in closes.items():
        c = np.asarray(c)
        r = np.diff(np.log(c))  # r[i] is the return on day i+1
        expected = np.std(r[-20:], ddof=1) * np.sqrt(252)
        got = feats.loc[feats["pair"] == pair, "vol_20"].iloc[-1]
        assert got == pytest.approx(expected, rel=1e-12)
        exp_ret = np.log(c[-1] / c[-2])
        assert feats.loc[feats["pair"] == pair, "ret_1d"].iloc[-1] == pytest.approx(
            exp_ret, rel=1e-12
        )
        exp_mom = c[-1] / c[-21] - 1
        assert feats.loc[feats["pair"] == pair, "mom_20"].iloc[-1] == pytest.approx(
            exp_mom, rel=1e-12
        )
        exp_ratio = (np.std(r[-5:], ddof=1) * np.sqrt(252)) / (
            np.std(r[-60:], ddof=1) * np.sqrt(252)
        )
        assert feats.loc[feats["pair"] == pair, "vol_ratio"].iloc[-1] == pytest.approx(
            exp_ratio, rel=1e-12
        )


def _prices_hl(closes: dict[str, np.ndarray], start: str = "2020-01-01") -> pd.DataFrame:
    """Like _prices but with a VARYING intraday range and open != close."""
    rng = np.random.default_rng(42)
    frames = []
    for pair, c in closes.items():
        c = np.asarray(c)
        n = len(c)
        high = c * (1 + rng.uniform(0.0005, 0.004, n))
        low = c * (1 - rng.uniform(0.0005, 0.004, n))
        frames.append(
            pd.DataFrame(
                {
                    "date": pd.bdate_range(start, periods=n),
                    "pair": pair,
                    "open": c * 1.0003,
                    "high": high,
                    "low": low,
                    "close": c,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_rng_hl_ret_5d_abs_vol_60_match_hand_computation() -> None:
    rng = np.random.default_rng(0)
    n = 80
    closes = {p: 1.0 + np.cumsum(rng.normal(0, 0.005, n)) for p in config.PAIRS}
    prices = _prices_hl(closes)
    feats = features.build_features(prices)
    for pair, c in closes.items():
        g = prices[prices["pair"] == pair]
        rel_range = ((g["high"] - g["low"]) / g["close"]).to_numpy()
        row = feats[feats["pair"] == pair].iloc[-1]
        assert row["rng_hl"] == pytest.approx(rel_range[-10:].mean(), rel=1e-12)
        assert row["ret_5d_abs"] == pytest.approx(abs(c[-1] / c[-6] - 1), rel=1e-12)
        r = np.diff(np.log(c))
        assert row["vol_60"] == pytest.approx(np.std(r[-60:], ddof=1) * np.sqrt(252), rel=1e-12)


def test_corr_20_is_mean_of_two_pairwise_correlations() -> None:
    rng = np.random.default_rng(1)
    n = 90
    closes = {p: list(1.0 + np.cumsum(rng.normal(0, 0.005, n))) for p in config.PAIRS}
    feats = features.build_features(_prices(closes))
    rets = {p: np.diff(np.log(np.asarray(c)))[-20:] for p, c in closes.items()}
    for p in config.USD_BASE_PAIRS:
        rets[p] = -rets[p]  # one sign convention: foreign currency vs USD
    for a in config.PAIRS:
        expected = np.mean([np.corrcoef(rets[a], rets[b])[0, 1] for b in config.PAIRS if b != a])
        got = feats.loc[feats["pair"] == a, "corr_20"].iloc[-1]
        assert got == pytest.approx(expected, rel=1e-10)


def test_corr_20_sign_convention_makes_dollar_days_positive() -> None:
    """If EURUSD and GBPUSD rise exactly when USDCHF falls (a pure dollar move), corr_20 must be +1."""
    rng = np.random.default_rng(3)
    n = 90
    usd = rng.normal(0, 0.005, n)  # a common dollar factor
    closes = {
        "EURUSD": list(1.1 * np.exp(np.cumsum(usd))),
        "GBPUSD": list(1.3 * np.exp(np.cumsum(usd))),
        "USDCHF": list(0.9 * np.exp(np.cumsum(-usd))),
    }
    feats = features.build_features(_prices(closes))
    assert np.allclose(feats["corr_20"], 1.0, atol=1e-9)


def test_corr_20_hole_in_one_pair_freezes_only_that_component() -> None:
    """Remove a 10-day stretch from EURUSD: GBPUSD's corr_20 must keep moving (its GBPUSD-USDCHF
    component still updates); on EURUSD's own missing days nothing is emitted for EURUSD."""
    rng = np.random.default_rng(2)
    n = 120
    closes = {p: list(1.0 + np.cumsum(rng.normal(0, 0.005, n))) for p in config.PAIRS}
    prices = _prices(closes)
    eur_dates = prices.loc[prices["pair"] == "EURUSD", "date"]
    hole = set(eur_dates.iloc[-15:-5])
    cut = prices[~((prices["pair"] == "EURUSD") & prices["date"].isin(hole))]
    feats = features.build_features(cut)
    g = feats[feats["pair"] == "GBPUSD"].set_index("date")["corr_20"]
    inside = g.loc[sorted(hole)]
    assert inside.notna().all()
    assert inside.nunique() == len(inside)  # not frozen: the GBPUSD-USDCHF leg keeps updating
    assert feats["corr_20"].notna().all()
    assert not feats.loc[feats["pair"] == "EURUSD", "date"].isin(hole).any()

    # and the value on GBPUSD dates is the mean of the two pairwise, as-of aligned components
    full = features.build_features(prices)
    d = sorted(hole)[-1]
    # EURUSD-GBPUSD component is stale (last common date before the hole), GBPUSD-USDCHF fresh
    assert g.loc[d] != full[full["pair"] == "GBPUSD"].set_index("date")["corr_20"].loc[d]


def test_corr_20_is_nan_on_zero_variance_window_not_a_stale_value() -> None:
    """A flat 25-day stretch makes the 20-day correlation undefined: corr_20 must be NaN there,
    never the last defined value carried forward."""
    rng = np.random.default_rng(4)
    n = 130
    closes = {p: 1.0 + np.cumsum(rng.normal(0, 0.005, n)) for p in config.PAIRS}
    flat_from, flat_to = 90, 115
    closes["EURUSD"][flat_from:flat_to] = closes["EURUSD"][flat_from]
    feats = features.build_features(_prices({p: list(c) for p, c in closes.items()}))
    e = feats[feats["pair"] == "EURUSD"].reset_index(drop=True)
    # rows whose full 20-return window lies inside the flat stretch (returns 0) -> undefined corr
    dates = pd.bdate_range("2020-01-01", periods=n)
    fully_flat = dates[flat_from + 20 : flat_to]
    assert e.set_index("date").loc[fully_flat, "corr_20"].isna().all()
    assert e["corr_20"].notna().sum() > 0  # elsewhere it is defined


# --------------------------------------------------------------------------------------
# THE leakage test: truncation invariance
# --------------------------------------------------------------------------------------
def test_truncation_invariance(prices_sample: pd.DataFrame) -> None:
    """Features computed on the full series must equal features computed on the series minus its
    last 30 rows per pair, on every overlapping row. If any feature peeked forward, cutting the
    future would change the past."""
    full = features.build_features(prices_sample)
    cut = prices_sample[prices_sample.groupby("pair").cumcount(ascending=False) >= 30]
    part = features.build_features(cut)
    merged_keys = part[["date", "pair"]]
    full_overlap = full.merge(merged_keys, on=["date", "pair"], how="inner").reset_index(drop=True)
    pd.testing.assert_frame_equal(full_overlap, part.reset_index(drop=True), check_exact=True)
    assert len(part) == len(full) - 3 * 30


def test_truncation_invariance_shifting_start_does_not_matter_for_late_rows(
    prices_sample: pd.DataFrame,
) -> None:
    """Sanity: features depend on the past through fixed windows only, so starting the series later
    (by more than the longest window) leaves the late rows unchanged as well."""
    full = features.build_features(prices_sample)
    later = prices_sample[prices_sample.groupby("pair").cumcount() >= 40]
    part = features.build_features(later)
    common = part.merge(full, on=["date", "pair"], suffixes=("_p", "_f"))
    for col in ["ret_1d", "mom_20", "ret_5d_abs"]:  # pure fixed-window arithmetic: bit-exact
        np.testing.assert_array_equal(common[f"{col}_p"], common[f"{col}_f"])
    for col in ["vol_20", "vol_60", "vol_ratio", "rng_hl", "corr_20"]:
        # pandas rolling std/mean/corr use an online add/remove algorithm that carries ~1e-16 of
        # state from earlier rows; vol_ratio divides two such numbers and can differ by ~1e-12 on
        # a 20-year history. That is float drift, not look-ahead — a real leak would be O(1e-3).
        # The exact proof of causality is test_truncation_invariance above (check_exact=True).
        np.testing.assert_allclose(common[f"{col}_p"], common[f"{col}_f"], rtol=1e-9, atol=1e-12)


def test_truncating_one_pair_never_changes_rows_before_its_cutoff(
    prices_sample: pd.DataFrame,
) -> None:
    """Cut only EURUSD's last 10 rows: every row of every pair dated <= that cutoff must be identical.
    (Rows after the cutoff may change for the other pairs — their EURUSD leg of corr_20 legitimately
    loses contemporaneous input — but nothing before it can.)"""
    full = features.build_features(prices_sample)
    is_eur = prices_sample["pair"] == "EURUSD"
    cut = prices_sample[~(is_eur & (prices_sample.groupby("pair").cumcount(ascending=False) < 10))]
    cutoff = cut.loc[cut["pair"] == "EURUSD", "date"].max()
    part = features.build_features(cut)
    m = full.merge(part, on=["date", "pair"], suffixes=("_f", "_p"))
    before = m[m["date"] <= cutoff]
    for col in features.BASE_FEATURES:
        pd.testing.assert_series_equal(
            before[f"{col}_f"], before[f"{col}_p"], check_names=False, check_exact=True
        )
