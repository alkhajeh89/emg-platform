"""Service-local ADR-033 schema catalog and negotiation infrastructure."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from time import perf_counter
from types import MappingProxyType
from typing import Any, TypeGuard

from emg_knowledge_graph import (
    SchemaNegotiationError,
    SchemaNegotiationRequest,
    SchemaNegotiationResult,
)
from emg_telemetry import get_logger
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

_MAX_VERSION_LENGTH = 128
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_AUTHORITY_FIELD_PARTS = frozenset({"classification", "owner", "tenant", "principal"})
_log = get_logger("knowledge-graph-schema")


class SchemaCatalogValidationError(ValueError):
    """The immutable schema catalog is incomplete or internally inconsistent."""


class SchemaBootGateError(ValueError):
    """Catalog and normalizer registrations cannot safely serve traffic."""


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
        """Support startup validation; runtime adapters use immutable lookup indexes."""

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
        raise SchemaCatalogValidationError("schema catalog generation must be non-blank")
    if not catalog.versions:
        raise SchemaCatalogValidationError("schema catalog must contain at least one version")
    if not is_well_formed_schema_version(catalog.canonical_version):
        raise SchemaCatalogValidationError(
            "canonical schema version must be fully qualified SemVer"
        )

    identifiers = tuple(entry.version for entry in catalog.versions)
    if len(identifiers) != len(set(identifiers)):
        raise SchemaCatalogValidationError("schema catalog version identifiers must be unique")
    for entry in catalog.versions:
        _validate_entry(entry)

    canonical = catalog.entry(catalog.canonical_version)
    if canonical is None:
        raise SchemaCatalogValidationError("canonical schema version is absent from the catalog")
    if (
        canonical.state is not SchemaLifecycleState.PUBLISHED
        or canonical.compatibility is not SchemaCompatibility.STRICT
        or canonical.normalization_required
        or canonical.normalizer_ids
    ):
        raise SchemaCatalogValidationError(
            "canonical schema version must be published, strict, and unnormalized"
        )


def _validate_entry(entry: SchemaCatalogEntry) -> None:
    if not is_well_formed_schema_version(entry.version):
        raise SchemaCatalogValidationError(
            f"schema version {entry.version!r} must be fully qualified SemVer"
        )
    if any(not identifier.strip() for identifier in entry.normalizer_ids):
        raise SchemaCatalogValidationError(
            f"schema version {entry.version!r} has a blank normalizer identifier"
        )

    requires_normalization = entry.compatibility is SchemaCompatibility.NORMALIZATION_REQUIRED
    if entry.normalization_required != requires_normalization:
        raise SchemaCatalogValidationError(
            f"schema version {entry.version!r} has inconsistent normalization classification"
        )
    if not entry.normalization_required and entry.normalizer_ids:
        raise SchemaCatalogValidationError(
            f"schema version {entry.version!r} declares normalizers without requiring them"
        )
    if entry.state is SchemaLifecycleState.PUBLISHED:
        if entry.deprecated_at is not None or entry.retirement_at is not None:
            raise SchemaCatalogValidationError(
                f"published schema version {entry.version!r} cannot have lifecycle instants"
            )
    elif entry.state is SchemaLifecycleState.DEPRECATED:
        _require_lifecycle_instants(entry)
        assert entry.deprecated_at is not None
        assert entry.retirement_at is not None
        if entry.deprecated_at >= entry.retirement_at:
            raise SchemaCatalogValidationError(
                f"deprecated schema version {entry.version!r} must retire after deprecation"
            )
    else:
        _require_lifecycle_instants(entry)
        if entry.normalization_required or entry.normalizer_ids:
            raise SchemaCatalogValidationError(
                f"retired schema version {entry.version!r} cannot require normalization"
            )


def _require_lifecycle_instants(entry: SchemaCatalogEntry) -> None:
    if entry.deprecated_at is None or entry.retirement_at is None:
        raise SchemaCatalogValidationError(
            f"{entry.state.value} schema version {entry.version!r} "
            "requires deprecation and retirement instants"
        )


def load_schema_catalog(document: object) -> SchemaCatalog:
    """Load one format-neutral catalog document and validate it."""

    try:
        catalog = SchemaCatalog.model_validate(document)
    except ValidationError as exc:
        raise SchemaCatalogValidationError(f"invalid schema catalog: {exc}") from exc
    validate_schema_catalog(catalog)
    return catalog


@dataclass(frozen=True, slots=True, init=False)
class RegistryBackedSchemaNegotiator:
    """Perform constant-time, exact-version negotiation against one catalog."""

    _catalog: SchemaCatalog
    _entries: Mapping[str, SchemaCatalogEntry]

    def __init__(self, catalog: SchemaCatalog) -> None:
        validate_schema_catalog(catalog)
        object.__setattr__(self, "_catalog", catalog)
        object.__setattr__(
            self,
            "_entries",
            MappingProxyType({entry.version: entry for entry in catalog.versions}),
        )
        _record_metric(
            "schema_catalog_generation_info",
            metric_type="gauge",
            value=1,
            canonical_version=catalog.canonical_version,
            catalog_generation=catalog.generation,
        )

    def negotiate(self, request: SchemaNegotiationRequest) -> SchemaNegotiationResult:
        requested = request.preferred_version
        if not is_well_formed_schema_version(requested):
            error = SchemaNegotiationError(
                f"schema version {requested!r} is not a fully qualified version identifier",
                failure_code="MALFORMED_SCHEMA",
            )
            self._record_rejection(requested, None, error.failure_code)
            raise error
        entry = self._entries.get(requested)
        if entry is None:
            error = SchemaNegotiationError(
                f"schema version {requested!r} is not present in the catalog",
                failure_code="UNKNOWN_SCHEMA",
            )
            self._record_rejection(requested, None, error.failure_code)
            raise error
        if entry.state is SchemaLifecycleState.RETIRED:
            error = SchemaNegotiationError(
                f"schema version {requested!r} is retired",
                failure_code="RETIRED_SCHEMA",
            )
            self._record_rejection(requested, entry, error.failure_code)
            raise error
        if entry.compatibility in {
            SchemaCompatibility.MIGRATION_REQUIRED,
            SchemaCompatibility.INCOMPATIBLE,
        }:
            error = SchemaNegotiationError(
                f"schema version {requested!r} is incompatible with canonical execution",
                failure_code="INCOMPATIBLE_SCHEMA",
            )
            self._record_rejection(requested, entry, error.failure_code)
            raise error
        _record_negotiation(
            requested_version=requested,
            effective_version=requested,
            canonical_version=self._catalog.canonical_version,
            lifecycle=entry.state.value,
            compatibility=entry.compatibility.value,
            normalization_required=entry.normalization_required,
            outcome="accepted",
            failure_code=None,
            catalog_generation=self._catalog.generation,
        )
        _record_metric(
            "schema_negotiation_attempt_total",
            metric_type="counter",
            value=1,
            requested_version=requested,
            outcome="accepted",
            failure_code=None,
            catalog_generation=self._catalog.generation,
        )
        if entry.state is SchemaLifecycleState.DEPRECATED:
            _record_metric(
                "schema_deprecated_usage_total",
                metric_type="counter",
                value=1,
                requested_version=requested,
                catalog_generation=self._catalog.generation,
            )
            _emit_schema_event(
                "schema_deprecated_version_accepted",
                outcome="accepted",
                requested_version=requested,
                effective_version=requested,
                lifecycle=entry.state.value,
                compatibility=entry.compatibility.value,
                normalization_required=entry.normalization_required,
                failure_code=None,
                catalog_generation=self._catalog.generation,
            )
        return SchemaNegotiationResult(
            effective_version=requested,
            adapter_required=entry.normalization_required,
        )

    def _record_rejection(
        self,
        requested: str,
        entry: SchemaCatalogEntry | None,
        failure_code: str,
    ) -> None:
        _record_negotiation(
            requested_version=requested,
            effective_version=None,
            canonical_version=self._catalog.canonical_version,
            lifecycle=None if entry is None else entry.state.value,
            compatibility=None if entry is None else entry.compatibility.value,
            normalization_required=(False if entry is None else entry.normalization_required),
            outcome="rejected",
            failure_code=failure_code,
            catalog_generation=self._catalog.generation,
        )
        _record_metric(
            "schema_negotiation_attempt_total",
            metric_type="counter",
            value=1,
            requested_version=requested,
            outcome="rejected",
            failure_code=failure_code,
            catalog_generation=self._catalog.generation,
        )
        _record_metric(
            "schema_negotiation_failure_total",
            metric_type="counter",
            value=1,
            failure_code=failure_code,
            catalog_generation=self._catalog.generation,
        )


@dataclass(frozen=True, slots=True, init=False)
class RegistryBackedCompatibilityAdapterRegistry:
    """Resolve one exact-pair normalizer from an immutable registration set."""

    _catalog: SchemaCatalog
    _registrations: tuple[CompatibilityNormalizerRegistration, ...]
    _entries: Mapping[str, SchemaCatalogEntry]
    _registrations_by_pair: Mapping[
        tuple[str, str], tuple[CompatibilityNormalizerRegistration, ...]
    ]

    def __init__(
        self,
        catalog: SchemaCatalog,
        registrations: tuple[CompatibilityNormalizerRegistration, ...],
    ) -> None:
        validate_schema_catalog(catalog)
        registrations_by_pair: dict[
            tuple[str, str], tuple[CompatibilityNormalizerRegistration, ...]
        ] = {}
        for registration in registrations:
            pair = (registration.source_version, registration.target_version)
            registrations_by_pair[pair] = (
                *registrations_by_pair.get(pair, ()),
                registration,
            )
        object.__setattr__(self, "_catalog", catalog)
        object.__setattr__(self, "_registrations", registrations)
        object.__setattr__(
            self,
            "_entries",
            MappingProxyType({entry.version: entry for entry in catalog.versions}),
        )
        object.__setattr__(
            self,
            "_registrations_by_pair",
            MappingProxyType(registrations_by_pair),
        )

    @property
    def catalog(self) -> SchemaCatalog:
        return self._catalog

    @property
    def registrations(self) -> tuple[CompatibilityNormalizerRegistration, ...]:
        return self._registrations

    def registrations_for(
        self, source_version: str, target_version: str
    ) -> tuple[CompatibilityNormalizerRegistration, ...]:
        return self._registrations_by_pair.get((source_version, target_version), ())

    def normalize(
        self,
        request: Any,
        *,
        source_version: str,
        target_version: str | None = None,
    ) -> Any:
        entry = self._entries.get(source_version)
        if entry is None or not entry.normalization_required:
            # Canonicalization is logically present for every accepted request.
            # Strict and Backward compatibility use the identity operation; only
            # Normalization Required invokes a registered adapter.
            return request
        target_version = target_version or self.catalog.canonical_version
        started = perf_counter()
        _record_metric(
            "schema_normalization_attempt_total",
            metric_type="counter",
            value=1,
            source_version=source_version,
            target_version=target_version,
            catalog_generation=self.catalog.generation,
        )
        try:
            matches = self.registrations_for(source_version, target_version)
            if len(matches) != 1:
                raise _adapter_failure(
                    f"normalizer resolution for {source_version!r} "
                    f"to {target_version!r} is invalid"
                )
            registration = matches[0]
            try:
                normalized = registration.normalizer(request)
            except Exception as exc:
                raise _adapter_failure(f"normalizer {registration.normalizer_id!r} failed") from exc
            _validate_closed_field_domain(request, normalized)
            before = _model_document(request)
            after = _model_document(normalized)
            if _authority_values(before) != _authority_values(after):
                raise _adapter_failure("normalizer changed an authority-bearing value")
        except SchemaNegotiationError as exc:
            elapsed = perf_counter() - started
            _record_normalization(
                source_version=source_version,
                target_version=target_version,
                outcome="failed",
                failure_code=exc.failure_code,
                elapsed_seconds=elapsed,
                catalog_generation=self.catalog.generation,
            )
            raise
        elapsed = perf_counter() - started
        _record_normalization(
            source_version=source_version,
            target_version=target_version,
            outcome="accepted",
            failure_code=None,
            elapsed_seconds=elapsed,
            catalog_generation=self.catalog.generation,
        )
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
                raise SchemaBootGateError(
                    f"schema version {entry.version!r} requires exactly one normalizer"
                )
            if entry.normalizer_ids != (matches[0].normalizer_id,):
                raise SchemaBootGateError(
                    f"schema version {entry.version!r} normalizer declaration does not match"
                )
        elif matches:
            raise SchemaBootGateError(
                f"schema version {entry.version!r} has an undeclared normalizer registration"
            )

    for registration in registry.registrations:
        source_entry = catalog.entry(registration.source_version)
        if (
            source_entry is None
            or registration.target_version != catalog.canonical_version
            or not source_entry.normalization_required
        ):
            raise SchemaBootGateError(
                f"normalizer {registration.normalizer_id!r} is not declared by the catalog"
            )
        prohibited = tuple(
            field for field in registration.written_fields if _is_authority_field(field)
        )
        if prohibited:
            raise SchemaBootGateError(
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


def _validate_closed_field_domain(
    before: object,
    after: object,
    path: tuple[str, ...] = (),
) -> None:
    """Reject structural expansion or contraction at any DTO nesting depth."""

    location = ".".join(path) or "<request>"
    if isinstance(before, BaseModel):
        if type(after) is not type(before):
            raise _adapter_failure(f"normalizer changed model type at {location}")
        assert isinstance(after, BaseModel)
        fields = type(before).model_fields
        if fields.keys() != type(after).model_fields.keys():
            raise _adapter_failure(f"normalizer changed model fields at {location}")
        for field in fields:
            _validate_closed_field_domain(
                getattr(before, field),
                getattr(after, field),
                (*path, field),
            )
        return

    if isinstance(before, Mapping):
        if type(after) is not type(before):
            raise _adapter_failure(f"normalizer changed mapping type at {location}")
        assert isinstance(after, Mapping)
        if before.keys() != after.keys():
            raise _adapter_failure(f"normalizer changed mapping keys at {location}")
        for key in before:
            _validate_closed_field_domain(
                before[key],
                after[key],
                (*path, str(key)),
            )
        return

    if _is_sequence(before):
        if type(after) is not type(before):
            raise _adapter_failure(f"normalizer changed sequence type at {location}")
        assert isinstance(after, Sequence)
        if len(before) != len(after):
            raise _adapter_failure(f"normalizer changed sequence length at {location}")
        for index, (before_item, after_item) in enumerate(zip(before, after, strict=True)):
            _validate_closed_field_domain(
                before_item,
                after_item,
                (*path, str(index)),
            )
        return

    if type(after) is not type(before):
        raise _adapter_failure(f"normalizer changed value domain at {location}")


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


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


def _record_negotiation(
    *,
    requested_version: str,
    effective_version: str | None,
    canonical_version: str,
    lifecycle: str | None,
    compatibility: str | None,
    normalization_required: bool,
    outcome: str,
    failure_code: str | None,
    catalog_generation: str,
) -> None:
    _emit_schema_event(
        "schema_negotiation",
        outcome=outcome,
        requested_version=requested_version,
        effective_version=effective_version,
        canonical_version=canonical_version,
        lifecycle=lifecycle,
        compatibility=compatibility,
        normalization_required=normalization_required,
        failure_code=failure_code,
        catalog_generation=catalog_generation,
    )


def _record_normalization(
    *,
    source_version: str,
    target_version: str,
    outcome: str,
    failure_code: str | None,
    elapsed_seconds: float,
    catalog_generation: str,
) -> None:
    _emit_schema_event(
        "schema_normalization",
        outcome=outcome,
        source_version=source_version,
        target_version=target_version,
        failure_code=failure_code,
        catalog_generation=catalog_generation,
    )
    if failure_code is not None:
        _record_metric(
            "schema_normalization_failure_total",
            metric_type="counter",
            value=1,
            source_version=source_version,
            target_version=target_version,
            failure_code=failure_code,
            catalog_generation=catalog_generation,
        )
    _record_metric(
        "schema_normalization_latency_seconds",
        metric_type="histogram_observation",
        value=elapsed_seconds,
        source_version=source_version,
        target_version=target_version,
        outcome=outcome,
        catalog_generation=catalog_generation,
    )


def _record_metric(
    metric_name: str,
    *,
    metric_type: str,
    value: int | float,
    **dimensions: object,
) -> None:
    """Emit collector-ready metric observations through structured telemetry.

    ``emg_telemetry`` currently provides the repository's log emitter but no
    separate metrics client. Encoding counter/gauge/histogram observations as
    named structured events keeps collection compatible with that mechanism
    without introducing a second metrics framework in this service.
    """

    outcome = str(dimensions.pop("outcome", "observed"))
    _emit_schema_event(
        "schema_metric",
        outcome=outcome,
        metric_name=metric_name,
        metric_type=metric_type,
        metric_value=value,
        **dimensions,
    )


def _emit_schema_event(event: str, *, outcome: str, **metadata: object) -> None:
    """Emit only schema-control metadata; request content is never accepted."""

    document = {"event": event, "outcome": outcome, **metadata}
    _log.info(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        extra={
            "actor": "schema-runtime",
            "module": "knowledge-graph",
            "action": event,
            "outcome": outcome,
        },
    )
