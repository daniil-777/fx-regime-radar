"""Shared pytest fixtures. Tests never touch the network: everything reads small saved fixtures."""

from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def prices_sample() -> pd.DataFrame:
    """~15 months of real daily prices for the three pairs (Oct 2014 – Dec 2015, incl. SNB day)."""
    return pd.read_parquet(FIXTURES / "prices_sample.parquet")
