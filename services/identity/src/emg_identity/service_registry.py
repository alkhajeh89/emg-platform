"""Registry of known/allowed EMG service clients (Sprint 3, FEAT-02-3).

"Create representative service identities for development, including:
Identity Service, Authorization Service, Audit Service." This registry is
the identity side of that requirement: it maps a Keycloak client_id (the
`azp` claim on a validated service token) to the service's display name and
the realm roles it is least-privilege-granted in
tools/seed-data/keycloak/emg-realm.json.

`ServiceTokenValidator` (service_token_validator.py) rejects any token whose
`azp` is not present in this registry — an unrecognized service client_id is
never trusted merely because it holds a validly-signed Keycloak token. This
registry is deliberately code (not a database) for Sprint 3: registering a
new service is a reviewed, versioned change to this file plus the Keycloak
realm seed, consistent with ADR-016's "new agent roles/APIs are registered
... before deployment" pattern (ADR-016 §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceRegistryEntry:
    service_name: str
    roles: tuple[str, ...] = field(default_factory=tuple)


SERVICE_REGISTRY: dict[str, ServiceRegistryEntry] = {
    "emg-svc-identity": ServiceRegistryEntry(
        service_name="identity",
        roles=("service-account", "svc-identity"),
    ),
    "emg-svc-authorization": ServiceRegistryEntry(
        service_name="authorization",
        roles=("service-account", "svc-authorization"),
    ),
    "emg-svc-audit": ServiceRegistryEntry(
        service_name="audit",
        roles=("service-account", "svc-audit"),
    ),
    "emg-svc-knowledge-graph-writer": ServiceRegistryEntry(
        service_name="knowledge-graph-writer",
        roles=("service-account", "svc-knowledge-graph-writer"),
    ),
}
