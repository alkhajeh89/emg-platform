"""Tenant identity — the multi-tenancy spine (Freeze §9, §12).

The frozen architecture requires that *"every datum carries ``tenant_id``"*
(§12) and names ``tenant_id`` an additive dimension on every node/edge/evidence
(§9). ``TenantId`` is the minimal, immutable value type for that dimension. It is
defined here in Phase 1 and threaded through persistence and the PDP in later
phases; the frozen multi-tenancy *model* (shared-schema baseline, isolation
tiers) is §17.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..labels import SafeLabel


class TenantId(BaseModel):
    """An immutable, validated tenant identifier.

    Wrapping the raw string in a value type (rather than passing bare ``str``)
    makes tenant scoping explicit and type-checkable across every store and
    service boundary — a mutation or read can never silently omit its tenant.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: SafeLabel

    @classmethod
    def of(cls, value: str) -> TenantId:
        """Construct from a raw string (validated by ``SafeLabel``)."""
        return cls(value=value)

    def __str__(self) -> str:
        return self.value


# Well-known tenant for platform-internal / single-tenant deployments. Explicit
# so that "no tenant" is never represented as an empty or implicit value.
SYSTEM_TENANT = TenantId(value="__system__")
