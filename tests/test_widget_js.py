"""The widget is a single hand-written HTML file with no build step, so nothing catches a JavaScript
syntax error before a user meets a dead page. This test is that gate.

A real incident (2026-08-20): an edit inserted a statement into `async function startLevelMeter`,
producing `async const SILENCE_MS = ...`. The file still served with HTTP 200 and looked correct in
a screenshot — every script-defined function was simply undefined, so the whole presenter was inert.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    ROOT / "rust/fxradar-serve/static/avatar.html",
    ROOT / "rust/fxradar-serve/static/widget.html",
]
SCRIPTS = [ROOT / "rust/fxradar-serve/static/widget.js"]
MODULES = [ROOT / "rust/fxradar-serve/static/cards.js"]  # ES modules: checked with a .mjs copy


def _inline_js(html_path: Path) -> str:
    html = html_path.read_text()
    return "\n".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S))


@pytest.mark.parametrize("path", [p for p in PAGES if p.exists()], ids=lambda p: p.name)
def test_inline_widget_js_parses(path: Path, tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed; syntax gate runs where node exists (CI, dev machines)")
    js = _inline_js(path)
    if not js.strip():
        pytest.skip(f"{path.name} has no inline script")
    target = tmp_path / f"{path.stem}.js"
    target.write_text(js)
    proc = subprocess.run([node, "--check", str(target)], capture_output=True, text=True)
    assert proc.returncode == 0, f"{path.name} inline JavaScript does not parse:\n{proc.stderr}"


@pytest.mark.parametrize("path", [p for p in SCRIPTS if p.exists()], ids=lambda p: p.name)
def test_standalone_widget_js_parses(path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed; syntax gate runs where node exists (CI, dev machines)")
    proc = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, f"{path.name} does not parse:\n{proc.stderr}"


def test_avatar_widget_defines_its_voice_contract() -> None:
    """Guard the names the voice path depends on: a rename that misses one is a silent regression."""
    js = _inline_js(ROOT / "rust/fxradar-serve/static/avatar.html")
    for symbol in (
        "function flushTurn(",
        "function noteSpeech(",
        "function pickAlternative(",
        "function applyFixups(",
        "function voiceLang(",
        "function interruptSpeech(",
        "maxAlternatives",
    ):
        assert symbol in js, f"the widget lost {symbol!r} — voice conversation depends on it"


@pytest.mark.parametrize("path", [p for p in MODULES if p.exists()], ids=lambda p: p.name)
def test_es_modules_parse(path: Path, tmp_path: Path) -> None:
    """cards.js is an ES module; `node --check` needs the .mjs extension to parse `export`."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    target = tmp_path / f"{path.stem}.mjs"
    target.write_text(path.read_text())
    proc = subprocess.run([node, "--check", str(target)], capture_output=True, text=True)
    assert proc.returncode == 0, f"{path.name} does not parse:\n{proc.stderr}"
