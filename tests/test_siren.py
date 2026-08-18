"""Siren tests (phase 08): architecture, calm-train-only fitting, causal scoring, percentiles, neighbours."""

import numpy as np
import pandas as pd
import pytest

from fxradar import config, siren


def _toy_df(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for pair in ["EURUSD", "GBPUSD"]:
        dates = pd.bdate_range("2015-01-01", periods=n)
        d = pd.DataFrame({"date": dates, "pair": pair})
        for f in siren.SIREN_FEATURES:
            d[f] = rng.normal(0, 1, n)
        d["regime"] = np.where(rng.uniform(size=n) < 0.7, "calm", "chop")
        d["regime_prob"] = rng.uniform(0.5, 1.0, n)
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


@pytest.fixture(scope="module")
def bundle_and_df():
    df = _toy_df()
    return siren.fit_siren(df, train_end="2016-03-31"), df


def test_architecture_is_8_3_8(bundle_and_df) -> None:
    b, _ = bundle_and_df
    assert siren.HIDDEN == (8, 3, 8)
    assert tuple(b["model"].hidden_layer_sizes) == (8, 3, 8)
    assert b["model"].coefs_[0].shape == (9, 8) and b["model"].coefs_[-1].shape == (8, 9)


def test_scaler_fit_only_on_calm_train_days(bundle_and_df) -> None:
    b, df = bundle_and_df
    mask = siren.calm_train_mask(df, "2016-03-31")
    fit_rows = df[mask]
    assert (fit_rows["date"] <= pd.Timestamp("2016-03-31")).all()
    assert (fit_rows["regime"] == "calm").all() and (
        fit_rows["regime_prob"] > siren.CALM_PROB
    ).all()
    assert (b["train_dates"][0], b["train_dates"][1]) == (
        str(fit_rows["date"].min().date()),
        str(fit_rows["date"].max().date()),
    )
    np.testing.assert_allclose(
        b["scaler"].mean_, fit_rows[siren.SIREN_FEATURES].mean().to_numpy(), atol=1e-12
    )
    assert b["n_train"] == len(fit_rows) and len(b["train_scores"]) == len(fit_rows)


def test_scoring_is_truncation_invariant(bundle_and_df) -> None:
    b, df = bundle_and_df
    full_c, full_d = siren.score(b, df)
    cut = df[df.groupby("pair").cumcount(ascending=False) >= 30]
    part_c, part_d = siren.score(b, cut)
    ov = full_c.merge(part_c[["date", "pair"]], on=["date", "pair"])
    pd.testing.assert_frame_equal(
        ov.reset_index(drop=True), part_c.reset_index(drop=True), check_exact=True
    )
    ovd = full_d.merge(part_d[["date", "pair"]], on=["date", "pair"])
    pd.testing.assert_frame_equal(ovd.reset_index(drop=True), part_d.reset_index(drop=True))


def test_percentiles_and_outlier(bundle_and_df) -> None:
    b, df = bundle_and_df
    weird = df.copy()
    idx = weird.index[-1]
    weird.loc[idx, siren.SIREN_FEATURES] = 8.0  # eight-sigma day
    c, _ = siren.score(b, weird)
    assert c["anomaly_pct"].between(0, 100).all()
    assert (
        c.loc[idx, "anomaly_pct"] == 100.0
        and c.loc[idx, "anomaly_score"] > c["anomaly_score"].median() * 5
    )
    ref = np.array([1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(siren.percentile_of(np.array([0.5, 2.0, 9.0]), ref), [0, 50, 100])


def test_nearest_neighbour_excludes_own_window(bundle_and_df) -> None:
    b, df = bundle_and_df
    _, d = siren.score(b, df)
    gap = (d["date"] - d["nn_date"]).abs().dt.days
    assert (gap > siren.NN_EXCLUDE_DAYS).all()
    assert (
        d["nn_date"] <= pd.Timestamp("2016-03-31")
    ).all()  # neighbours come from the train period only


_have = siren.model_path().exists() and config.REGIMES_PATH.exists()


@pytest.mark.skipif(not _have, reason="siren artifacts not built")
def test_saved_siren_lights_up_snb_and_contract() -> None:
    r = pd.read_parquet(config.REGIMES_PATH)
    assert {"anomaly_score", "anomaly_pct"} <= set(r.columns)
    u = r[r["pair"] == "USDCHF"].set_index("date")
    assert u.loc["2015-01-14":"2015-01-19", "anomaly_pct"].max() >= 98
    assert u["anomaly_score"].idxmax() >= pd.Timestamp(
        "2015-01-14"
    )  # the SNB shock is USDCHF's loudest episode
