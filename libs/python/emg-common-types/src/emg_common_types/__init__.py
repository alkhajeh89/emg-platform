"""emg_common_types — shared value types and enums used across EMG services.

Scaffolded in Sprint 1 (FEAT-01-2). Contains only cross-cutting, storage- and
domain-agnostic value types. Domain entity types (Person, Organization,
Investigation, etc.) belong to Module 7's ontology (EPIC-05) and are
explicitly NOT defined here per Sprint 1's "no Knowledge Graph" constraint.
"""

from .classification import Classification
from .identifiers import CorrelationId, new_correlation_id

__version__ = "0.1.0"

__all__ = [
    "Classification",
    "CorrelationId",
    "new_correlation_id",
    "__version__",
]
