"""emg-platform-core — EMG Platform Foundation (Phase 1).

The storage-independence seam for the Enterprise Memory Graph: the
``GraphStore``/``GraphTransaction`` ports, a deterministic in-memory adapter, and
the cross-cutting ``TenantId``/``PrincipalRef`` identity value types. Pure and
deterministic — no I/O and no ML in the core (Freeze §9). Conforms to
EMG_PRODUCT_ARCHITECTURE_FREEZE.md §9, §11, §12, §32.
"""

from __future__ import annotations

from .adapters import InMemoryGraphStore
from .errors import (
    PlatformCoreError,
    RevisionNotFoundError,
    SnapshotIntegrityError,
    TransactionStateError,
    UnsupportedHistoryCapabilityError,
)
from .identity import (
    SYSTEM_PRINCIPAL,
    SYSTEM_TENANT,
    PrincipalKind,
    PrincipalRef,
    TenantId,
)
from .ports import (
    DEFAULT_REVISION_LIST_LIMIT,
    MAX_REVISION_LIST_LIMIT,
    GraphRevisionReader,
    GraphStore,
    GraphTransaction,
    HistoricalGraphRevision,
    RevisionMetadata,
    WriteReceipt,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_REVISION_LIST_LIMIT",
    "MAX_REVISION_LIST_LIMIT",
    "SYSTEM_PRINCIPAL",
    "SYSTEM_TENANT",
    "GraphRevisionReader",
    "GraphStore",
    "GraphTransaction",
    "HistoricalGraphRevision",
    "InMemoryGraphStore",
    "PlatformCoreError",
    "PrincipalKind",
    "PrincipalRef",
    "RevisionMetadata",
    "RevisionNotFoundError",
    "SnapshotIntegrityError",
    "TenantId",
    "TransactionStateError",
    "UnsupportedHistoryCapabilityError",
    "WriteReceipt",
    "__version__",
]
