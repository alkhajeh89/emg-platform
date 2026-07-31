"""Refresh-token rotation state and persistence adapters."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
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
    """Durable adapter; raw token and family identifiers are never stored."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def register(self, family_id: str, token_id: str, expires_at: datetime) -> None:
        import psycopg

        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO identity_refresh_token_families (family_hash)
                VALUES (%s)
                ON CONFLICT (family_hash) DO NOTHING
                """,
                (_identifier_hash(family_id),),
            )
            cursor.execute(
                """
                INSERT INTO identity_refresh_tokens
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

        family_hash = _identifier_hash(family_id)
        current_hash = _identifier_hash(current_token_id)
        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revoked_at
                FROM identity_refresh_token_families
                WHERE family_hash = %s
                FOR UPDATE
                """,
                (family_hash,),
            )
            family = cursor.fetchone()
            cursor.execute(
                """
                SELECT status, expires_at
                FROM identity_refresh_tokens
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
                    UPDATE identity_refresh_token_families
                    SET revoked_at = clock_timestamp()
                    WHERE family_hash = %s
                    """,
                    (family_hash,),
                )
                cursor.execute(
                    """
                    UPDATE identity_refresh_tokens
                    SET status = 'revoked'
                    WHERE family_hash = %s
                    """,
                    (family_hash,),
                )
                return False
            cursor.execute(
                """
                UPDATE identity_refresh_tokens
                SET status = 'rotated', rotated_at = clock_timestamp()
                WHERE token_hash = %s
                """,
                (current_hash,),
            )
            cursor.execute(
                """
                INSERT INTO identity_refresh_tokens
                    (token_hash, family_hash, status, expires_at)
                VALUES (%s, %s, 'active', %s)
                """,
                (_identifier_hash(next_token_id), family_hash, next_expires_at),
            )
            return True

    def family_is_active(self, family_id: str) -> bool:
        import psycopg

        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revoked_at IS NULL
                FROM identity_refresh_token_families
                WHERE family_hash = %s
                """,
                (_identifier_hash(family_id),),
            )
            row = cursor.fetchone()
            return row is not None and bool(row[0])
