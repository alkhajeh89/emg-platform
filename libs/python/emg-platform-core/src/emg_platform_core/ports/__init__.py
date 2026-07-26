"""Storage ports — the storage-independence seam (Freeze §11, §32)."""

from __future__ import annotations

from .graph_revision_reader import (
    DEFAULT_REVISION_LIST_LIMIT,
    MAX_REVISION_LIST_LIMIT,
    GraphRevisionReader,
)
from .graph_store import GraphStore, GraphTransaction, WriteReceipt
from .revision_metadata import HistoricalGraphRevision, RevisionMetadata

__all__ = [
    "DEFAULT_REVISION_LIST_LIMIT",
    "MAX_REVISION_LIST_LIMIT",
    "GraphRevisionReader",
    "GraphStore",
    "GraphTransaction",
    "HistoricalGraphRevision",
    "RevisionMetadata",
    "WriteReceipt",
]
