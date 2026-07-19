"""Revision repository layer (Phase 2, Sprint 3).

The authoritative revision log + head pointer, with optimistic concurrency
(compare-and-set). Independent of GraphStore, projection, and outbox logic.
"""

from __future__ import annotations

from .in_memory import InMemoryRevisionRepository
from .model import Revision, RevisionHead
from .repository import RevisionRepository

__all__ = [
    "InMemoryRevisionRepository",
    "Revision",
    "RevisionHead",
    "RevisionRepository",
]
