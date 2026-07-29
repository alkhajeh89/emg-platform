"""Application-owned schema-negotiation contract (ADR-032)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable

_RequestT = TypeVar("_RequestT")


@dataclass(frozen=True, slots=True)
class SchemaNegotiationRequest:
    """A client's preferred immutable semantic-schema version."""

    preferred_version: str


@dataclass(frozen=True, slots=True)
class SchemaNegotiationResult:
    """The authoritative effective version selected before command creation."""

    effective_version: str
    adapter_required: bool = False


@runtime_checkable
class SchemaNegotiator(Protocol):
    """Application port implemented by the authoritative schema registry."""

    def negotiate(self, request: SchemaNegotiationRequest) -> SchemaNegotiationResult:
        """Select an effective supported version or raise a schema error."""
        ...


@runtime_checkable
class CompatibilityAdapterRegistry(Protocol):
    """Normalize one accepted request DTO into canonical-schema semantics."""

    def normalize(
        self,
        request: _RequestT,
        *,
        source_version: str,
        target_version: str,
    ) -> _RequestT:
        """Return the same DTO family with canonical, non-authority-bearing values."""
        ...
