"""PostgreSQL implementation of the application-owned atomic mutation port."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from datetime import timedelta
from typing import NoReturn
from uuid import uuid4

from emg_common_types import Classification
from emg_knowledge_graph.atomic_mutation import (
    DEFAULT_CLAIM_WAIT_SECONDS,
    DEFAULT_REPLAY_RETENTION,
    AtomicMutationOutcome,
    CommittedMutation,
    MutationExecutionRequest,
    MutationOperation,
)
from emg_knowledge_graph.commands import MutationCommand
from emg_knowledge_graph.errors import (
    IdempotencyContentionError,
    IdempotencyMismatchError,
    LegacyIdempotencyConflictError,
    MutationReplayIntegrityError,
)
from emg_knowledge_graph.results import MutationAuditIntent, MutationResult
from emg_persistence.mutations import (
    IdempotencyClaim,
    IdempotencyState,
    LedgerAppend,
    LedgerRecord,
    LedgerResource,
)
from emg_persistence.postgres import (
    ContextBoundTransactionProvider,
    PostgresMutationRepository,
)
from emg_platform_core import PrincipalKind, PrincipalRef, TenantId, WriteReceipt
from psycopg.errors import LockNotAvailable, QueryCanceled

_RESULT_SCHEMA_VERSION = 1
_RECEIPT_SCHEMA_VERSION = 1
_AUDIT_SCHEMA_VERSION = 1
FailureInjector = Callable[[str], None]


def _receipt_document(receipt: WriteReceipt) -> dict[str, object]:
    return {
        "schema_version": _RECEIPT_SCHEMA_VERSION,
        "receipt": receipt.model_dump(mode="json"),
    }


def _audit_document(intents: tuple[MutationAuditIntent, ...]) -> dict[str, object]:
    return {
        "schema_version": _AUDIT_SCHEMA_VERSION,
        "intents": [
            {
                "tenant_id": intent.tenant.value,
                "principal": intent.principal.model_dump(mode="json"),
                "idempotency_key": intent.idempotency_key,
                "action": intent.action,
                "resource_type": intent.resource_type,
                "resource_id": intent.resource_id,
                "related_resource_ids": list(intent.related_resource_ids),
                "classification": intent.classification.value,
                "reason": intent.reason,
                "revision_number": intent.revision_number,
                "content_hash": intent.content_hash,
            }
            for intent in intents
        ],
    }


def _result_document(result: MutationResult) -> dict[str, object]:
    return {
        "schema_version": _RESULT_SCHEMA_VERSION,
        "result": {
            "tenant_id": result.tenant.value,
            "principal": result.principal.model_dump(mode="json"),
            "revision_number": result.revision_number,
            "content_hash": result.content_hash,
            "node_count": result.node_count,
            "edge_count": result.edge_count,
            "revision_created": result.revision_created,
            "nodes_created": result.nodes_created,
            "edges_created": result.edges_created,
            "node_inputs_merged": result.node_inputs_merged,
            "edge_inputs_merged": result.edge_inputs_merged,
            "audit_intents": _audit_document(result.audit_intents)["intents"],
        },
    }


def _require_mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MutationReplayIntegrityError(f"{field} must be a JSON object")
    return value


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MutationReplayIntegrityError(f"{field} must be an integer")
    return value


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise MutationReplayIntegrityError(f"{field} must be a boolean")
    return value


def _deserialize_intent(value: object) -> MutationAuditIntent:
    item = _require_mapping(value, field="audit intent")
    principal = _require_mapping(item.get("principal"), field="audit principal")
    related = item.get("related_resource_ids")
    if not isinstance(related, list) or not all(isinstance(value, str) for value in related):
        raise MutationReplayIntegrityError("audit related_resource_ids must be strings")
    try:
        return MutationAuditIntent(
            tenant=TenantId.of(str(item["tenant_id"])),
            principal=PrincipalRef(
                principal_id=str(principal["principal_id"]),
                kind=PrincipalKind(str(principal["kind"])),
            ),
            idempotency_key=str(item["idempotency_key"]),
            action=str(item["action"]),
            resource_type=str(item["resource_type"]),
            resource_id=str(item["resource_id"]),
            related_resource_ids=tuple(related),
            classification=Classification(str(item["classification"])),
            reason=None if item.get("reason") is None else str(item["reason"]),
            revision_number=_require_int(item["revision_number"], field="audit revision_number"),
            content_hash=str(item["content_hash"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MutationReplayIntegrityError(f"invalid persisted audit intent: {exc}") from exc


def _deserialize_result(document: dict[str, object]) -> MutationResult:
    if document.get("schema_version") != _RESULT_SCHEMA_VERSION:
        raise MutationReplayIntegrityError("unsupported persisted MutationResult schema")
    item = _require_mapping(document.get("result"), field="mutation result")
    principal = _require_mapping(item.get("principal"), field="result principal")
    intents = item.get("audit_intents")
    if not isinstance(intents, list):
        raise MutationReplayIntegrityError("audit_intents must be a JSON array")
    try:
        return MutationResult(
            tenant=TenantId.of(str(item["tenant_id"])),
            principal=PrincipalRef(
                principal_id=str(principal["principal_id"]),
                kind=PrincipalKind(str(principal["kind"])),
            ),
            revision_number=_require_int(item["revision_number"], field="result revision_number"),
            content_hash=str(item["content_hash"]),
            node_count=_require_int(item["node_count"], field="result node_count"),
            edge_count=_require_int(item["edge_count"], field="result edge_count"),
            revision_created=_require_bool(
                item["revision_created"], field="result revision_created"
            ),
            nodes_created=_require_int(item["nodes_created"], field="result nodes_created"),
            edges_created=_require_int(item["edges_created"], field="result edges_created"),
            node_inputs_merged=_require_int(
                item["node_inputs_merged"], field="result node_inputs_merged"
            ),
            edge_inputs_merged=_require_int(
                item["edge_inputs_merged"], field="result edge_inputs_merged"
            ),
            audit_intents=tuple(_deserialize_intent(intent) for intent in intents),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MutationReplayIntegrityError(f"invalid persisted MutationResult: {exc}") from exc


def _raise_mismatch() -> NoReturn:
    raise IdempotencyMismatchError(
        "idempotency key is already associated with a different command fingerprint"
    )


class PostgresAtomicMutationExecution:
    """Atomically coordinates idempotency, GraphStore, ledger, and dispatch."""

    def __init__(
        self,
        transactions: ContextBoundTransactionProvider,
        *,
        repository_factory: type[PostgresMutationRepository] = PostgresMutationRepository,
        replay_retention: timedelta = DEFAULT_REPLAY_RETENTION,
        claim_ttl: timedelta = timedelta(minutes=2),
        claim_wait_seconds: float = DEFAULT_CLAIM_WAIT_SECONDS,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self._transactions = transactions
        self._repository_factory = repository_factory
        self._replay_retention = replay_retention
        self._claim_ttl = claim_ttl
        self._claim_wait_seconds = claim_wait_seconds
        self._failure_injector = failure_injector

    def _inject(self, point: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(point)

    @staticmethod
    def _validate_claim(claim: IdempotencyClaim, request: MutationExecutionRequest) -> None:
        if claim.state is IdempotencyState.LEGACY_SUCCEEDED:
            raise LegacyIdempotencyConflictError(
                "legacy idempotency record has no canonical command fingerprint"
            )
        if (
            claim.operation != request.operation
            or claim.fingerprint_version != request.fingerprint_version
            or claim.command_schema_version != request.command_schema_version
            or claim.command_fingerprint is None
            or not hmac.compare_digest(claim.command_fingerprint, request.command_fingerprint)
        ):
            _raise_mismatch()

    @staticmethod
    def _replay(
        repository: PostgresMutationRepository,
        claim: IdempotencyClaim,
        request: MutationExecutionRequest,
    ) -> AtomicMutationOutcome:
        PostgresAtomicMutationExecution._validate_claim(claim, request)
        if claim.state is not IdempotencyState.SUCCEEDED or claim.mutation_id is None:
            raise MutationReplayIntegrityError(
                "committed idempotency claim is unexpectedly pending"
            )
        ledger = repository.get_ledger(
            tenant_id=request.tenant.value, mutation_id=claim.mutation_id
        )
        if ledger is None:
            raise MutationReplayIntegrityError("completed claim has no mutation ledger row")
        result = _deserialize_result(ledger.mutation_result)
        PostgresAtomicMutationExecution._validate_integrity(ledger, result, request)
        return AtomicMutationOutcome(result=result, replayed=True)

    @staticmethod
    def _validate_integrity(
        ledger: LedgerRecord,
        result: MutationResult,
        request: MutationExecutionRequest,
    ) -> None:
        if (
            ledger.tenant_id != request.tenant.value
            or ledger.principal_id != str(request.principal.principal_id)
            or ledger.idempotency_key != request.idempotency_key
            or ledger.operation != request.operation
            or ledger.command_fingerprint != request.command_fingerprint
            or ledger.graph_revision != result.revision_number
            or ledger.graph_content_hash != result.content_hash
            or ledger.resource_count != len(result.audit_intents)
            or result.tenant != request.tenant
            or result.principal != request.principal
        ):
            raise MutationReplayIntegrityError(
                "mutation ledger scalars and canonical MutationResult diverge"
            )
        receipt_document = ledger.write_receipt
        if receipt_document.get("schema_version") != _RECEIPT_SCHEMA_VERSION:
            raise MutationReplayIntegrityError("unsupported persisted WriteReceipt schema")
        try:
            receipt = WriteReceipt.model_validate(receipt_document.get("receipt"))
        except ValueError as exc:
            raise MutationReplayIntegrityError(f"invalid persisted WriteReceipt: {exc}") from exc
        if (
            receipt.tenant != result.tenant
            or receipt.principal != result.principal
            or receipt.revision_number != result.revision_number
            or receipt.content_hash != result.content_hash
            or receipt.node_count != result.node_count
            or receipt.edge_count != result.edge_count
            or receipt.revision_created != result.revision_created
            or receipt.committed_at != ledger.graph_revision_at
        ):
            raise MutationReplayIntegrityError(
                "WriteReceipt, ledger scalars, and MutationResult diverge"
            )

    def lookup(self, command: MutationCommand) -> AtomicMutationOutcome | None:
        with self._transactions.transaction() as connection:
            repository = self._repository_factory(connection)
            claim = repository.lookup_claim(
                tenant_id=command.tenant.value,
                principal_id=str(command.principal.principal_id),
                idempotency_key=command.idempotency_key,
            )
            if claim is None:
                return None
            if claim.state is IdempotencyState.LEGACY_SUCCEEDED:
                raise LegacyIdempotencyConflictError(
                    "legacy idempotency record has no canonical command fingerprint"
                )
            if claim.fingerprint_version is None or claim.command_schema_version is None:
                raise MutationReplayIntegrityError(
                    "active idempotency record has no fingerprint versions"
                )
            request = MutationExecutionRequest.from_command(
                command,
                fingerprint_version=claim.fingerprint_version,
                command_schema_version=claim.command_schema_version,
            )
            self._validate_claim(claim, request)
            if claim.state is IdempotencyState.PENDING:
                raise MutationReplayIntegrityError(
                    "committed idempotency claim is unexpectedly pending"
                )
            return self._replay(repository, claim, request)

    def execute(
        self,
        request: MutationExecutionRequest,
        operation: MutationOperation,
    ) -> AtomicMutationOutcome:
        try:
            with self._transactions.outer_transaction() as connection:
                repository = self._repository_factory(connection)
                try:
                    claim = repository.acquire_claim(
                        tenant_id=request.tenant.value,
                        principal_id=str(request.principal.principal_id),
                        idempotency_key=request.idempotency_key,
                        operation=request.operation,
                        command_fingerprint=request.command_fingerprint,
                        fingerprint_version=request.fingerprint_version,
                        command_schema_version=request.command_schema_version,
                        claim_ttl=self._claim_ttl,
                        wait_timeout_seconds=self._claim_wait_seconds,
                    )
                except (LockNotAvailable, QueryCanceled) as exc:
                    raise IdempotencyContentionError(
                        "timed out acquiring or waiting for the idempotency claim"
                    ) from exc
                if not claim.acquired:
                    return self._replay(repository, claim, request)

                committed = operation()
                self._inject("after_graph_write")
                ledger = self._ledger(request, committed)
                repository.append_success(
                    claim=claim,
                    ledger=ledger,
                    replay_retention=self._replay_retention,
                )
                self._inject("after_ledger_write")
            return AtomicMutationOutcome(result=committed.result, replayed=False)
        except IdempotencyContentionError:
            raise

    @staticmethod
    def _ledger(request: MutationExecutionRequest, committed: CommittedMutation) -> LedgerAppend:
        result = committed.result
        receipt = committed.receipt
        if (
            result.tenant != request.tenant
            or result.principal != request.principal
            or receipt.tenant != request.tenant
            or receipt.principal != request.principal
            or result.revision_number != receipt.revision_number
            or result.content_hash != receipt.content_hash
            or result.node_count != receipt.node_count
            or result.edge_count != receipt.edge_count
            or result.revision_created != receipt.revision_created
            or not result.audit_intents
            or any(
                intent.tenant != request.tenant
                or intent.principal != request.principal
                or intent.idempotency_key != request.idempotency_key
                or intent.revision_number != receipt.revision_number
                or intent.content_hash != receipt.content_hash
                for intent in result.audit_intents
            )
        ):
            raise MutationReplayIntegrityError(
                "typed receipt, result, audit intents, and execution request diverge"
            )
        resources = tuple(
            LedgerResource(
                ordinal=ordinal,
                resource_type=intent.resource_type,
                resource_id=intent.resource_id,
                action=intent.action,
                classification=intent.classification.value,
                reason=intent.reason,
            )
            for ordinal, intent in enumerate(result.audit_intents)
        )
        return LedgerAppend(
            mutation_id=uuid4(),
            tenant_id=request.tenant.value,
            principal_id=str(request.principal.principal_id),
            principal_kind=request.principal.kind.value,
            idempotency_key=request.idempotency_key,
            command_fingerprint=request.command_fingerprint,
            fingerprint_version=request.fingerprint_version,
            command_schema_version=request.command_schema_version,
            operation=request.operation,
            status="succeeded" if receipt.revision_created else "no_op",
            graph_revision=receipt.revision_number,
            graph_content_hash=receipt.content_hash,
            graph_revision_at=receipt.committed_at,
            write_receipt=_receipt_document(receipt),
            mutation_result=_result_document(result),
            audit_intents=_audit_document(result.audit_intents),
            resources=resources,
        )
