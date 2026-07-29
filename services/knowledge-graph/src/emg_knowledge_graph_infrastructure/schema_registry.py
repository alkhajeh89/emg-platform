"""Service-local ADR-033 schema catalog and negotiation infrastructure."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any

from emg_knowledge_graph import (
    SchemaNegotiationError,
    SchemaNegotiationRequest,
    SchemaNegotiationResult,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

_MAX_VERSION_LENGTH = 128
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_AUTHORITY_FIELD_PARTS = frozenset({"classification", "owner", "tenant", "principal"})


class SchemaLifecycleState(str, Enum):
    """The three ADR-033 states admitted to the runtime catalog."""

    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class SchemaCompatibility(str, Enum):
    """Absolute compatibility of one version against the canonical schema."""

    STRICT = "strict"
    BACKWARD = "backward"
    NORMALIZATION_REQUIRED = "normalization_required"
    MIGRATION_REQUIRED = "migration_required"
    INCOMPATIBLE = "incompatible"


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SchemaCatalogEntry(_CatalogModel):
    version: str
    state: SchemaLifecycleState
    compatibility: SchemaCompatibility
    normalization_required: bool = False
    normalizer_ids: tuple[str, ...] = ()
    deprecated_at: AwareDatetime | None = None
    retirement_at: AwareDatetime | None = None


class SchemaCatalog(_CatalogModel):
    generation: str
    canonical_version: str
    versions: tuple[SchemaCatalogEntry, ...]

    def entry(self, version: str) -> SchemaCatalogEntry | None:
        """Return one exact catalog entry without interpreting its identifier."""

        return next((entry for entry in self.versions if entry.version == version), None)


Normalizer = Callable[[object], object]


class CompatibilityNormalizerRegistration(_CatalogModel):
    normalizer_id: str
    source_version: str
    target_version: str
    written_fields: tuple[str, ...] = ()
    normalizer: Normalizer


def is_well_formed_schema_version(value: str) -> bool:
    """Validate only syntax; compatibility remains exclusively catalog-owned."""

    return (
        isinstance(value, str)
        and 0 < len(value) <= _MAX_VERSION_LENGTH
        and _SEMVER.fullmatch(value) is not None
    )


def validate_schema_catalog(catalog: SchemaCatalog) -> None:
    """Reject a catalog that cannot produce deterministic ADR-033 outcomes."""

    if not catalog.generation.strip():
        raise ValueError("schema catalog generation must be non-blank")
    if not catalog.versions:
        raise ValueError("schema catalog must contain at least one version")
    if not is_well_formed_schema_version(catalog.canonical_version):
        raise ValueError("canonical schema version must be fully qualified SemVer")

    identifiers = tuple(entry.version for entry in catalog.versions)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("schema catalog version identifiers must be unique")
    for entry in catalog.versions:
        _validate_entry(entry)

    canonical = catalog.entry(catalog.canonical_version)
    if canonical is None:
        raise ValueError("canonical schema version is absent from the catalog")
    if (
        canonical.state is not SchemaLifecycleState.PUBLISHED
        or canonical.compatibility is not SchemaCompatibility.STRICT
        or canonical.normalization_required
        or canonical.normalizer_ids
    ):
        raise ValueError("canonical schema version must be published, strict, and unnormalized")


def _validate_entry(entry: SchemaCatalogEntry) -> None:
    if not is_well_formed_schema_version(entry.version):
        raise ValueError(f"schema version {entry.version!r} must be fully qualified SemVer")
    if any(not identifier.strip() for identifier in entry.normalizer_ids):
        raise ValueError(f"schema version {entry.version!r} has a blank normalizer identifier")

    requires_normalization = entry.compatibility is SchemaCompatibility.NORMALIZATION_REQUIRED
    if entry.normalization_required != requires_normalization:
        raise ValueError(
            f"schema version {entry.version!r} has inconsistent normalization classification"
        )
    if not entry.normalization_required and entry.normalizer_ids:
        raise ValueError(
            f"schema version {entry.version!r} declares normalizers without requiring them"
        )
    if entry.state is SchemaLifecycleState.PUBLISHED:
        if entry.deprecated_at is not None or entry.retirement_at is not None:
            raise ValueError(
                f"published schema version {entry.version!r} cannot have lifecycle instants"
            )
    elif entry.state is SchemaLifecycleState.DEPRECATED:
        _require_lifecycle_instants(entry)
        assert entry.deprecated_at is not None
        assert entry.retirement_at is not None
        if entry.deprecated_at >= entry.retirement_at:
            raise ValueError(
                f"deprecated schema version {entry.version!r} must retire after deprecation"
            )
    else:
        _require_lifecycle_instants(entry)
        if entry.normalization_required or entry.normalizer_ids:
            raise ValueError(
                f"retired schema version {entry.version!r} cannot require normalization"
            )


def _require_lifecycle_instants(entry: SchemaCatalogEntry) -> None:
    if entry.deprecated_at is None or entry.retirement_at is None:
        raise ValueError(
            f"{entry.state.value} schema version {entry.version!r} "
            "requires deprecation and retirement instants"
        )


def load_schema_catalog(document: object) -> SchemaCatalog:
    """Load one format-neutral catalog document and validate it."""

    try:
        catalog = SchemaCatalog.model_validate(document)
    except ValidationError as exc:
        raise ValueError(f"invalid schema catalog: {exc}") from exc
    validate_schema_catalog(catalog)
    return catalog


class RegistryBackedSchemaNegotiator:
    """Perform constant-time, exact-version negotiation against one catalog."""

    def __init__(self, catalog: SchemaCatalog) -> None:
        validate_schema_catalog(catalog)
        self._entries = MappingProxyType({entry.version: entry for entry in catalog.versions})

    def negotiate(self, request: SchemaNegotiationRequest) -> SchemaNegotiationResult:
        requested = request.preferred_version
        if not is_well_formed_schema_version(requested):
            raise SchemaNegotiationError(
                f"schema version {requested!r} is not a fully qualified version identifier",
                failure_code="MALFORMED_SCHEMA",
            )
        entry = self._entries.get(requested)
        if entry is None:
            raise SchemaNegotiationError(
                f"schema version {requested!r} is not present in the catalog",
                failure_code="UNKNOWN_SCHEMA",
            )
        if entry.state is SchemaLifecycleState.RETIRED:
            raise SchemaNegotiationError(
                f"schema version {requested!r} is retired",
                failure_code="RETIRED_SCHEMA",
            )
        if entry.compatibility in {
            SchemaCompatibility.MIGRATION_REQUIRED,
            SchemaCompatibility.INCOMPATIBLE,
        }:
            raise SchemaNegotiationError(
                f"schema version {requested!r} is incompatible with canonical execution",
                failure_code="INCOMPATIBLE_SCHEMA",
            )
        return SchemaNegotiationResult(
            effective_version=requested,
            adapter_required=entry.normalization_required,
        )


class RegistryBackedCompatibilityAdapterRegistry:
    """Resolve one exact-pair normalizer from an immutable registration set."""

    def __init__(
        self,
        catalog: SchemaCatalog,
        registrations: tuple[CompatibilityNormalizerRegistration, ...],
    ) -> None:
        validate_schema_catalog(catalog)
        self.catalog = catalog
        self.registrations = registrations
        registrations_by_pair: dict[
            tuple[str, str], tuple[CompatibilityNormalizerRegistration, ...]
        ] = {}
        for registration in registrations:
            pair = (registration.source_version, registration.target_version)
            registrations_by_pair[pair] = (
                *registrations_by_pair.get(pair, ()),
                registration,
            )
        self._registrations_by_pair = MappingProxyType(registrations_by_pair)

    def registrations_for(
        self, source_version: str, target_version: str
    ) -> tuple[CompatibilityNormalizerRegistration, ...]:
        return self._registrations_by_pair.get((source_version, target_version), ())

    def normalize(
        self,
        request: Any,
        *,
        source_version: str,
        target_version: str,
    ) -> Any:
        entry = self.catalog.entry(source_version)
        if entry is None or not entry.normalization_required:
            return request
        matches = self.registrations_for(source_version, target_version)
        if len(matches) != 1:
            raise _adapter_failure(
                f"normalizer resolution for {source_version!r} to {target_version!r} is invalid"
            )
        try:
            normalized = matches[0].normalizer(request)
        except Exception as exc:
            raise _adapter_failure(f"normalizer {matches[0].normalizer_id!r} failed") from exc
        if type(normalized) is not type(request):
            raise _adapter_failure("normalizer changed the request DTO family")
        before = _model_document(request)
        after = _model_document(normalized)
        if set(before) != set(after):
            raise _adapter_failure("normalizer changed the request field domain")
        if _authority_values(before) != _authority_values(after):
            raise _adapter_failure("normalizer changed an authority-bearing value")
        return normalized


def validate_schema_boot_gate(
    catalog: SchemaCatalog,
    registry: RegistryBackedCompatibilityAdapterRegistry,
) -> None:
    """Prove catalog/normalizer consistency before a process can become ready."""

    validate_schema_catalog(catalog)
    for entry in catalog.versions:
        matches = registry.registrations_for(entry.version, catalog.canonical_version)
        if entry.normalization_required:
            if len(matches) != 1:
                raise ValueError(
                    f"schema version {entry.version!r} requires exactly one normalizer"
                )
            if entry.normalizer_ids != (matches[0].normalizer_id,):
                raise ValueError(
                    f"schema version {entry.version!r} normalizer declaration does not match"
                )
        elif matches:
            raise ValueError(
                f"schema version {entry.version!r} has an undeclared normalizer registration"
            )

    for registration in registry.registrations:
        source_entry = catalog.entry(registration.source_version)
        if (
            source_entry is None
            or registration.target_version != catalog.canonical_version
            or not source_entry.normalization_required
        ):
            raise ValueError(
                f"normalizer {registration.normalizer_id!r} is not declared by the catalog"
            )
        prohibited = tuple(
            field for field in registration.written_fields if _is_authority_field(field)
        )
        if prohibited:
            raise ValueError(
                f"normalizer {registration.normalizer_id!r} declares prohibited writes: "
                f"{', '.join(prohibited)}"
            )


def _model_document(value: object) -> Mapping[str, object]:
    dump = getattr(value, "model_dump", None)
    if not callable(dump):
        raise _adapter_failure("normalizer input and output must be request DTOs")
    document = dump(mode="python")
    if not isinstance(document, Mapping):
        raise _adapter_failure("normalizer produced a non-object request DTO")
    return document


def _authority_values(value: object, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], object]:
    found: dict[tuple[str, ...], object] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            item_path = (*path, str(key))
            if _is_authority_field(str(key)):
                found[item_path] = item
            found.update(_authority_values(item, item_path))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            found.update(_authority_values(item, (*path, str(index))))
    return found


def _is_authority_field(field: str) -> bool:
    leaf = field.rsplit(".", 1)[-1].lower()
    tokens = frozenset(leaf.split("_"))
    return bool(tokens.intersection(_AUTHORITY_FIELD_PARTS))


def _adapter_failure(message: str) -> SchemaNegotiationError:
    return SchemaNegotiationError(message, failure_code="ADAPTER_FAILURE")
