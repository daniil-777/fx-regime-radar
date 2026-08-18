"""Bundle export tests (phase 11): manifest hashes, ONNX parity, round trip through the goldens."""

import json

import numpy as np
import onnxruntime as ort
import pandas as pd
import pytest

from fxradar import export, forecaster, siren
from fxradar import hmm_model as hm

BUNDLE = export.bundle_dir()
pytestmark = pytest.mark.skipif(not (BUNDLE / "manifest.json").exists(), reason="bundle not built")


def test_manifest_hashes_verify() -> None:
    ok = export.verify_manifest(BUNDLE)
    assert ok and all(ok.values()), ok
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    assert set(manifest["files"]) == {
        "feature_spec.yaml", "forecaster.json", "forecaster.onnx", "goldens.parquet",
        "hmm_EURUSD.json", "hmm_GBPUSD.json", "hmm_USDCHF.json", "siren.json", "siren.onnx",
    }  # fmt: skip
    assert manifest["parity"]["forecaster_onnx_max_abs_diff"] <= 1e-6
    assert manifest["parity"]["siren_onnx_max_abs_diff"] <= 1e-6
    assert not any(
        p.suffix in {".pkl", ".joblib", ".pickle"} for p in BUNDLE.iterdir()
    )  # nothing pickled crosses


def test_tampering_is_detected(tmp_path) -> None:
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copy)
    (copy / "forecaster.json").write_text((copy / "forecaster.json").read_text() + " ")
    ok = export.verify_manifest(copy)
    assert ok["forecaster.json"] is False and ok["siren.json"] is True


def test_hmm_json_matches_saved_model() -> None:
    for pair in ["EURUSD"]:
        h = json.loads((BUNDLE / f"hmm_{pair}.json").read_text())
        b = hm.load_bundle(pair)
        np.testing.assert_allclose(np.array(h["transmat"]), b.model.transmat_)
        for k in range(4):
            cov = np.array(h["covariances"][k])
            np.testing.assert_allclose(np.array(h["precisions"][k]) @ cov, np.eye(3), atol=1e-9)
            assert h["log_dets"][k] == pytest.approx(np.linalg.slogdet(cov)[1], rel=1e-10)
        assert h["state_names"] == [b.mapping[i] for i in range(4)]


def test_onnx_parity_on_fresh_rows() -> None:
    fc = json.loads((BUNDLE / "forecaster.json").read_text())
    model, _ = forecaster.load_model()
    rng = np.random.default_rng(0)
    goldens = pd.read_parquet(BUNDLE / "goldens.parquet")
    x = np.column_stack(
        [
            goldens[f"feat_{c}"] if f"feat_{c}" in goldens else rng.integers(0, 2, len(goldens))
            for c in fc["features"]
        ]
    ).astype(np.float32)
    sess = ort.InferenceSession(str(BUNDLE / "forecaster.onnx"), providers=["CPUExecutionProvider"])
    outs = sess.run(None, {"input": x})
    p_onnx = np.array([d[1] for d in outs[1]]) if isinstance(outs[1], list) else outs[1][:, 1]
    p_ref = model.predict_proba(pd.DataFrame(x, columns=fc["features"]))[:, 1]
    assert np.abs(p_onnx - p_ref).max() <= 1e-6

    si = json.loads((BUNDLE / "siren.json").read_text())
    b = siren.load_bundle()
    xs = rng.normal(size=(50, 9))
    s2 = ort.InferenceSession(str(BUNDLE / "siren.onnx"), providers=["CPUExecutionProvider"])
    r = s2.run(None, {si["onnx_input"]: xs})[0]
    assert r.shape == (50, 9) and np.abs(r - b["model"].predict(xs)).max() <= 1e-6


def test_goldens_round_trip_reproduces_python_outputs() -> None:
    table = export.replay_goldens(BUNDLE)
    assert table["ok"].all(), table[~table["ok"]].to_string()
    goldens = pd.read_parquet(BUNDLE / "goldens.parquet")
    assert len(goldens) >= 300
    snb = goldens[(goldens["pair"] == "USDCHF") & (goldens["date"] == pd.Timestamp("2015-01-15"))]
    assert len(snb) == 1 and len(snb.iloc[0]["USDCHF_close"]) == export.WINDOW
