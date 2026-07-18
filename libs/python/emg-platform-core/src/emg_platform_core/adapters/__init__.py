"""Concrete ``GraphStore`` adapters. Phase 1 ships the in-memory adapter only;
Neo4j/Postgres adapters (durability) arrive in Phase 2 (Freeze §32)."""

from __future__ import annotations

from .in_memory import InMemoryGraphStore

__all__ = ["InMemoryGraphStore"]
