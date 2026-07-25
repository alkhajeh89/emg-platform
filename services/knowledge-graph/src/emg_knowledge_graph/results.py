"""Immutable results returned by knowledge-graph application workflows."""

from __future__ import annotations

from dataclasses import dataclass

from emg_platform_core import PrincipalRef, TenantId


@dataclass(frozen=True, slots=True)
class BuildRevisionResult:
    """Application DTO derived from a committed receipt and build statistics."""

    tenant: TenantId
    principal: PrincipalRef
    content_hash: str
    node_count: int
    edge_count: int
    nodes_created: int
    edges_created: int
    node_inputs_merged: int
    edge_inputs_merged: int
