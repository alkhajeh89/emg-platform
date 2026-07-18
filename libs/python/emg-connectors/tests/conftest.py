"""Fixtures for emg-connectors (FEAT-13-1).

Puts the tests directory on `sys.path` so the shared `_helpers` module is
importable under `--import-mode=importlib`, then exposes the doubles as fixtures.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from _helpers import T0, FakePlugin, make_descriptor  # noqa: E402
from emg_connectors import ConnectorContext, ConnectorDescriptor  # noqa: E402


@pytest.fixture
def t0() -> datetime:
    return T0


@pytest.fixture
def descriptor() -> ConnectorDescriptor:
    return make_descriptor()


@pytest.fixture
def plugin() -> FakePlugin:
    return FakePlugin()


@pytest.fixture
def context(t0: datetime) -> ConnectorContext:
    return ConnectorContext(correlation_id="corr-1", as_of=t0)
