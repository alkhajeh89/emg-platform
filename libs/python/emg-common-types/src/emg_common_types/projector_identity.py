"""ADR-041 canonical, non-secret Audit Projector identity inventory.

The inventory is deliberately transport-neutral and stdlib-only so the Audit
Service, Audit Projector, Keycloak provisioner, and repository validators can
apply one fail-closed parser without sharing credential material.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

_TOP_LEVEL_KEYS = frozenset({"version", "projector_identities"})
_ENTRY_KEYS = frozenset({"tenant_id", "client_id"})
_PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "placeholder",
    "provided-by-environment",
    "replace-me",
    "todo",
)


@dataclass(frozen=True, order=True)
class ProjectorIdentity:
    """One stable tenant-to-projector-client binding."""

    tenant_id: str
    client_id: str


def _required_identifier(value: object, field: str, *, reject_placeholders: bool) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"projector identity {field} must be a non-blank trimmed string")
    lowered = value.casefold()
    if reject_placeholders and any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        raise ValueError(f"projector identity {field} contains an unresolved placeholder")
    return value


def parse_projector_identity_inventory(
    raw_json: str, *, reject_placeholders: bool = True
) -> tuple[ProjectorIdentity, ...]:
    """Parse and validate the version-1 ADR-041 identity inventory.

    Output is sorted by ``client_id`` so every derived representation is
    deterministic regardless of environment input ordering.
    """

    try:
        raw = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("projector identity inventory must be valid JSON") from exc
    if not isinstance(raw, dict) or set(raw) != _TOP_LEVEL_KEYS:
        raise ValueError(
            "projector identity inventory must contain exactly version and projector_identities"
        )
    if raw["version"] != 1:
        raise ValueError("projector identity inventory version must be 1")
    entries = raw["projector_identities"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("projector identity inventory must contain at least one identity")

    identities: list[ProjectorIdentity] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise ValueError("each projector identity must contain exactly tenant_id and client_id")
        identities.append(
            ProjectorIdentity(
                tenant_id=_required_identifier(
                    entry["tenant_id"], "tenant_id", reject_placeholders=reject_placeholders
                ),
                client_id=_required_identifier(
                    entry["client_id"], "client_id", reject_placeholders=reject_placeholders
                ),
            )
        )

    tenants = [identity.tenant_id for identity in identities]
    clients = [identity.client_id for identity in identities]
    if len(set(tenants)) != len(tenants):
        raise ValueError("projector identity inventory contains duplicate tenant_id values")
    if len(set(clients)) != len(clients):
        raise ValueError("projector identity inventory contains duplicate client_id values")
    return tuple(sorted(identities, key=lambda identity: identity.client_id))


def projector_client_allow_list(identities: tuple[ProjectorIdentity, ...]) -> tuple[str, ...]:
    """Return the deterministic Audit Service recognized-client allow-list."""

    return tuple(identity.client_id for identity in identities)


def validate_projector_credential_bindings(
    identities: tuple[ProjectorIdentity, ...], credentials: object
) -> None:
    """Require one exact secret-bearing runtime binding per inventory entry.

    Secret values are checked only for presence and are never returned or
    included in errors.
    """

    if not isinstance(credentials, list):
        raise ValueError("projector tenant credentials must contain a JSON array")
    actual: set[tuple[str, str]] = set()
    for credential in credentials:
        if not isinstance(credential, dict) or set(credential) != {
            "tenant_id",
            "client_id",
            "client_secret",
        }:
            raise ValueError(
                "each projector credential must contain tenant_id, client_id, and client_secret"
            )
        tenant_id = _required_identifier(
            credential["tenant_id"], "tenant_id", reject_placeholders=True
        )
        client_id = _required_identifier(
            credential["client_id"], "client_id", reject_placeholders=True
        )
        secret = credential["client_secret"]
        if not isinstance(secret, str) or not secret:
            raise ValueError("each projector credential must contain a non-blank client secret")
        binding = (tenant_id, client_id)
        if binding in actual:
            raise ValueError("projector tenant credentials contain a duplicate binding")
        actual.add(binding)

    expected = {(identity.tenant_id, identity.client_id) for identity in identities}
    if actual != expected:
        raise ValueError("projector tenant credentials do not exactly match identity inventory")
