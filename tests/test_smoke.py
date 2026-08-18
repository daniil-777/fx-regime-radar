"""Smoke test: every fxradar module imports and the package version is what we ship."""

import importlib

import fxradar

MODULES = [
    "fxradar.config",
    "fxradar.data",
    "fxradar.features",
    "fxradar.hmm_model",
    "fxradar.forecaster",
    "fxradar.siren",
    "fxradar.narrate",
]


def test_version() -> None:
    assert fxradar.__version__ == "2.8.0"


def test_all_modules_import() -> None:
    for name in MODULES:
        module = importlib.import_module(name)
        assert module.__doc__, f"{name} needs a docstring stating its purpose"
