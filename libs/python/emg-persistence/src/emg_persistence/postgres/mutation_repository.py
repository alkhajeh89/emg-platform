"""PostgreSQL claim and immutable mutation-ledger persistence (ADR-030)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from ..mutations import (
    DispatchBacklog,
    DispatchWorkItem,
    IdempotencyClaim,
    IdempotencyState,
    LedgerAppend,
    LedgerRecord,
    LsnPosition,
)

if TYPE_CHECKING:
    from psycopg import Connection

_CLAIM_COLUMNS = (
    "tenant_id, principal_id, idempotency_key, operation_type, state, requested_at, "
    "expires_at, command_fingerprint, fingerprint_version, "
    "command_schema_version, mutation_id, mutation_result_json"
)
_INSERT_CLAIM = (
    "WITH timing AS (SELECT clock_timestamp() AS cutoff) "
    "INSERT INTO mutation_idempotency "
    "(tenant_id, principal_id, idempotency_key, operation_type, state, "
    "command_fingerprint, fingerprint_version, command_schema_version, "
    "requested_at, expires_at) "
    "VALUES (%(tenant)s, %(principal)s, %(key)s, %(operation)s, 'pending', "
    "%(fingerprint)s, %(fingerprint_version)s, %(command_schema_version)s, "
    "(SELECT cutoff FROM timing), (SELECT cutoff FROM timing) + %(claim_ttl)s) "
    "ON CONFLICT (tenant_id, principal_id, idempotency_key) DO NOTHING "
    f"RETURNING {_CLAIM_COLUMNS}"
)
_LOCK_CLAIM = (
    f"SELECT {_CLAIM_COLUMNS}, clock_timestamp() "
    "FROM mutation_idempotency "
    "WHERE tenant_id = %(tenant)s AND principal_id = %(principal)s "
    "AND idempotency_key = %(key)s FOR UPDATE"
)
_DELETE_CLAIM = (
    "DELETE FROM mutation_idempotency "
    "WHERE tenant_id = %(tenant)s AND principal_id = %(principal)s "
    "AND idempotency_key = %(key)s"
)
_LOOKUP_CLAIM = (
    f"SELECT {_CLAIM_COLUMNS}, clock_timestamp() "
    "FROM mutation_idempotency "
    "WHERE tenant_id = %(tenant)s AND principal_id = %(principal)s "
    "AND idempotency_key = %(key)s"
)
_INSERT_LEDGER = (
    "WITH timing AS (SELECT clock_timestamp() AS completed) "
    "INSERT INTO mutation_ledger "
    "(mutation_id, tenant_id, principal_id, principal_kind, idempotency_key, "
    "command_fingerprint, fingerprint_version, command_schema_version, operation, "
    "status, graph_revision, graph_content_hash, write_receipt, mutation_result, "
    "audit_intents, resource_count, requested_at, ledger_completed_at, "
    "graph_revision_at, replay_expires_at) "
    "VALUES (%(mutation_id)s, %(tenant)s, %(principal)s, %(principal_kind)s, %(key)s, "
    "%(fingerprint)s, %(fingerprint_version)s, %(command_schema_version)s, "
    "%(operation)s, %(status)s, %(revision)s, %(content_hash)s, %(receipt)s, "
    "%(result)s, %(audit)s, %(resource_count)s, %(requested_at)s, "
    "(SELECT completed FROM timing), %(graph_revision_at)s, "
    "(SELECT completed FROM timing) + %(replay_ttl)s) "
    "RETURNING ledger_completed_at, replay_expires_at"
)
_INSERT_RESOURCE = (
    "INSERT INTO mutation_ledger_resource "
    "(mutation_id, ordinal, resource_type, resource_id, action, classification, reason) "
    "VALUES (%(mutation_id)s, %(ordinal)s, %(resource_type)s, %(resource_id)s, "
    "%(action)s, %(classification)s, %(reason)s)"
)
_INSERT_DISPATCH = (
    "INSERT INTO mutation_dispatch "
    "(mutation_id, tenant_id, channel, available_at) "
    "VALUES (%(mutation_id)s, %(tenant)s, %(channel)s, clock_timestamp())"
)
_COMPLETE_CLAIM = (
    "UPDATE mutation_idempotency SET state = 'succeeded', mutation_id = %(mutation_id)s, "
    "revision_number = %(revision)s, content_hash = %(content_hash)s, "
    "receipt_json = %(receipt)s, mutation_result_json = %(result)s, "
    "expires_at = %(replay_expires_at)s "
    "WHERE tenant_id = %(tenant)s AND principal_id = %(principal)s "
    "AND idempotency_key = %(key)s AND state = 'pending' "
    "AND command_fingerprint = %(fingerprint)s"
)
_SELECT_LEDGER = (
    "SELECT mutation_id, tenant_id, principal_id, principal_kind, idempotency_key, "
    "command_fingerprint, fingerprint_version, command_schema_version, operation, "
    "status, graph_revision, graph_content_hash, write_receipt, mutation_result, "
    "audit_intents, requested_at, ledger_completed_at, graph_revision_at, "
    "replay_expires_at, resource_count FROM mutation_ledger "
    "WHERE tenant_id = %(tenant)s AND mutation_id = %(id)s"
)
_CLAIM_DISPATCH = (
    "WITH work AS ("
    "SELECT mutation_id, channel FROM mutation_dispatch "
    "WHERE tenant_id = %(tenant)s AND channel = %(channel)s "
    "AND delivered_at IS NULL "
    "AND available_at <= clock_timestamp() "
    "AND attempt_count < %(max_attempts)s "
    "AND (claim_expires_at IS NULL OR claim_expires_at <= clock_timestamp()) "
    "ORDER BY available_at, mutation_id "
    "FOR UPDATE SKIP LOCKED LIMIT %(limit)s"
    ") UPDATE mutation_dispatch AS dispatch SET "
    "claim_owner = %(worker)s, "
    "claim_expires_at = clock_timestamp() + %(lease)s, "
    "attempt_count = dispatch.attempt_count + 1 "
    "FROM work WHERE dispatch.mutation_id = work.mutation_id "
    "AND dispatch.channel = work.channel "
    "RETURNING dispatch.mutation_id, dispatch.tenant_id, dispatch.channel, "
    "dispatch.available_at, dispatch.attempt_count, dispatch.claim_owner, "
    "dispatch.claim_expires_at, dispatch.source_system_id, "
    "dispatch.source_timeline, dispatch.source_commit_lsn::text, "
    "dispatch.source_tx_index"
)
_SET_DISPATCH_SOURCE = (
    "UPDATE mutation_dispatch SET source_system_id = %(system)s, "
    "source_timeline = %(timeline)s, source_commit_lsn = %(lsn)s::pg_lsn, "
    "source_tx_index = %(index)s WHERE tenant_id = %(tenant)s "
    "AND mutation_id = %(mutation_id)s "
    "AND channel = %(channel)s"
)
_COMPLETE_DISPATCH = (
    "UPDATE mutation_dispatch SET delivered_at = clock_timestamp(), "
    "claim_owner = NULL, claim_expires_at = NULL "
    "WHERE tenant_id = %(tenant)s AND mutation_id = %(mutation_id)s "
    "AND channel = %(channel)s "
    "AND claim_owner = %(worker)s AND delivered_at IS NULL"
)
_RESCHEDULE_DISPATCH = (
    "UPDATE mutation_dispatch SET available_at = clock_timestamp() + %(delay)s, "
    "claim_owner = NULL, claim_expires_at = NULL "
    "WHERE tenant_id = %(tenant)s AND mutation_id = %(mutation_id)s "
    "AND channel = %(channel)s AND claim_owner = %(worker)s "
    "AND delivered_at IS NULL"
)
_EXHAUST_DISPATCH = (
    "UPDATE mutation_dispatch SET attempt_count = %(max_attempts)s, "
    "claim_owner = NULL, claim_expires_at = NULL "
    "WHERE tenant_id = %(tenant)s AND mutation_id = %(mutation_id)s "
    "AND channel = %(channel)s AND claim_owner = %(worker)s "
    "AND delivered_at IS NULL"
)
_DISPATCH_BACKLOG = (
    "SELECT COUNT(*) FILTER (WHERE delivered_at IS NULL), "
    "COUNT(*) FILTER (WHERE delivered_at IS NULL AND claim_owner IS NOT NULL "
    "AND claim_expires_at > clock_timestamp()), "
    "COUNT(*) FILTER (WHERE delivered_at IS NULL AND attempt_count >= %(max_attempts)s), "
    "COALESCE(EXTRACT(EPOCH FROM (clock_timestamp() - MIN(available_at) "
    "FILTER (WHERE delivered_at IS NULL))), 0) "
    "FROM mutation_dispatch WHERE tenant_id = %(tenant)s AND channel = %(channel)s"
)


class PostgresMutationRepository:
    """SQL-only adapter; application result mapping remains above this layer."""

    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection

    @staticmethod
    def _params(
        *,
        tenant_id: str,
        principal_id: str,
        idempotency_key: str,
        operation: str,
        command_fingerprint: str,
        fingerprint_version: int,
        command_schema_version: int,
        claim_ttl: timedelta,
    ) -> dict[str, object]:
        return {
            "tenant": tenant_id,
            "principal": principal_id,
            "key": idempotency_key,
            "operation": operation,
            "fingerprint": command_fingerprint,
            "fingerprint_version": fingerprint_version,
            "command_schema_version": command_schema_version,
            "claim_ttl": claim_ttl,
        }

    @staticmethod
    def _claim(row: tuple[Any, ...], *, acquired: bool) -> IdempotencyClaim:
        return IdempotencyClaim(
            tenant_id=row[0],
            principal_id=row[1],
            idempotency_key=row[2],
            operation=row[3],
            state=IdempotencyState(row[4]),
            requested_at=row[5],
            expires_at=row[6],
            command_fingerprint=row[7],
            fingerprint_version=row[8],
            command_schema_version=row[9],
            mutation_id=row[10],
            mutation_result=row[11],
            acquired=acquired,
        )

    def acquire_claim(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        idempotency_key: str,
        operation: str,
        command_fingerprint: str,
        fingerprint_version: int,
        command_schema_version: int,
        claim_ttl: timedelta,
        wait_timeout_seconds: float,
    ) -> IdempotencyClaim:  # pragma: no cover - live DB
        params = self._params(
            tenant_id=tenant_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            operation=operation,
            command_fingerprint=command_fingerprint,
            fingerprint_version=fingerprint_version,
            command_schema_version=command_schema_version,
            claim_ttl=claim_ttl,
        )
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('lock_timeout', %(timeout)s, true)",
                {"timeout": f"{max(1, round(wait_timeout_seconds * 1000))}ms"},
            )
            cursor.execute(
                "SELECT set_config('statement_timeout', %(timeout)s, true)",
                {"timeout": f"{max(1, round(wait_timeout_seconds * 1000))}ms"},
            )
            cursor.execute(_INSERT_CLAIM, params)
            row = cursor.fetchone()
            if row is not None:
                cursor.execute("SELECT set_config('lock_timeout', '0', true)")
                cursor.execute("SELECT set_config('statement_timeout', '0', true)")
                return self._claim(row, acquired=True)
            cursor.execute(_LOCK_CLAIM, params)
            locked = cursor.fetchone()
            cursor.execute("SELECT set_config('lock_timeout', '0', true)")
            cursor.execute("SELECT set_config('statement_timeout', '0', true)")
            if locked is None:
                raise RuntimeError("idempotency claim disappeared while locked")
            claim = self._claim(locked[:-1], acquired=False)
            database_now = locked[-1]
            expired = claim.expires_at <= database_now
            if not expired:
                return claim
            cursor.execute(_DELETE_CLAIM, params)
            cursor.execute(_INSERT_CLAIM, params)
            replacement = cursor.fetchone()
            if replacement is None:
                raise RuntimeError("expired idempotency claim could not be replaced")
            return self._claim(replacement, acquired=True)

    def lookup_claim(
        self, *, tenant_id: str, principal_id: str, idempotency_key: str
    ) -> IdempotencyClaim | None:  # pragma: no cover - live DB
        params = {
            "tenant": tenant_id,
            "principal": principal_id,
            "key": idempotency_key,
        }
        with self._connection.cursor() as cursor:
            cursor.execute(_LOOKUP_CLAIM, params)
            row = cursor.fetchone()
        if row is None:
            return None
        claim = self._claim(row[:-1], acquired=False)
        database_now = row[-1]
        if claim.expires_at <= database_now:
            return None
        return claim

    def append_success(
        self,
        *,
        claim: IdempotencyClaim,
        ledger: LedgerAppend,
        replay_retention: timedelta,
    ) -> LedgerRecord:  # pragma: no cover - live DB
        from psycopg.types.json import Jsonb

        params: dict[str, object] = {
            "mutation_id": ledger.mutation_id,
            "tenant": ledger.tenant_id,
            "principal": ledger.principal_id,
            "principal_kind": ledger.principal_kind,
            "key": ledger.idempotency_key,
            "fingerprint": ledger.command_fingerprint,
            "fingerprint_version": ledger.fingerprint_version,
            "command_schema_version": ledger.command_schema_version,
            "operation": ledger.operation,
            "status": ledger.status,
            "revision": ledger.graph_revision,
            "content_hash": ledger.graph_content_hash,
            "receipt": Jsonb(ledger.write_receipt),
            "result": Jsonb(ledger.mutation_result),
            "audit": Jsonb(ledger.audit_intents),
            "resource_count": len(ledger.resources),
            "requested_at": claim.requested_at,
            "graph_revision_at": ledger.graph_revision_at,
            "replay_ttl": replay_retention,
        }
        with self._connection.cursor() as cursor:
            cursor.execute(_INSERT_LEDGER, params)
            completion = cursor.fetchone()
            if completion is None:
                raise RuntimeError("mutation ledger insert did not return completion metadata")
            for resource in ledger.resources:
                cursor.execute(
                    _INSERT_RESOURCE,
                    {
                        "mutation_id": ledger.mutation_id,
                        "ordinal": resource.ordinal,
                        "resource_type": resource.resource_type,
                        "resource_id": resource.resource_id,
                        "action": resource.action,
                        "classification": resource.classification,
                        "reason": resource.reason,
                    },
                )
            for channel in ("audit", "event"):
                cursor.execute(
                    _INSERT_DISPATCH,
                    {
                        "mutation_id": ledger.mutation_id,
                        "tenant": ledger.tenant_id,
                        "channel": channel,
                    },
                )
            params["replay_expires_at"] = completion[1]
            cursor.execute(_COMPLETE_CLAIM, params)
            if cursor.rowcount != 1:
                raise RuntimeError("pending idempotency claim could not be completed")
        return LedgerRecord(
            mutation_id=ledger.mutation_id,
            tenant_id=ledger.tenant_id,
            principal_id=ledger.principal_id,
            principal_kind=ledger.principal_kind,
            idempotency_key=ledger.idempotency_key,
            command_fingerprint=ledger.command_fingerprint,
            fingerprint_version=ledger.fingerprint_version,
            command_schema_version=ledger.command_schema_version,
            operation=ledger.operation,
            status=ledger.status,
            graph_revision=ledger.graph_revision,
            graph_content_hash=ledger.graph_content_hash,
            write_receipt=ledger.write_receipt,
            mutation_result=ledger.mutation_result,
            audit_intents=ledger.audit_intents,
            requested_at=claim.requested_at,
            ledger_completed_at=completion[0],
            graph_revision_at=ledger.graph_revision_at,
            replay_expires_at=completion[1],
            resource_count=len(ledger.resources),
        )

    def get_ledger(
        self, *, tenant_id: str, mutation_id: object
    ) -> LedgerRecord | None:  # pragma: no cover
        with self._connection.cursor() as cursor:
            cursor.execute(_SELECT_LEDGER, {"tenant": tenant_id, "id": mutation_id})
            row = cursor.fetchone()
        if row is None:
            return None
        return LedgerRecord(
            mutation_id=row[0],
            tenant_id=row[1],
            principal_id=row[2],
            principal_kind=row[3],
            idempotency_key=row[4],
            command_fingerprint=row[5],
            fingerprint_version=row[6],
            command_schema_version=row[7],
            operation=row[8],
            status=row[9],
            graph_revision=row[10],
            graph_content_hash=row[11],
            write_receipt=row[12],
            mutation_result=row[13],
            audit_intents=row[14],
            requested_at=row[15],
            ledger_completed_at=row[16],
            graph_revision_at=row[17],
            replay_expires_at=row[18],
            resource_count=row[19],
        )

    def claim_dispatch(
        self,
        *,
        tenant_id: str,
        channel: str,
        worker: str,
        limit: int,
        max_attempts: int,
        lease: timedelta,
    ) -> tuple[DispatchWorkItem, ...]:  # pragma: no cover - live DB
        if channel not in {"audit", "event"}:
            raise ValueError(f"unsupported mutation dispatch channel: {channel!r}")
        if limit < 1:
            raise ValueError("dispatch limit must be positive")
        if max_attempts < 1:
            raise ValueError("dispatch max_attempts must be positive")
        with self._connection.cursor() as cursor:
            cursor.execute(
                _CLAIM_DISPATCH,
                {
                    "channel": channel,
                    "tenant": tenant_id,
                    "worker": worker,
                    "limit": limit,
                    "max_attempts": max_attempts,
                    "lease": lease,
                },
            )
            rows = cursor.fetchall()
        return tuple(self._dispatch_item(row) for row in rows)

    @staticmethod
    def _dispatch_item(row: tuple[Any, ...]) -> DispatchWorkItem:
        position = None
        if row[7] is not None:
            position = LsnPosition(
                system_id=row[7],
                timeline=row[8],
                commit_lsn=row[9],
                transaction_index=row[10],
            )
        return DispatchWorkItem(
            mutation_id=row[0],
            tenant_id=row[1],
            channel=row[2],
            available_at=row[3],
            attempt_count=row[4],
            claim_owner=row[5],
            claim_expires_at=row[6],
            source_position=position,
        )

    def set_dispatch_source_position(
        self,
        *,
        tenant_id: str,
        mutation_id: object,
        channel: str,
        position: LsnPosition,
    ) -> None:  # pragma: no cover - live DB
        with self._connection.cursor() as cursor:
            cursor.execute(
                _SET_DISPATCH_SOURCE,
                {
                    "mutation_id": mutation_id,
                    "tenant": tenant_id,
                    "channel": channel,
                    "system": position.system_id,
                    "timeline": position.timeline,
                    "lsn": position.commit_lsn,
                    "index": position.transaction_index,
                },
            )
            if cursor.rowcount != 1:
                raise RuntimeError("mutation dispatch row was not found")

    def complete_dispatch(
        self, *, tenant_id: str, mutation_id: object, channel: str, worker: str
    ) -> None:  # pragma: no cover - live DB
        with self._connection.cursor() as cursor:
            cursor.execute(
                _COMPLETE_DISPATCH,
                {
                    "mutation_id": mutation_id,
                    "tenant": tenant_id,
                    "channel": channel,
                    "worker": worker,
                },
            )
            if cursor.rowcount != 1:
                raise RuntimeError("mutation dispatch claim was lost")

    def reschedule_dispatch(
        self,
        *,
        tenant_id: str,
        mutation_id: object,
        channel: str,
        worker: str,
        delay: timedelta,
    ) -> None:  # pragma: no cover - live DB
        if delay < timedelta(0):
            raise ValueError("dispatch retry delay must not be negative")
        with self._connection.cursor() as cursor:
            cursor.execute(
                _RESCHEDULE_DISPATCH,
                {
                    "tenant": tenant_id,
                    "mutation_id": mutation_id,
                    "channel": channel,
                    "worker": worker,
                    "delay": delay,
                },
            )
            if cursor.rowcount != 1:
                raise RuntimeError("mutation dispatch claim was lost")

    def exhaust_dispatch(
        self,
        *,
        tenant_id: str,
        mutation_id: object,
        channel: str,
        worker: str,
        max_attempts: int,
    ) -> None:  # pragma: no cover - live DB
        if max_attempts < 1:
            raise ValueError("dispatch max_attempts must be positive")
        with self._connection.cursor() as cursor:
            cursor.execute(
                _EXHAUST_DISPATCH,
                {
                    "tenant": tenant_id,
                    "mutation_id": mutation_id,
                    "channel": channel,
                    "worker": worker,
                    "max_attempts": max_attempts,
                },
            )
            if cursor.rowcount != 1:
                raise RuntimeError("mutation dispatch claim was lost")

    def dispatch_backlog(
        self, *, tenant_id: str, channel: str, max_attempts: int
    ) -> DispatchBacklog:  # pragma: no cover - live DB
        if channel not in {"audit", "event"}:
            raise ValueError(f"unsupported mutation dispatch channel: {channel!r}")
        if max_attempts < 1:
            raise ValueError("dispatch max_attempts must be positive")
        with self._connection.cursor() as cursor:
            cursor.execute(
                _DISPATCH_BACKLOG,
                {"tenant": tenant_id, "channel": channel, "max_attempts": max_attempts},
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("mutation dispatch backlog query returned no row")
        return DispatchBacklog(
            pending_count=row[0],
            in_flight_count=row[1],
            exhausted_count=row[2],
            oldest_pending_age_seconds=max(0.0, float(row[3])),
        )
