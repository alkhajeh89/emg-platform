"""Structural (duck-typed) shape of a machine/service identity.

Sprint 3's `emg_identity.service_principal.ServicePrincipal`
(`services/identity`, not a shared library) is the concrete machine-identity
type this platform actually issues. FEAT-03-1 requires the PEP contract to
"support both Principal and ServicePrincipal," but a shared library must
never import from a service (`services/*` depends on `libs/*`, never the
reverse — Engineering Master Plan §3).

`ServicePrincipalLike` is a `typing.Protocol` matching `ServicePrincipal`'s
exact field shape. Python Protocols are structural: any class with these
attributes satisfies this Protocol automatically, with no inheritance and no
import dependency in either direction. `mypy --strict` verifies the actual
`ServicePrincipal` passed at every call site genuinely matches — see
`services/identity/tests/test_authz_router.py`. Sprint 3's
`service_principal.py` is not modified by this Protocol's existence.

Members are declared as read-only `@property` methods, not plain class
attributes: `ServicePrincipal` is a frozen (immutable) dataclass, and
`mypy --strict` treats a Protocol's plain attribute annotations as requiring
a *settable* variable — a frozen dataclass field is read-only and fails that
stricter check even though it is a perfectly valid structural match for
read-only access, which is all this Protocol ever needs.

**`attributes` (ADR-026 Revision 2, Amendment 2, Group D2):** originally this
Protocol had no `attributes` field at all — "machine identities carry no
classification/department claims by Sprint 3 design, so ABAC attribute
conditions never apply to a service caller" (the prior version of this
docstring). ADR-026 Revision 2 revisited that Sprint-3-era simplification: it
was a point-in-time design choice, not a permanent invariant, and it left
`ServicePrincipalLike` unable to carry a clearance value (or any other ABAC
attribute) despite `emg_auth_client.Principal.attributes` already providing
exactly this shape for human callers. `attributes: dict[str, str]` is added
here, mirroring `Principal.attributes` exactly, so `PolicyEngine`'s
`required_attributes` conditions (`engine.py`) now evaluate identically for
both principal kinds. This is purely additive: every existing concrete
`ServicePrincipal` implementation gains this field with a
`field(default_factory=dict)` default, so no existing construction call site
needs to change (see `services/identity/src/emg_identity/service_principal.py`,
`services/audit/src/emg_audit_service/authn.py`,
`services/knowledge-graph/src/emg_knowledge_graph_api/authn.py`)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ServicePrincipalLike(Protocol):
    """Matches every concrete `ServicePrincipal` implementation's field
    shape: `client_id`, `service_name`, `roles`, `scopes`, `attributes`
    (the last added by ADR-026 Revision 2 — see this module's docstring)."""

    @property
    def client_id(self) -> str: ...

    @property
    def service_name(self) -> str: ...

    @property
    def roles(self) -> tuple[str, ...]: ...

    @property
    def scopes(self) -> tuple[str, ...]: ...

    @property
    def attributes(self) -> dict[str, str]: ...
