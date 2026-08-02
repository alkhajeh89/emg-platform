"""Lazy Neo4j projection ownership and lifecycle."""

from __future__ import annotations

from typing import Any

import pytest
from emg_persistence import PersistenceSettings
from emg_persistence.neo4j.lazy import LazyNeo4jProjection


class _Driver:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_lazy_projection_constructs_once_and_closes_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _Driver()
    create_calls: list[PersistenceSettings] = []

    def create_driver(settings: PersistenceSettings) -> Any:
        create_calls.append(settings)
        return driver

    monkeypatch.setattr("emg_persistence.neo4j.driver.create_driver", create_driver)
    settings = PersistenceSettings(neo4j_uri="neo4j://host")
    lazy = LazyNeo4jProjection(settings)

    assert create_calls == []
    assert lazy.get() is lazy.get()
    assert create_calls == [settings]

    lazy.close()
    lazy.close()

    assert driver.close_calls == 1
    with pytest.raises(RuntimeError, match="projection is closed"):
        lazy.get()
