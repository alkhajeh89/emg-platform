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
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ServicePrincipalLike(Protocol):
    """Matches `emg_identity.service_principal.ServicePrincipal` exactly:
    `client_id`, `service_name`, `roles`, `scopes`. No `attributes` field —
    machine identities carry no classification/department claims by Sprint
    3 design, so ABAC attribute conditions never apply to a service caller
    (see emg-policy-engine's evaluation semantics)."""

    @property
    def client_id(self) -> str: ...

    @property
    def service_name(self) -> str: ...

    @property
    def roles(self) -> tuple[str, ...]: ...

    @property
    def scopes(self) -> tuple[str, ...]: ...
