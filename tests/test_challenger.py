"""Phase 23 challenger tests: extended matrix, reuse of the champion's label/split/threshold rules,
training + scoring on a toy, the daily stage contract (change_risk_5d_ch, top_drivers_ch,
challenger_scores for the ledger). No network; no training on real data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from tests.test_features_ext import _synthetic_context

from fxradar import calendar_ext, challenger, features, features_ext, forecaster
from fxradar import hmm_model as hm


@pytest.fixture(scope="module")
def toy(prices_sample):
    """features + regimes (2 pairs, tiny HMM) + features_ext from synthetic context."""
    px = prices_sample[prices_sample["pair"] != "USDCHF"]
    feats = features.build_features(px)
    parts = []
    for _pair, g in feats.groupby("pair"):
        b = hm.fit_hmm(g.reset_index(drop=True), train_end="2015-12-31", random_state=42)
        parts.append(hm.score_pair(b, g.reset_index(drop=True)))
    scored = pd.concat(parts, ignore_index=True)
    feats = feats.merge(scored[["date", "pair", *hm.POST_HMM_FEATURES]], on=["date", "pair"])
    regs = scored[hm.REGIME_COLUMNS]
    ext, _ = features_ext.build_features_ext(
        px, _synthetic_context(), calendar_ext.load_events(), None, "2015-06-30"
    )
    ext = features_ext.align_to_features(ext, feats)
    return feats, regs, ext


def test_feature_list_is_champion_plus_ext() -> None:
    assert challenger.FEATURES[: len(forecaster.FEATURES)] == forecaster.FEATURES
    assert challenger.FEATURES[len(forecaster.FEATURES) :] == features_ext.EXT_FEATURES
    assert len(set(challenger.FEATURES)) == len(challenger.FEATURES)
    assert "vol_20_yz" in challenger.FEATURES and "days_to_FOMC" in challenger.FEATURES


def test_matrix_keeps_champion_rows_and_adds_ext(toy) -> None:
    feats, regs, ext = toy
    champ = forecaster.build_matrix(feats, regs)
    m = challenger.build_matrix(feats, regs, ext)
    assert len(m) == len(champ)
    assert list(m.columns) == ["date", "pair", "regime", *challenger.FEATURES]
    pd.testing.assert_frame_equal(m[forecaster.FEATURES], champ[forecaster.FEATURES])
    # a row missing from features_ext stays NaN — never filled
    m2 = challenger.build_matrix(feats, regs, ext.iloc[:-10])
    assert m2[features_ext.EXT_FEATURES].isna().any(axis=1).sum() >= 10


def test_matrix_is_truncation_invariant(toy) -> None:
    feats, regs, ext = toy
    full = challenger.build_matrix(feats, regs, ext)
    cut = lambda df: df[df.groupby("pair").cumcount(ascending=False) >= 20]  # noqa: E731
    part = challenger.build_matrix(cut(feats), cut(regs), cut(ext))
    ov = full.merge(part[["date", "pair"]], on=["date", "pair"])
    pd.testing.assert_frame_equal(
        ov.reset_index(drop=True), part.reset_index(drop=True), check_exact=True
    )


def test_assemble_reuses_champion_labels_and_splits(toy) -> None:
    feats, regs, ext = toy
    df = challenger.assemble(feats, regs, ext)
    champ = forecaster.assemble(feats, regs)
    pd.testing.assert_series_equal(df["y"], champ["y"])
    pd.testing.assert_series_equal(df["split"], champ["split"])


@pytest.fixture(scope="module")
def trained(toy, tmp_path_factory):
    """Train on a shifted-date toy (so train/val/test all exist), save to a temp models dir."""
    feats, regs, ext = toy
    shift = pd.Timedelta(days=548)  # 2015 fixture -> straddles the 2016-12-31 train/val boundary
    feats, regs, ext = (d.assign(date=d["date"] + shift) for d in (feats, regs, ext))
    df = challenger.assemble(feats, regs, ext)
    model, info = challenger.fit_challenger(df)
    x_va, y_va = challenger._xy(df, "val", challenger.FEATURES)
    a, b = forecaster.fit_calibrator(model.predict_proba(x_va)[:, 1], y_va.to_numpy())
    meta = {
        "version": challenger.CHALLENGER_VERSION,
        "calibration": {"a": a, "b": b},
        "features": challenger.FEATURES,
    }
    models_dir = tmp_path_factory.mktemp("models")
    challenger.save_model(model, meta, models_dir)
    return models_dir, feats, regs, ext, info


def test_train_score_contract(trained) -> None:
    models_dir, feats, regs, ext, info = trained
    assert info["n_train"] > 0 and info["n_val"] > 0 and info["best_iteration"] >= 0
    model, meta = challenger.load_model(models_dir)
    out = challenger.score(model, challenger.build_matrix(feats, regs, ext), meta)
    assert list(out.columns) == ["date", "pair", "change_risk_5d", "top_drivers"]
    assert out["change_risk_5d"].between(0, 1).all()
    assert out["top_drivers"].map(len).eq(3).all()
    assert out["top_drivers"].map(lambda d: set(d) <= set(challenger.FEATURES)).all()


def test_stage_contract(trained) -> None:
    models_dir, feats, regs, ext, _ = trained
    ctx = {"features": feats, "regimes": regs.copy(), "features_ext": ext, "model_versions": {}}
    challenger.stage(ctx, models_dir=models_dir)
    r = ctx["regimes"]
    assert {"change_risk_5d_ch", "top_drivers_ch"} <= set(r.columns)
    assert len(r) == len(regs)  # merge on (date, pair) never duplicates rows
    assert ctx["model_versions"]["challenger"] == "1.0.0"
    s = ctx["challenger_scores"]
    assert list(s.columns) == ["date", "pair", "change_risk_5d", "model_version"]
    assert (s["model_version"] == "challenger=1.0.0").all()
    assert s["change_risk_5d"].between(0, 1).all()
    assert "regime" not in s.columns  # scores only; the orchestrator joins the rest


def test_stage_falls_back_to_disk_when_ctx_has_no_ext(trained, monkeypatch, tmp_path) -> None:
    models_dir, feats, regs, ext, _ = trained
    p = tmp_path / "features_ext.parquet"
    ext.to_parquet(p, index=False)
    monkeypatch.setattr(features_ext, "FEATURES_EXT_PATH", p)
    ctx = {"features": feats, "regimes": regs.copy()}
    challenger.stage(ctx, models_dir=models_dir)
    assert ctx["regimes"]["change_risk_5d_ch"].notna().any()


def test_promotion_criteria_is_explicit() -> None:
    t = challenger.PROMOTION_CRITERIA.lower()
    assert "pr-auc" in t and "brier" in t and "60" in t and "never automatic" in t


_have = challenger.model_path().exists()


@pytest.mark.skipif(not _have, reason="challenger model not trained")
def test_saved_challenger_meta_is_frozen_and_honest() -> None:
    _, meta = challenger.load_model()
    assert meta["features"] == challenger.FEATURES and "calibration" in meta
    assert meta["promotion_criteria"] == challenger.PROMOTION_CRITERIA
    board = pd.DataFrame(meta["scoreboard"])
    assert set(board["split"]) == {"val", "test"}
    assert "accuracy" not in " ".join(board.columns).lower()
    assert {"pr_auc", "brier", "precision", "recall"} <= set(board.columns)
    assert board["model"].str.startswith("champion").any()
    assert np.isfinite(board["pr_auc"]).all()
