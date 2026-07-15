"""Service (machine) principal — deliberately NOT `emg_auth_client.Principal`.

Sprint 3 (FEAT-02-3) requires "clear separation between user sessions and
service identities." Rather than overload the human `Principal` type with a
`principal_type` flag (easy to forget to check), a service caller is
represented by a structurally distinct type. Anywhere code expects a
`ServicePrincipal` cannot accidentally be handed a human `Principal` (or
vice versa) without a type error — the separation is enforced by the type
system, not by convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServicePrincipal:
    """The authenticated identity of an EMG *service* (never a human),
    derived from a validated Keycloak client-credentials access token."""

    client_id: str
    service_name: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    scopes: tuple[str, ...] = field(default_factory=tuple)
