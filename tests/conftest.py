"""Shared pytest fixtures. Tests never touch the network: everything reads small saved fixtures."""

import socket
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------- the socket blocker -----------
# "Tests never touch the network" was a comment, not a mechanism (audit ENG-04). This makes it a
# mechanism: any non-loopback TCP/UDP connect inside pytest fails loudly. Loopback stays open so
# in-process servers used by fixtures keep working; stdlib only, no new dependency.
_REAL_CONNECT = socket.socket.connect
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _guarded_connect(self, address):  # noqa: ANN001 - socket internals
    host = address[0] if isinstance(address, tuple) and address else address
    if self.family in (socket.AF_INET, socket.AF_INET6) and host not in _LOOPBACK:
        raise RuntimeError(
            f"network call blocked inside pytest: connect({host!r}) — tests read committed "
            "fixtures only; if a test legitimately needs a local server, bind it to 127.0.0.1"
        )
    return _REAL_CONNECT(self, address)


@pytest.fixture(autouse=True, scope="session")
def _no_network():
    socket.socket.connect = _guarded_connect
    yield
    socket.socket.connect = _REAL_CONNECT


@pytest.fixture(scope="session")
def prices_sample() -> pd.DataFrame:
    """~15 months of real daily prices for the three pairs (Oct 2014 – Dec 2015, incl. SNB day)."""
    return pd.read_parquet(FIXTURES / "prices_sample.parquet")
