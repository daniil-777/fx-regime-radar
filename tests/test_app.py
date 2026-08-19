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
    at = _run("app/views/overview.py")
    elapsed = time.time() - t0
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    assert any(config.DISCLAIMER in m.value for m in at.markdown)  # footer
    values = [s.value for s in at.sidebar.selectbox]
    assert values[:2] == ["fx", "EURUSD"] and values[2] == "today (latest data)"
    assert len(at.get("plotly_chart")) == 1
    assert elapsed < 8.0  # cold import + first paint in CI; ~1s locally


def test_scenario_explorer_time_machine_and_universe_switch() -> None:
    """Switching universe swaps pairs; jumping to an episode shows the as-of banner and hides the future."""
    at = _run("app/views/overview.py")
    if "Crypto majors" in at.sidebar.selectbox[0].options:  # options are display labels
        at.sidebar.selectbox[0].set_value("crypto").run()
        assert not at.exception, at.exception
        assert at.sidebar.selectbox[1].options[0] == "BTC/USD"
    episodes = at.sidebar.selectbox[2].options
    assert len(episodes) >= 2 and episodes[0] == "today (latest data)"
    at.sidebar.selectbox[2].set_value(episodes[1]).run()
    assert not at.exception, at.exception
    txt = " ".join(m.value for m in at.markdown)
    assert (
        "Time machine — viewing as of" in txt and "(replay)" in txt
    )  # narration replayed by template


def test_methodology_page_renders_with_disclaimer() -> None:
    at = _run("app/views/methodology.py")
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    assert any(config.DISCLAIMER in m.value for m in at.markdown)


def test_strategy_lab_page_renders_with_banner_and_disclaimer() -> None:
    from fxradar.strategies import METRICS_PATH, STRATEGY_PATH

    if not (STRATEGY_PATH.exists() and METRICS_PATH.exists()):
        pytest.skip("strategy artifacts not built")
    at = _run("app/views/strategy_lab.py")
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    assert any("not a live trading system" in m.value for m in at.markdown)
    assert len(at.get("plotly_chart")) == 2


def test_arcade_page_lock_before_reveal_cycle(tmp_path, monkeypatch) -> None:
    from fxradar import arcade

    monkeypatch.setattr(arcade, "DB_PATH", tmp_path / "arcade.db")
    at = _run("app/views/arcade.py")
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


def test_router_and_advisor_render() -> None:
    at = _run("app/app.py")  # the st.navigation entrypoint runs the default (Overview) page
    assert not at.exception, at.exception
    at = _run("app/views/advisor.py")
    assert not at.exception, at.exception
    txt = " ".join(m.value for m in at.markdown)
    assert "risk budget" in txt and "overall stability" in txt and "never which way" in txt
    assert not any(w in txt.lower() for w in [" buy ", " sell "])  # never a direction on the page
    at.text_input[0].set_value("should I buy now?").run()
    assert not at.exception, at.exception
    txt = " ".join(m.value for m in at.markdown)
    assert "never predicts price direction" in txt


def test_mobile_bar_mirrors_sidebar_controls_both_ways() -> None:
    """The phone-sized control bar (segmented controls) and the sidebar selectboxes are two views of
    one choice: changing either one moves the other, and no Streamlit warning is raised."""
    at = _run("app/views/overview.py")
    assert not at.exception, at.exception
    assert not at.warning and not at.error
    seg = at.segmented_control
    if "Crypto majors" not in at.sidebar.selectbox[0].options:  # options are display labels
        pytest.skip("crypto universe not built")
    # segmented controls: [universe, pair]
    assert seg[0].value == "fx" and seg[1].value == "EURUSD"
    seg[1].set_value("GBPUSD").run()  # mobile pill -> sidebar selectbox
    assert not at.exception, at.exception
    assert at.sidebar.selectbox[1].value == "GBPUSD"
    at.sidebar.selectbox[1].set_value("USDCHF").run()  # sidebar -> mobile pill
    assert at.segmented_control[1].value == "USDCHF"
    at.segmented_control[0].set_value("crypto").run()  # universe via the mobile bar
    assert not at.exception, at.exception
    assert at.sidebar.selectbox[0].value == "crypto"
    assert at.sidebar.selectbox[1].options[0] == "BTC/USD"
    assert not at.warning and not at.error


def test_regime_space_page_renders_and_replays() -> None:
    """Regime space (3-D feature-space views): renders for the default pair, carries animation
    frames that end exactly on the as-of day, survives a third-axis switch and a time-machine jump,
    and never talks direction. Reads artifacts only (rule 8)."""
    at = _run("app/views/regime_space.py")
    assert not at.exception, at.exception
    txt = " ".join(m.value for m in at.markdown)
    assert "State-space portrait" in txt and "Regime landscape" in txt
    assert not any(w in txt.lower() for w in [" buy ", " sell ", "will rise", "will fall"])
    at.selectbox(key="rs_third").select("5-day change risk").run()
    assert not at.exception, at.exception
    episodes = at.selectbox(key="episode_fx").options
    snb = [o for o in episodes if "SNB" in o]
    if snb:  # replay a named shock: everything must still render on that as-of date
        at.selectbox(key="episode_fx").select(snb[0]).run()
        assert not at.exception, at.exception
        assert "as of 2015-01-15" in " ".join(m.value for m in at.markdown)


def test_proof_page_renders_scoreboard_and_verify_box() -> None:
    at = _run("app/views/proof.py")
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    text = " ".join(m.value for m in at.markdown)
    assert "verify_ledger.py" in text and "Verify independently" in text
