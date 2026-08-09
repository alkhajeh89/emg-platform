"""emg_common_types — shared value types and enums used across EMG services.

Scaffolded in Sprint 1 (FEAT-01-2). Contains only cross-cutting, storage- and
domain-agnostic value types. Domain entity types (Person, Organization,
Investigation, etc.) belong to Module 7's ontology (EPIC-05) and are
explicitly NOT defined here per Sprint 1's "no Knowledge Graph" constraint.

``LanguageCode``, ``TextDirection``, and ``Locale`` were added per
``EMG_ADR-018_Bilingual_Enterprise_Architecture.md`` and
``PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md`` Section 1, as the shared
vehicle for ``source_language``/``translations``/``locale`` across the
ontology, ingestion, API, AI, and frontend layers.
"""

from .classification import Classification
from .classification_normalization import normalize_classification_clearance
from .identifiers import CorrelationId, new_correlation_id
from .language import LanguageCode, Locale, TextDirection
from .projector_identity import (
    ProjectorIdentity,
    parse_projector_identity_inventory,
    projector_client_allow_list,
    validate_projector_credential_bindings,
)

__version__ = "0.1.0"

__all__ = [
    "Classification",
    "CorrelationId",
    "LanguageCode",
    "Locale",
    "ProjectorIdentity",
    "TextDirection",
    "new_correlation_id",
    "normalize_classification_clearance",
    "parse_projector_identity_inventory",
    "projector_client_allow_list",
    "validate_projector_credential_bindings",
    "__version__",
]
