"""Refresh-token rotation state and persistence adapters."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


def _identifier_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RefreshTokenStore(Protocol):
    """Application-owned state required for single-use refresh tokens."""

    def register(self, family_id: str, token_id: str, expires_at: datetime) -> None: ...

    def rotate(
        self,
        family_id: str,
        current_token_id: str,
        next_token_id: str,
        next_expires_at: datetime,
    ) -> bool:
        """Consume current and register next; revoke the family on reuse."""
        ...

    def family_is_active(self, family_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class _TokenRecord:
    family_hash: str
    status: str
    expires_at: datetime


class InMemoryRefreshTokenStore:
    """Thread-safe development/test adapter with production-equivalent semantics."""

    def __init__(self) -> None:
        self._tokens: dict[str, _TokenRecord] = {}
        self._revoked_families: set[str] = set()
        self._lock = threading.Lock()

    def register(self, family_id: str, token_id: str, expires_at: datetime) -> None:
        family_hash = _identifier_hash(family_id)
        token_hash = _identifier_hash(token_id)
        with self._lock:
            self._tokens[token_hash] = _TokenRecord(family_hash, "active", expires_at)

    def rotate(
        self,
        family_id: str,
        current_token_id: str,
        next_token_id: str,
        next_expires_at: datetime,
    ) -> bool:
        family_hash = _identifier_hash(family_id)
        current_hash = _identifier_hash(current_token_id)
        next_hash = _identifier_hash(next_token_id)
        now = datetime.now(timezone.utc)
        with self._lock:
            current = self._tokens.get(current_hash)
            valid = (
                current is not None
                and current.family_hash == family_hash
                and current.status == "active"
                and current.expires_at > now
                and family_hash not in self._revoked_families
            )
            if not valid:
                self._revoked_families.add(family_hash)
                self._revoke_family(family_hash)
                return False
            assert current is not None
            self._tokens[current_hash] = _TokenRecord(family_hash, "rotated", current.expires_at)
            self._tokens[next_hash] = _TokenRecord(family_hash, "active", next_expires_at)
            return True

    def family_is_active(self, family_id: str) -> bool:
        family_hash = _identifier_hash(family_id)
        with self._lock:
            return family_hash not in self._revoked_families

    def _revoke_family(self, family_hash: str) -> None:
        for token_hash, record in tuple(self._tokens.items()):
            if record.family_hash == family_hash:
                self._tokens[token_hash] = _TokenRecord(family_hash, "revoked", record.expires_at)


class PostgresRefreshTokenStore:
    """Durable adapter; raw token and family identifiers are never stored.

    ``recovery_authority_file``, when supplied, enforces the ADR-043
    Amendment 1 A8 request-time recovery gate before every operation: the
    externally materialized (generation, authority_revision) pair must equal
    PostgreSQL's reconciled pair, re-checked on every call so that a pod
    that becomes stale after readiness (e.g. the external authority rotates
    mid-flight) rejects further operations fail closed rather than relying
    solely on Kubernetes readiness propagation (A8).
    """

    def __init__(
        self,
        dsn: str,
        *,
        recovery_authority_file: Path | None = None,
        recovery_gate_timeout_seconds: float = 2.0,
    ) -> None:
        self._dsn = dsn
        self._recovery_authority_file = recovery_authority_file
        self._recovery_gate_timeout_seconds = recovery_gate_timeout_seconds

    def _enforce_recovery_gate(self) -> None:
        if self._recovery_authority_file is None:
            return
        from .recovery_gate import evaluate_recovery_gate

        evaluate_recovery_gate(
            dsn=self._dsn,
            authority_file=self._recovery_authority_file,
            timeout_seconds=self._recovery_gate_timeout_seconds,
        )

    def register(self, family_id: str, token_id: str, expires_at: datetime) -> None:
        import psycopg

        self._enforce_recovery_gate()
        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO emg_identity.identity_refresh_token_families (family_hash)
                VALUES (%s)
                ON CONFLICT (family_hash) DO NOTHING
                """,
                (_identifier_hash(family_id),),
            )
            cursor.execute(
                """
                INSERT INTO emg_identity.identity_refresh_tokens
                    (token_hash, family_hash, status, expires_at)
                VALUES (%s, %s, 'active', %s)
                """,
                (_identifier_hash(token_id), _identifier_hash(family_id), expires_at),
            )

    def rotate(
        self,
        family_id: str,
        current_token_id: str,
        next_token_id: str,
        next_expires_at: datetime,
    ) -> bool:
        import psycopg

        self._enforce_recovery_gate()
        family_hash = _identifier_hash(family_id)
        current_hash = _identifier_hash(current_token_id)
        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revoked_at
                FROM emg_identity.identity_refresh_token_families
                WHERE family_hash = %s
                FOR UPDATE
                """,
                (family_hash,),
            )
            family = cursor.fetchone()
            cursor.execute(
                """
                SELECT status, expires_at
                FROM emg_identity.identity_refresh_tokens
                WHERE token_hash = %s AND family_hash = %s
                FOR UPDATE
                """,
                (current_hash, family_hash),
            )
            token = cursor.fetchone()
            valid = (
                family is not None
                and family[0] is None
                and token is not None
                and token[0] == "active"
                and token[1] > datetime.now(timezone.utc)
            )
            if not valid:
                cursor.execute(
                    """
                    UPDATE emg_identity.identity_refresh_token_families
                    SET revoked_at = clock_timestamp()
                    WHERE family_hash = %s
                    """,
                    (family_hash,),
                )
                cursor.execute(
                    """
                    UPDATE emg_identity.identity_refresh_tokens
                    SET status = 'revoked'
                    WHERE family_hash = %s
                    """,
                    (family_hash,),
                )
                return False
            cursor.execute(
                """
                UPDATE emg_identity.identity_refresh_tokens
                SET status = 'rotated', rotated_at = clock_timestamp()
                WHERE token_hash = %s
                """,
                (current_hash,),
            )
            cursor.execute(
                """
                INSERT INTO emg_identity.identity_refresh_tokens
                    (token_hash, family_hash, status, expires_at)
                VALUES (%s, %s, 'active', %s)
                """,
                (_identifier_hash(next_token_id), family_hash, next_expires_at),
            )
            return True

    def family_is_active(self, family_id: str) -> bool:
        import psycopg

        self._enforce_recovery_gate()
        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revoked_at IS NULL
                FROM emg_identity.identity_refresh_token_families
                WHERE family_hash = %s
                """,
                (_identifier_hash(family_id),),
            )
            row = cursor.fetchone()
            return row is not None and bool(row[0])
