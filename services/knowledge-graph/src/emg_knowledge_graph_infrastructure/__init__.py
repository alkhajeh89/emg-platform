"""Knowledge Graph infrastructure adapters kept outside the application package."""

from .atomic_mutation import PostgresAtomicMutationExecution
from .factory import build_atomic_knowledge_graph_application
from .resource_metadata import GraphResourceMetadataReader
from .schema_registry import (
    CompatibilityNormalizerRegistration,
    RegistryBackedCompatibilityAdapterRegistry,
    RegistryBackedSchemaNegotiator,
    SchemaCatalog,
    SchemaCatalogEntry,
    SchemaCompatibility,
    SchemaLifecycleState,
    is_well_formed_schema_version,
    load_schema_catalog,
    validate_schema_boot_gate,
    validate_schema_catalog,
)

__all__ = [
    "PostgresAtomicMutationExecution",
    "GraphResourceMetadataReader",
    "build_atomic_knowledge_graph_application",
    "CompatibilityNormalizerRegistration",
    "RegistryBackedCompatibilityAdapterRegistry",
    "RegistryBackedSchemaNegotiator",
    "SchemaCatalog",
    "SchemaCatalogEntry",
    "SchemaCompatibility",
    "SchemaLifecycleState",
    "is_well_formed_schema_version",
    "load_schema_catalog",
    "validate_schema_boot_gate",
    "validate_schema_catalog",
]
