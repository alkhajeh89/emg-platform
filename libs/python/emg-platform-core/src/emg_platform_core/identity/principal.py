"""Principal provenance — who or what asserted a change (Freeze §9).

The frozen architecture requires *"principal provenance on every mutation — who/
what asserted it"*. ``PrincipalRef`` is the minimal, immutable value type that
carries that identity. It is defined here in Phase 1; Phase 2 threads it through
the persistence write path so every stored mutation records its asserting
principal.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from ..labels import SafeLabel


class PrincipalKind(str, Enum):
    """The category of actor that asserted a change."""

    USER = "user"
    SERVICE = "service"
    CONNECTOR = "connector"
    SYSTEM = "system"


class PrincipalRef(BaseModel):
    """An immutable reference to the actor responsible for a mutation.

    Not an identity *record* (that belongs to the identity service, Freeze §10/
    §11) — only a stable, auditable *reference* usable as mutation provenance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_id: SafeLabel
    kind: PrincipalKind

    @classmethod
    def user(cls, principal_id: str) -> PrincipalRef:
        return cls(principal_id=principal_id, kind=PrincipalKind.USER)

    @classmethod
    def service(cls, principal_id: str) -> PrincipalRef:
        return cls(principal_id=principal_id, kind=PrincipalKind.SERVICE)

    @classmethod
    def connector(cls, principal_id: str) -> PrincipalRef:
        return cls(principal_id=principal_id, kind=PrincipalKind.CONNECTOR)

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.principal_id}"


# Well-known principal for platform-internal operations (bootstrap, migrations,
# system-initiated writes). Explicit, so system actions are never mistaken for a
# user or service actor.
SYSTEM_PRINCIPAL = PrincipalRef(principal_id="__system__", kind=PrincipalKind.SYSTEM)
