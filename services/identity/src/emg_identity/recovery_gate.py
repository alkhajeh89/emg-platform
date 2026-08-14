"""ADR-043 Amendment 1 fail-closed recovery-freshness gate (A4, A8).

Compares the externally materialized ``(generation, authority_revision)``
pair against PostgreSQL's reconciled pair before any refresh-token
readiness or request-time operation is permitted to proceed. PostgreSQL's
copy is a reconciliation record, never a freshness authority (A4): this gate
always re-derives both sides fresh and never infers freshness from
timestamps, row presence alone, or the generation in isolation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class RecoveryGateDenied(Exception):
    """The Amendment 1 recovery-freshness predicate failed closed.

    Raised for every fail-closed condition required by A8: a missing,
    unreadable, or malformed materialized authority file; a missing,
    duplicated, or malformed PostgreSQL recovery-state row; or a pair
    mismatch between the two.
    """


@dataclass(frozen=True, slots=True)
class AuthorityPair:
    """The compared ``(generation, authority_revision)`` pair."""

    generation: str
    authority_revision: str


def _read_materialized_pair(path: Path) -> AuthorityPair:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecoveryGateDenied(f"recovery authority file unreadable: {exc}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RecoveryGateDenied("recovery authority file is malformed") from exc
    if not isinstance(payload, dict):
        raise RecoveryGateDenied("recovery authority file is malformed")
    generation = payload.get("generation")
    authority_revision = payload.get("authority_revision")
    if (
        not isinstance(generation, str)
        or not generation
        or not isinstance(authority_revision, str)
        or not authority_revision
    ):
        raise RecoveryGateDenied("recovery authority file is missing a required field")
    return AuthorityPair(generation=generation, authority_revision=authority_revision)


def _read_reconciled_pair(dsn: str, *, timeout_seconds: float) -> AuthorityPair:
    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=max(1, int(timeout_seconds))) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT reconciled_generation::text, reconciled_authority_revision "
                    "FROM emg_identity.identity_recovery_state"
                )
                rows = cursor.fetchall()
    except RecoveryGateDenied:
        raise
    except Exception as exc:  # pragma: no cover - live PostgreSQL failure surface
        raise RecoveryGateDenied(f"recovery state unavailable: {exc}") from exc
    if len(rows) != 1:
        raise RecoveryGateDenied("recovery state row is missing or duplicated")
    generation, authority_revision = rows[0]
    if not generation or not authority_revision:
        raise RecoveryGateDenied("recovery state row is malformed")
    return AuthorityPair(generation=str(generation), authority_revision=str(authority_revision))


def evaluate_recovery_gate(*, dsn: str, authority_file: Path, timeout_seconds: float = 2.0) -> None:
    """Fail closed (raise :class:`RecoveryGateDenied`) unless the full pair
    matches (A4, A8). Both sides are re-read on every call; nothing is
    cached beyond the lifetime of this single evaluation, so loss of
    freshness cannot leave an already-evaluated result serving a later
    request (A8's "cached-for-at-most-one-request" requirement)."""

    external = _read_materialized_pair(authority_file)
    reconciled = _read_reconciled_pair(dsn, timeout_seconds=timeout_seconds)
    if external != reconciled:
        raise RecoveryGateDenied(
            "external recovery authority pair does not match the PostgreSQL " "reconciled pair"
        )
