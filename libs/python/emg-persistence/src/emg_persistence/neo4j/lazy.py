"""Lazy Neo4j projection holder — no driver connection at factory time."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import PersistenceSettings
    from .projection import Neo4jGraphProjection


class LazyNeo4jProjection:
    """Construct the Neo4j driver and projection on first use only."""

    def __init__(self, settings: PersistenceSettings) -> None:
        self._settings = settings
        self._driver: Any = None
        self._projection: Neo4jGraphProjection | None = None
        self._lock = Lock()
        self._closed = False

    @property
    def configured(self) -> bool:
        return self._settings.neo4j_uri is not None

    def get(self) -> Neo4jGraphProjection | None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Neo4j projection is closed")
            if not self.configured:
                return None
            if self._projection is None:
                from .driver import create_driver
                from .projection import Neo4jGraphProjection

                self._driver = create_driver(self._settings)
                self._projection = Neo4jGraphProjection(self._driver)
            return self._projection

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            driver = self._driver
            self._driver = None
            self._projection = None
        if driver is not None:
            driver.close()
