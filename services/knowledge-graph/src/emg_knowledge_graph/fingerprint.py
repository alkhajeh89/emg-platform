"""ADR-030 Fingerprint Version 1 for mutation commands."""

from __future__ import annotations

import hashlib
import math
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, cast

import rfc8785
from pydantic import BaseModel

from .commands import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    MergeEntitiesCommand,
    MutationCommand,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
)
from .errors import InvalidMutationCommandError

FINGERPRINT_VERSION = 1
COMMAND_SCHEMA_VERSION = 1
_MIN_SAFE_INTEGER = -(2**53) + 1
_MAX_SAFE_INTEGER = 2**53 - 1


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidMutationCommandError("fingerprint datetime must be timezone-aware")
    utc = value.astimezone(timezone.utc)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_value(value: object) -> object:
    """Convert repository value objects to the JSON domain accepted by JCS."""
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, datetime):
        return _datetime_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, int):
        if not (_MIN_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER):
            raise InvalidMutationCommandError("fingerprint integer exceeds the JCS safe range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidMutationCommandError("fingerprint floats must be finite")
        return value
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canonical_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise InvalidMutationCommandError("fingerprint object keys must be strings")
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    raise InvalidMutationCommandError(f"unsupported fingerprint value type: {type(value).__name__}")


def _operation_and_payload(command: MutationCommand) -> tuple[str, dict[str, object]]:
    if isinstance(command, CreateEntityCommand):
        return "entity.create", {"entity": _canonical_value(command.entity)}
    if isinstance(command, ReplaceEntityCommand):
        return (
            f"entity.{command.action.value}",
            {
                "replacement": _canonical_value(command.replacement),
                "reason": command.reason,
            },
        )
    if isinstance(command, ReplaceRelationshipCommand):
        return (
            "relationship.update",
            {"replacement": _canonical_value(command.replacement)},
        )
    if isinstance(command, CloseRelationshipCommand):
        return (
            "relationship.close",
            {"edge_id": command.edge_id, "reason": command.reason},
        )
    if isinstance(command, MergeEntitiesCommand):
        return (
            "entity.merge",
            {
                "survivor_id": command.survivor_id,
                "source_ids": sorted(command.source_ids),
                "reason": command.reason,
            },
        )
    raise InvalidMutationCommandError(
        f"unsupported mutation command type: {type(command).__name__}"
    )


def canonical_fingerprint_document(command: MutationCommand) -> dict[str, object]:
    """Return the fully materialized ADR-030 Fingerprint V1 envelope.

    The transport idempotency key is intentionally excluded. Ontology fields,
    including an ontology ``correlation_id``, remain inside the command payload.
    """
    operation, payload = _operation_and_payload(command)
    return {
        "schema": "emg.kg.mutation-command",
        "schema_version": COMMAND_SCHEMA_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "operation": operation,
        "tenant_id": command.tenant.value,
        "principal": {
            "kind": command.principal.kind.value,
            "principal_id": str(command.principal.principal_id),
        },
        "as_of": _datetime_text(command.as_of),
        "payload": payload,
    }


def canonical_fingerprint_bytes(command: MutationCommand) -> bytes:
    """Serialize the Fingerprint V1 envelope using RFC 8785 JCS."""
    document = _canonical_value(canonical_fingerprint_document(command))
    try:
        return rfc8785.dumps(cast(Any, document))
    except (rfc8785.CanonicalizationError, UnicodeEncodeError) as exc:
        raise InvalidMutationCommandError(f"command cannot be canonicalized: {exc}") from exc


def command_fingerprint(command: MutationCommand) -> str:
    """Return the lowercase SHA-256 digest of the canonical V1 envelope."""
    return hashlib.sha256(canonical_fingerprint_bytes(command)).hexdigest()


def command_operation(command: MutationCommand) -> str:
    """Return the closed operation name embedded in Fingerprint V1."""
    operation, _ = _operation_and_payload(command)
    return operation
