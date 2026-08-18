"""viz3d (display layer): simplex exactness + validation, order guard, train-only embedding fit
(leakage), determinism, and agreement of the replayed filtered probabilities with regimes.parquet.
"""

import numpy as np
import pandas as pd
import pytest

from fxradar import config, viz3d

HAVE_ARTIFACTS = (config.REGIMES_PATH.exists() and config.FEATURES_PATH.exists()) and any(
    config.MODELS_DIR.glob("hmm_*_v*.joblib")
)
needs_artifacts = pytest.mark.skipif(not HAVE_ARTIFACTS, reason="artifacts not built")


# ---- simplex_coords ---------------------------------------------------------------------
def test_simplex_vertex_rows_map_to_vertices_exactly() -> None:
    eye = np.eye(4)
    out = viz3d.simplex_coords(eye, viz3d.REGIME_ORDER)
    assert np.array_equal(out, viz3d.VERTICES)  # exact, bit-for-bit
    assert np.array_equal(viz3d.simplex_coords([[1, 0, 0, 0]]), viz3d.VERTICES[:1])


def test_uniform_row_maps_to_origin() -> None:
    out = viz3d.simplex_coords(np.full((1, 4), 0.25))
    assert np.all(np.abs(out) < 1e-12)


def test_random_valid_rows_equal_probs_at_V_bit_for_bit() -> None:
    rng = np.random.default_rng(0)
    p = rng.dirichlet(np.ones(4), size=200)
    assert np.array_equal(viz3d.simplex_coords(p), p @ viz3d.VERTICES)


@pytest.mark.parametrize(
    "bad",
    [
        [[0.5, 0.5, 0.5, 0.0]],  # sums to 1.5
        [[0.2, 0.2, 0.2, 0.2]],  # sums to 0.8
        [[1.2, -0.2, 0.0, 0.0]],  # negative entry (sums to 1)
        [[np.nan, 0.5, 0.5, 0.0]],  # not finite
    ],
)
def test_simplex_rejects_invalid_rows(bad) -> None:
    with pytest.raises(ValueError):
        viz3d.simplex_coords(bad)


def test_simplex_order_guard_rejects_disagreeing_mapping() -> None:
    with pytest.raises(ValueError):
        viz3d.simplex_coords(np.eye(4), ["crisis", "chop", "trend", "calm"])
    with pytest.raises(ValueError):
        viz3d.simplex_coords(np.eye(4), ["calm", "trend", "chop"])


# ---- landscape embedding: train-only fit, determinism ------------------------------------
def _synthetic_features(n: int = 400, start: str = "2015-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(1)
    dates = pd.bdate_range(start, periods=n)
    df = pd.DataFrame(
        rng.normal(size=(n, len(viz3d.LANDSCAPE_FEATURES))), columns=viz3d.LANDSCAPE_FEATURES
    )
    df.insert(0, "date", dates)
    df.insert(1, "pair", "SYN")
    return df


def test_embedding_fit_uses_train_rows_only_and_records_it() -> None:
    feats = _synthetic_features()
    train_end = "2015-12-31"
    emb = viz3d.fit_landscape_embedding(feats, train_end=train_end, pair="SYN")
    n_train = int((feats["date"] <= pd.Timestamp(train_end)).sum())
    assert emb.train_end == train_end
    assert emb.n_fit_rows == n_train and n_train < len(feats)  # no future dates in the fit
    # the fit is insensitive to anything after train_end: perturb the future, refit, same map
    feats2 = feats.copy()
    future = feats2["date"] > pd.Timestamp(train_end)
    feats2.loc[future, viz3d.LANDSCAPE_FEATURES] *= 100.0
    emb2 = viz3d.fit_landscape_embedding(feats2, train_end=train_end, pair="SYN")
    assert np.allclose(emb.transform(feats), emb2.transform(feats))


def test_embedding_is_deterministic_and_round_trips(tmp_path) -> None:
    feats = _synthetic_features()
    a = viz3d.fit_landscape_embedding(feats, train_end="2015-12-31", pair="SYN")
    b = viz3d.fit_landscape_embedding(feats, train_end="2015-12-31", pair="SYN")
    assert np.array_equal(a.transform(feats), b.transform(feats))
    viz3d.save_embedding(a, tmp_path)
    c = viz3d.load_embedding("SYN", tmp_path)
    assert c.train_end == a.train_end and c.n_fit_rows == a.n_fit_rows
    assert np.array_equal(c.transform(feats), a.transform(feats))


def test_embedding_rejects_unknown_method() -> None:
    with pytest.raises(ValueError):
        viz3d.fit_landscape_embedding(_synthetic_features(), train_end="2015-12-31", method="tsne")


# ---- on the real artifacts --------------------------------------------------------------
@needs_artifacts
def test_replayed_filtered_probabilities_match_regime_table_and_figures_build() -> None:
    features, regimes, bundles = viz3d.load_inputs()
    pair = config.PAIRS[0]
    fr = viz3d.probability_frame(pair, features, regimes, bundles[pair])
    p = fr[viz3d.PROB_COLUMNS].to_numpy()
    assert np.allclose(p.sum(axis=1), 1.0, atol=1e-9)
    # the winner and its probability agree with what the pipeline stored (same forward filter)
    assert (np.array(viz3d.REGIME_ORDER)[p.argmax(axis=1)] == fr["regime"].to_numpy()).all()
    assert np.allclose(p.max(axis=1), fr["regime_prob"].to_numpy(), atol=1e-9)
    fig = viz3d.tetrahedron_figure(fr, pair, "time")
    assert len(fig.data) == 6 + 4 + 1 + 1  # edges, vertices, path, today
    scene = fig.layout.scene
    assert (
        scene.aspectmode == "data" and scene.xaxis.visible is False and scene.zaxis.visible is False
    )
    fig_s = viz3d.tetrahedron_figure(fr, pair, "siren")
    assert fig_s.data[-2].marker.colorbar is not None
    with pytest.raises(ValueError):
        viz3d.tetrahedron_figure(fr, pair, "regime")


@needs_artifacts
def test_persisted_embedding_is_train_only_and_landscape_figure_is_deterministic() -> None:
    pair = config.PAIRS[0]
    path = viz3d.embedding_path(pair, config.MODELS_DIR)
    if not path.exists():
        pytest.skip("landscape embedding not fit (python -m fxradar.viz3d --fit)")
    features, regimes, _ = viz3d.load_inputs()
    emb = viz3d.load_embedding(pair, config.MODELS_DIR)
    f = features[features["pair"] == pair]
    train = f[f["date"] <= pd.Timestamp(config.TRAIN_END)]
    n_train = int(np.isfinite(train[emb.features].to_numpy(dtype=float)).all(axis=1).sum())
    assert emb.train_end == str(pd.Timestamp(config.TRAIN_END).date())
    assert emb.n_fit_rows == n_train  # exactly the train rows, nothing after TRAIN_END
    frame = viz3d.landscape_frame(pair, features, regimes)
    f1 = viz3d.landscape_figure(frame, emb, pair)
    f2 = viz3d.landscape_figure(frame, emb, pair)
    for t1, t2 in zip(f1.data, f2.data, strict=True):
        assert np.array_equal(np.asarray(t1.x), np.asarray(t2.x))
        assert np.array_equal(np.asarray(t1.z), np.asarray(t2.z))
    assert f1.data[-1].name == "today" and f1.data[-2].name.startswith("last ")
