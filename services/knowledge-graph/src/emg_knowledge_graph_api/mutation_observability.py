"""API-local ADR-027 Stage 4 Phase 4B mutation observability emission."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from emg_errors import EMGError, PermissionDeniedError
from emg_telemetry import get_logger
from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from .errors import error_status

_log = get_logger("knowledge_graph.mutations")


class MutationOperation(str, Enum):
    """The fixed ADR-027 Revision 5 mutation-route vocabulary."""

    CREATE_ENTITY = "create_entity"
    REPLACE_ENTITY = "replace_entity"
    REPLACE_RELATIONSHIP = "replace_relationship"
    CLOSE_RELATIONSHIP = "close_relationship"
    MERGE_ENTITIES = "merge_entities"


class MutationOutcome(str, Enum):
    """The bounded Phase 4B mutation outcome vocabulary."""

    SUCCESS = "success"
    REJECTED = "rejected"
    FAILURE = "failure"


class MutationMetric(str, Enum):
    """The complete Phase 4B metric inventory."""

    REQUESTS = "mutation_requests_total"
    LATENCY = "mutation_latency_seconds"
    IDEMPOTENCY_HITS = "idempotency_hits_total"
    AUTHORIZATION_DENIALS = "authorization_denials_total"


_ROUTE_OPERATIONS: dict[str, MutationOperation] = {
    operation.value: operation for operation in MutationOperation
}


def _outcome_for_status(status_code: int) -> MutationOutcome:
    if status_code < 400:
        return MutationOutcome.SUCCESS
    if status_code < 500:
        return MutationOutcome.REJECTED
    return MutationOutcome.FAILURE


def _elapsed_seconds(started_at: float, *, clock: Callable[[], float]) -> float:
    """Return a monotonic non-negative observation using an injectable clock."""

    return max(0.0, clock() - started_at)


def _emit_event(
    document: dict[str, object],
    *,
    action: str,
    outcome: MutationOutcome,
) -> None:
    """Emit one safe structured event without affecting request behavior."""

    try:
        _log.info(
            json.dumps(document, sort_keys=True, separators=(",", ":")),
            extra={
                "actor": "mutation-boundary",
                "module": "knowledge-graph",
                "action": action,
                "outcome": outcome.value,
            },
        )
    except Exception:
        # Observability is deliberately outside mutation correctness and must
        # never change the HTTP, authorization, or atomic-execution outcome.
        return


def _emit_metric(
    metric: MutationMetric,
    *,
    metric_type: str,
    value: int | float,
    operation: MutationOperation,
    outcome: MutationOutcome,
) -> None:
    _emit_event(
        {
            "event": "mutation_metric",
            "metric_name": metric.value,
            "metric_type": metric_type,
            "metric_value": value,
            "operation": operation.value,
            "outcome": outcome.value,
        },
        action="mutation_metric",
        outcome=outcome,
    )


def _emit_request_completion(
    *,
    operation: MutationOperation,
    outcome: MutationOutcome,
    status_code: int,
    duration_seconds: float,
) -> None:
    _emit_event(
        {
            "event": "mutation_request_completed",
            "operation": operation.value,
            "outcome": outcome.value,
            "status_code": status_code,
            "duration_seconds": duration_seconds,
        },
        action="mutation_request",
        outcome=outcome,
    )


def record_idempotency_hit(
    operation: MutationOperation,
    *,
    replayed: bool,
) -> None:
    """Emit only for the existing authorized application replay signal."""

    if replayed is True:
        _emit_metric(
            MutationMetric.IDEMPOTENCY_HITS,
            metric_type="counter",
            value=1,
            operation=operation,
            outcome=MutationOutcome.SUCCESS,
        )


class MutationObservedRoute(APIRoute):
    """Observe exactly the five matched mutation routes at the HTTP boundary."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        route_handler = super().get_route_handler()
        try:
            operation = _ROUTE_OPERATIONS[self.name]
        except KeyError as exc:
            raise RuntimeError(f"unregistered observed mutation route {self.name!r}") from exc

        async def observed_route_handler(request: Request) -> Response:
            started_at = time.perf_counter()
            status_code = 500
            outcome = MutationOutcome.FAILURE
            try:
                response: Response = await route_handler(request)
                status_code = response.status_code
                outcome = _outcome_for_status(status_code)
                return response
            except PermissionDeniedError as exc:
                status_code = error_status(exc)
                outcome = MutationOutcome.REJECTED
                _emit_metric(
                    MutationMetric.AUTHORIZATION_DENIALS,
                    metric_type="counter",
                    value=1,
                    operation=operation,
                    outcome=outcome,
                )
                raise
            except EMGError as exc:
                status_code = error_status(exc)
                outcome = _outcome_for_status(status_code)
                raise
            except RequestValidationError:
                status_code = 422
                outcome = MutationOutcome.REJECTED
                raise
            except HTTPException as exc:
                status_code = exc.status_code
                outcome = _outcome_for_status(status_code)
                raise
            finally:
                duration_seconds = _elapsed_seconds(
                    started_at,
                    clock=time.perf_counter,
                )
                _emit_metric(
                    MutationMetric.REQUESTS,
                    metric_type="counter",
                    value=1,
                    operation=operation,
                    outcome=outcome,
                )
                _emit_metric(
                    MutationMetric.LATENCY,
                    metric_type="histogram_observation",
                    value=duration_seconds,
                    operation=operation,
                    outcome=outcome,
                )
                _emit_request_completion(
                    operation=operation,
                    outcome=outcome,
                    status_code=status_code,
                    duration_seconds=duration_seconds,
                )

        return observed_route_handler


__all__ = [
    "MutationMetric",
    "MutationObservedRoute",
    "MutationOperation",
    "MutationOutcome",
    "record_idempotency_hit",
]
