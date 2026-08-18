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
