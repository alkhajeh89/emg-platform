"""emg-platform-core — EMG Platform Foundation (Phase 1).

The storage-independence seam for the Enterprise Memory Graph: the
``GraphStore``/``GraphTransaction`` ports, a deterministic in-memory adapter, and
the cross-cutting ``TenantId``/``PrincipalRef`` identity value types. Pure and
deterministic — no I/O and no ML in the core (Freeze §9). Conforms to
EMG_PRODUCT_ARCHITECTURE_FREEZE.md §9, §11, §12, §32.
"""

from __future__ import annotations

from .adapters import InMemoryGraphStore
from .errors import PlatformCoreError, TransactionStateError
from .identity import (
    SYSTEM_PRINCIPAL,
    SYSTEM_TENANT,
    PrincipalKind,
    PrincipalRef,
    TenantId,
)
from .ports import GraphStore, GraphTransaction, WriteReceipt

__version__ = "0.1.0"

__all__ = [
    "SYSTEM_PRINCIPAL",
    "SYSTEM_TENANT",
    "GraphStore",
    "GraphTransaction",
    "InMemoryGraphStore",
    "PlatformCoreError",
    "PrincipalKind",
    "PrincipalRef",
    "TenantId",
    "TransactionStateError",
    "WriteReceipt",
    "__version__",
]
