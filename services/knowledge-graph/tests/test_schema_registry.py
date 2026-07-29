"""ADR-033 Revision 2 Phase 1 schema-registry foundation tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from emg_knowledge_graph import (
    CompatibilityAdapterRegistry,
    SchemaNegotiationError,
    SchemaNegotiationRequest,
    SchemaNegotiationResult,
    SchemaNegotiator,
)
from emg_knowledge_graph_api.dependencies import schema_negotiator_dependency
from emg_knowledge_graph_infrastructure import (
    CompatibilityNormalizerRegistration,
    RegistryBackedCompatibilityAdapterRegistry,
    RegistryBackedSchemaNegotiator,
    SchemaCatalog,
    SchemaCatalogEntry,
    SchemaCompatibility,
    SchemaLifecycleState,
    load_schema_catalog,
    validate_schema_boot_gate,
    validate_schema_catalog,
)
from pydantic import BaseModel, ConfigDict, ValidationError

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER = datetime(2026, 7, 1, tzinfo=timezone.utc)


class _RequestDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    classification: str = "INTERNAL"
    owner: str = "writer"
    source_principal: str = "writer"


def _catalog(*entries: SchemaCatalogEntry) -> SchemaCatalog:
    versions = entries or (
        SchemaCatalogEntry(
            version="2.1.0",
            state=SchemaLifecycleState.PUBLISHED,
            compatibility=SchemaCompatibility.STRICT,
        ),
    )
    return SchemaCatalog(
        generation="generation-1",
        canonical_version="2.1.0",
        versions=versions,
    )


def _entry(
    version: str,
    compatibility: SchemaCompatibility,
    *,
    state: SchemaLifecycleState = SchemaLifecycleState.PUBLISHED,
    normalization_required: bool = False,
    normalizer_ids: tuple[str, ...] = (),
) -> SchemaCatalogEntry:
    lifecycle = (
        {"deprecated_at": NOW, "retirement_at": LATER}
        if state is not SchemaLifecycleState.PUBLISHED
        else {}
    )
    return SchemaCatalogEntry(
        version=version,
        state=state,
        compatibility=compatibility,
        normalization_required=normalization_required,
        normalizer_ids=normalizer_ids,
        **lifecycle,
    )


def _registration(
    normalizer: Callable[[object], object] = lambda value: value,
    *,
    normalizer_id: str = "normalize-1.2-to-2.1",
    source_version: str = "1.2.0",
    target_version: str = "2.1.0",
    written_fields: tuple[str, ...] = (),
) -> CompatibilityNormalizerRegistration:
    return CompatibilityNormalizerRegistration(
        normalizer_id=normalizer_id,
        source_version=source_version,
        target_version=target_version,
        written_fields=written_fields,
        normalizer=normalizer,
    )


def _normalizing_catalog() -> SchemaCatalog:
    return _catalog(
        _entry("2.1.0", SchemaCompatibility.STRICT),
        _entry("2.0.0", SchemaCompatibility.BACKWARD),
        _entry(
            "1.2.0",
            SchemaCompatibility.NORMALIZATION_REQUIRED,
            normalization_required=True,
            normalizer_ids=("normalize-1.2-to-2.1",),
        ),
    )


def test_application_ports_remain_structural_and_transport_independent() -> None:
    catalog = _catalog()
    negotiator = RegistryBackedSchemaNegotiator(catalog)
    registry = RegistryBackedCompatibilityAdapterRegistry(catalog, ())

    assert isinstance(negotiator, SchemaNegotiator)
    assert isinstance(registry, CompatibilityAdapterRegistry)
    assert SchemaNegotiationResult.__dataclass_fields__.keys() == {
        "effective_version",
        "adapter_required",
    }


@pytest.mark.parametrize(
    ("version", "state", "compatibility", "normalization_required", "expected_adapter"),
    [
        (
            "2.1.0",
            SchemaLifecycleState.PUBLISHED,
            SchemaCompatibility.STRICT,
            False,
            False,
        ),
        (
            "2.0.0",
            SchemaLifecycleState.PUBLISHED,
            SchemaCompatibility.BACKWARD,
            False,
            False,
        ),
        (
            "1.4.0",
            SchemaLifecycleState.DEPRECATED,
            SchemaCompatibility.BACKWARD,
            False,
            False,
        ),
        (
            "1.2.0",
            SchemaLifecycleState.PUBLISHED,
            SchemaCompatibility.NORMALIZATION_REQUIRED,
            True,
            True,
        ),
    ],
)
def test_exact_catalog_versions_negotiate_to_the_requested_contract(
    version: str,
    state: SchemaLifecycleState,
    compatibility: SchemaCompatibility,
    normalization_required: bool,
    expected_adapter: bool,
) -> None:
    catalog = _catalog(
        _entry("2.1.0", SchemaCompatibility.STRICT),
        (
            _entry(
                version,
                compatibility,
                state=state,
                normalization_required=normalization_required,
                normalizer_ids=("normalizer",) if normalization_required else (),
            )
            if version != "2.1.0"
            else _entry("2.0.0", SchemaCompatibility.BACKWARD)
        ),
    )
    result = RegistryBackedSchemaNegotiator(catalog).negotiate(
        SchemaNegotiationRequest(preferred_version=version)
    )

    assert result == SchemaNegotiationResult(
        effective_version=version,
        adapter_required=expected_adapter,
    )


@pytest.mark.parametrize(
    ("version", "expected_code"),
    [
        ("1.0.0", "INCOMPATIBLE_SCHEMA"),
        ("0.9.0", "RETIRED_SCHEMA"),
        ("3.0.0", "UNKNOWN_SCHEMA"),
        ("9.9.9", "UNKNOWN_SCHEMA"),
        ("latest", "MALFORMED_SCHEMA"),
        ("2", "MALFORMED_SCHEMA"),
        ("2.x", "MALFORMED_SCHEMA"),
        (">=2.0.0", "MALFORMED_SCHEMA"),
    ],
)
def test_negotiation_failure_taxonomy_is_stable(version: str, expected_code: str) -> None:
    catalog = _catalog(
        _entry("2.1.0", SchemaCompatibility.STRICT),
        _entry("1.0.0", SchemaCompatibility.MIGRATION_REQUIRED),
        _entry(
            "0.9.0",
            SchemaCompatibility.INCOMPATIBLE,
            state=SchemaLifecycleState.RETIRED,
        ),
    )

    with pytest.raises(SchemaNegotiationError) as caught:
        RegistryBackedSchemaNegotiator(catalog).negotiate(
            SchemaNegotiationRequest(preferred_version=version)
        )

    assert caught.value.failure_code == expected_code


def test_catalog_loader_returns_a_closed_immutable_validated_catalog() -> None:
    catalog = load_schema_catalog(
        {
            "generation": "generation-1",
            "canonical_version": "2.1.0",
            "versions": [
                {
                    "version": "2.1.0",
                    "state": "published",
                    "compatibility": "strict",
                }
            ],
        }
    )

    assert catalog.canonical_version == "2.1.0"
    with pytest.raises(ValidationError, match="frozen"):
        catalog.generation = "changed"


@pytest.mark.parametrize(
    "document",
    [
        {},
        {
            "generation": "g",
            "canonical_version": "2.1.0",
            "versions": [],
        },
        {
            "generation": "g",
            "canonical_version": "2.1.0",
            "versions": [],
            "unknown": True,
        },
        "not-a-catalog",
    ],
)
def test_catalog_loader_rejects_missing_empty_extra_and_malformed_data(
    document: object,
) -> None:
    with pytest.raises(ValueError):
        load_schema_catalog(document)


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        (
            SchemaCatalog(generation="", canonical_version="2.1.0", versions=()),
            "generation",
        ),
        (
            SchemaCatalog(
                generation="g",
                canonical_version="2.1.0",
                versions=(
                    _entry("2.1.0", SchemaCompatibility.STRICT),
                    _entry("2.1.0", SchemaCompatibility.STRICT),
                ),
            ),
            "unique",
        ),
        (
            SchemaCatalog(
                generation="g",
                canonical_version="2.1.0",
                versions=(_entry("2.0.0", SchemaCompatibility.BACKWARD),),
            ),
            "absent",
        ),
        (
            SchemaCatalog(
                generation="g",
                canonical_version="2.1.0",
                versions=(_entry("2.1.0", SchemaCompatibility.BACKWARD),),
            ),
            "canonical",
        ),
    ],
)
def test_catalog_validator_rejects_ambiguous_or_canonical_less_catalogs(
    catalog: SchemaCatalog, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_schema_catalog(catalog)


def test_catalog_validator_requires_consistent_normalization_and_lifecycle() -> None:
    inconsistent = _catalog(
        _entry("2.1.0", SchemaCompatibility.STRICT),
        _entry("1.2.0", SchemaCompatibility.NORMALIZATION_REQUIRED),
    )
    invalid_lifecycle = _catalog(
        _entry("2.1.0", SchemaCompatibility.STRICT),
        SchemaCatalogEntry(
            version="1.4.0",
            state=SchemaLifecycleState.DEPRECATED,
            compatibility=SchemaCompatibility.BACKWARD,
        ),
    )

    with pytest.raises(ValueError, match="inconsistent normalization"):
        validate_schema_catalog(inconsistent)
    with pytest.raises(ValueError, match="requires deprecation and retirement"):
        validate_schema_catalog(invalid_lifecycle)


def test_boot_gate_accepts_exactly_one_declared_safe_normalizer() -> None:
    catalog = _normalizing_catalog()
    registry = RegistryBackedCompatibilityAdapterRegistry(catalog, (_registration(),))

    validate_schema_boot_gate(catalog, registry)


@pytest.mark.parametrize(
    ("registrations", "message"),
    [
        ((), "exactly one"),
        (
            (
                _registration(),
                _registration(normalizer_id="second-normalizer"),
            ),
            "exactly one",
        ),
        (
            (_registration(normalizer_id="different"),),
            "declaration does not match",
        ),
        (
            (_registration(written_fields=("replacement.classification",)),),
            "prohibited writes",
        ),
    ],
)
def test_boot_gate_rejects_missing_ambiguous_mismatched_and_authority_writing_normalizers(
    registrations: tuple[CompatibilityNormalizerRegistration, ...],
    message: str,
) -> None:
    catalog = _normalizing_catalog()
    registry = RegistryBackedCompatibilityAdapterRegistry(catalog, registrations)

    with pytest.raises(ValueError, match=message):
        validate_schema_boot_gate(catalog, registry)


def test_boot_gate_rejects_undeclared_normalizer_pair() -> None:
    catalog = _catalog(
        _entry("2.1.0", SchemaCompatibility.STRICT),
        _entry("2.0.0", SchemaCompatibility.BACKWARD),
    )
    registry = RegistryBackedCompatibilityAdapterRegistry(
        catalog,
        (_registration(source_version="2.0.0"),),
    )

    with pytest.raises(ValueError, match="undeclared normalizer"):
        validate_schema_boot_gate(catalog, registry)


def test_registry_is_identity_for_strict_and_backward_versions() -> None:
    catalog = _normalizing_catalog()
    registry = RegistryBackedCompatibilityAdapterRegistry(catalog, (_registration(),))
    request = _RequestDTO(label="unchanged")

    assert (
        registry.normalize(
            request,
            source_version="2.0.0",
            target_version="2.1.0",
        )
        is request
    )


def test_registry_applies_one_safe_dto_to_dto_normalizer() -> None:
    catalog = _normalizing_catalog()

    def normalize(value: object) -> object:
        assert isinstance(value, _RequestDTO)
        return value.model_copy(update={"label": value.label.upper()})

    registry = RegistryBackedCompatibilityAdapterRegistry(
        catalog,
        (_registration(normalize, written_fields=("label",)),),
    )
    validate_schema_boot_gate(catalog, registry)

    result = registry.normalize(
        _RequestDTO(label="canonical"),
        source_version="1.2.0",
        target_version="2.1.0",
    )

    assert result == _RequestDTO(label="CANONICAL")


@pytest.mark.parametrize(
    "normalizer",
    [
        lambda value: _RequestDTO(
            label=value.label,  # type: ignore[union-attr]
            classification="SECRET",
        ),
        lambda value: {"label": "not-a-dto"},
        lambda value: (_ for _ in ()).throw(RuntimeError("defect")),
    ],
)
def test_registry_converts_authority_shape_and_execution_defects_to_adapter_failure(
    normalizer: Callable[[object], object],
) -> None:
    catalog = _normalizing_catalog()
    registry = RegistryBackedCompatibilityAdapterRegistry(
        catalog,
        (_registration(normalizer),),
    )

    with pytest.raises(SchemaNegotiationError) as caught:
        registry.normalize(
            _RequestDTO(label="value"),
            source_version="1.2.0",
            target_version="2.1.0",
        )

    assert caught.value.failure_code == "ADAPTER_FAILURE"


def test_runtime_composition_remains_explicitly_fail_closed_in_phase_one() -> None:
    negotiator = schema_negotiator_dependency()

    with pytest.raises(SchemaNegotiationError) as caught:
        negotiator.negotiate(SchemaNegotiationRequest(preferred_version="2.1.0"))

    assert caught.value.failure_code == "NEGOTIATION_UNCONFIGURED"
