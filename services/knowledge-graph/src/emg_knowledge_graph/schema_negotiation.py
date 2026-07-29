"""Application-owned schema-negotiation contract (ADR-032)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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
