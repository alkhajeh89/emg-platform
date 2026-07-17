"""emg_ontology — the Core Ontology model + conformance layer (Module 7 —
Knowledge Graph Platform, EPIC-05, FEAT-05-1). Added Sprint 9.

Library-first, the same contract-first pattern as `emg-policy-engine` and
`emg-audit-client`: this package defines the *governed ontology* — an abstract
`Entity` and the `Actor`/`Artifact`/`Event`/`Relationship` archetypes, the
Organizational and Risk & Safety domains, a pure storage-independent conformance
validator, and a deterministic versioned descriptor. Every entity carries a
classification, trust score, and provenance reference by construction.

Out of scope for Sprint 9 (deliberately): persistence, the Neo4j binding,
ingestion, traversal/query, trust-score calculation, lifecycle-state management,
and any live service — those are FEAT-05-2 through FEAT-05-5.
"""

from .audit import (
    AUDIT_MODULE,
    ENTITY_CREATED,
    ENTITY_SUPERSEDED,
    GRAPH_MUTATION_ACTIONS,
    RELATIONSHIP_CREATED,
    RELATIONSHIP_SUPERSEDED,
    mutation_audit_metadata,
)
from .conformance import (
    ConformanceError,
    ConformanceReport,
    OntologyConformanceError,
    assert_entity_conformant,
    assert_relationship_conformant,
    validate_entity,
    validate_relationship,
)
from .core import (
    Actor,
    Artifact,
    Cardinality,
    Direction,
    Entity,
    Event,
    LifecycleStatus,
    Mutability,
    ProvenanceReference,
    Relationship,
    classification_rank,
    dominates,
)
from .descriptor import build_descriptor, descriptor_hash, descriptor_json
from .identifiers import (
    ONTOLOGY_SCHEMA_VERSION,
    TRUST_SCORE_MAX,
    TRUST_SCORE_MIN,
    new_entity_id,
    new_relationship_id,
)
from .organizational import (
    BusinessUnit,
    Organization,
    Person,
    Process,
    Project,
    Role,
    System,
)
from .references import AuditEventRef, CustodyRecordRef, ProvenanceRecordRef
from .registry import ENTITY_DOMAINS, ENTITY_REGISTRY, is_known_entity_type
from .relationships import (
    RELATIONSHIP_CATALOG,
    RelationshipRule,
    is_known_relationship_type,
)
from .risk_safety import Control, Evidence, Incident, Policy, Regulation, Risk

__version__ = "0.1.0"

__all__ = [
    # core envelope + archetypes
    "Entity",
    "Actor",
    "Artifact",
    "Event",
    "Relationship",
    "ProvenanceReference",
    "LifecycleStatus",
    "Mutability",
    "Cardinality",
    "Direction",
    "classification_rank",
    "dominates",
    # identifiers / schema version / trust range
    "ONTOLOGY_SCHEMA_VERSION",
    "TRUST_SCORE_MIN",
    "TRUST_SCORE_MAX",
    "new_entity_id",
    "new_relationship_id",
    # organizational domain
    "Organization",
    "BusinessUnit",
    "Person",
    "Role",
    "System",
    "Project",
    "Process",
    # risk & safety domain
    "Risk",
    "Control",
    "Policy",
    "Regulation",
    "Incident",
    "Evidence",
    # module-6 reference types
    "AuditEventRef",
    "ProvenanceRecordRef",
    "CustodyRecordRef",
    # registry
    "ENTITY_REGISTRY",
    "ENTITY_DOMAINS",
    "is_known_entity_type",
    # relationship catalog
    "RELATIONSHIP_CATALOG",
    "RelationshipRule",
    "is_known_relationship_type",
    # conformance
    "validate_entity",
    "validate_relationship",
    "assert_entity_conformant",
    "assert_relationship_conformant",
    "ConformanceReport",
    "ConformanceError",
    "OntologyConformanceError",
    # descriptor
    "build_descriptor",
    "descriptor_json",
    "descriptor_hash",
    # audit contract (definition only)
    "AUDIT_MODULE",
    "GRAPH_MUTATION_ACTIONS",
    "ENTITY_CREATED",
    "ENTITY_SUPERSEDED",
    "RELATIONSHIP_CREATED",
    "RELATIONSHIP_SUPERSEDED",
    "mutation_audit_metadata",
    "__version__",
]
