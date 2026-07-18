"""Shared fixtures for the emg-memory-graph test suite (FEAT-05-6).

Under pytest's importlib mode, sibling test modules cannot ``import conftest``;
reusable constructors therefore live in ``_mg_helpers.py``, which we place on
``sys.path`` here so tests can ``from _mg_helpers import ...``.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402
from _mg_helpers import ASOF, T0, edge_input, node_input  # noqa: E402
from emg_memory_graph import MemoryGraph, MemoryGraphBuilder  # noqa: E402


@pytest.fixture
def t0() -> datetime:
    return T0


@pytest.fixture
def asof() -> datetime:
    return ASOF


@pytest.fixture
def lineage_graph() -> MemoryGraph:
    """A small decision-lineage graph:
    requirement -> meeting -> decision -> approval; decision approved_by Sara;
    policy -> risk -> project; Sara participated_in meeting."""
    b = MemoryGraphBuilder()
    nodes = (
        node_input("req", "requirement", "R1"),
        node_input("mtg", "meeting", "M1"),
        node_input("dec", "decision", "D1"),
        node_input("appr", "approval", "A1"),
        node_input("sara", "person", "Sara"),
        node_input("pol", "policy", "P1"),
        node_input("risk", "risk", "K1"),
        node_input("proj", "project", "Atlas"),
    )
    edges = (
        edge_input("precedes", "req", "mtg"),
        edge_input("precedes", "mtg", "dec"),
        edge_input("resulted_in", "dec", "appr"),
        edge_input("approved_by", "dec", "sara"),
        edge_input("discussed_in", "dec", "mtg"),
        edge_input("originates_from", "pol", "risk"),
        edge_input("affects", "risk", "proj"),
        edge_input("participated_in", "sara", "mtg"),
    )
    return b.build(nodes=nodes, edges=edges, as_of=ASOF).graph
