"""App smoke tests (phase 05): pages render from artifacts only, carry the disclaimer, load fast."""

import time

import pytest

from fxradar import config

pytestmark = pytest.mark.skipif(
    not (config.REGIMES_PATH.exists() and config.PRICES_PATH.exists()), reason="artifacts not built"
)


def _run(path: str):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(config.ROOT / path), default_timeout=60).run()


def test_dashboard_renders_with_disclaimer_in_sidebar_and_footer() -> None:
    t0 = time.time()
    at = _run("app/app.py")
    elapsed = time.time() - t0
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    assert any(config.DISCLAIMER in m.value for m in at.markdown)  # footer
    assert [s.value for s in at.sidebar.selectbox] == ["EURUSD"]
    assert len(at.get("plotly_chart")) == 1
    assert elapsed < 8.0  # cold import + first paint in CI; ~1s locally


def test_methodology_page_renders_with_disclaimer() -> None:
    at = _run("app/pages/1_Methodology.py")
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    assert any(config.DISCLAIMER in m.value for m in at.markdown)


def test_strategy_lab_page_renders_with_banner_and_disclaimer() -> None:
    from fxradar.strategies import METRICS_PATH, STRATEGY_PATH

    if not (STRATEGY_PATH.exists() and METRICS_PATH.exists()):
        pytest.skip("strategy artifacts not built")
    at = _run("app/pages/2_Strategy_lab.py")
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    assert any("not a live trading system" in m.value for m in at.markdown)
    assert len(at.get("plotly_chart")) == 2


def test_arcade_page_lock_before_reveal_cycle(tmp_path, monkeypatch) -> None:
    from fxradar import arcade

    monkeypatch.setattr(arcade, "DB_PATH", tmp_path / "arcade.db")
    at = _run("app/pages/3_Arcade.py")
    assert not at.exception, at.exception
    assert any("calibration game" in m.value for m in at.markdown)
    at.text_input[0].set_value("tester").run()
    assert not at.exception, at.exception
    pre = " ".join(m.value for m in at.markdown)
    assert (
        "model (revealed after lock)" not in pre
    )  # anti-anchoring: nothing model-side before the lock
    at.slider[0].set_value(40).run()
    at.button[0].click().run()
    assert not at.exception, at.exception
    post = " ".join(m.value for m in at.markdown)
    assert "model (revealed after lock)" in post and "40%" in post


def test_orb_html_render_smoke() -> None:
    import sys

    sys.path.insert(0, str(config.ROOT / "app"))
    import orb

    for regime in ["calm", "trend", "chop", "crisis"]:
        h = orb.orb_html(regime, 0.4, 99.0, size=120, pair="EURUSD")
        assert orb.REGIME_COLORS[regime] in h and "three.min.js" in h and '"pulse": true' in h
        assert (
            h.count("orb-wrap") >= 1 and "prefers-reduced-motion" in h and "visibilitychange" in h
        )
    assert set(orb.PRESETS) == {"calm", "trend", "chop", "crisis"} and orb.PARTICLES <= 1000
    assert '"pulse": false' in orb.orb_html("calm", 0.0, 50.0)
    assert '"regime": "calm"' in orb.orb_html(
        "unknown", 0.0, 0.0
    )  # unknown -> calm preset, never crashes
