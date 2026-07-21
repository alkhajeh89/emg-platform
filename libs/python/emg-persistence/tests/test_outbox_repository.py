"""Unit coverage for the transactional outbox model and repository."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, cast
from uuid import uuid4

import pytest
from _outbox_helpers import make_outbox_event
from emg_persistence.outbox import OutboxEvent, OutboxRepository
from emg_persistence.postgres.outbox_repository import PostgresOutboxRepository
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import ValidationError


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: tuple[str, dict[str, Any]] | None = None

    def execute(self, query: str, params: dict[str, Any]) -> None:
        self.executed = (query, params)

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = _FakeCursor()
        self.commit_calls = 0

    def cursor(self) -> AbstractContextManager[_FakeCursor]:
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_calls += 1


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("revision_number", 0),
        ("content_hash", "not-a-sha256"),
        ("event_type", ""),
        ("schema_version", 0),
        ("idempotency_key", ""),
    ),
)
def test_outbox_event_rejects_invalid_fields(field: str, value: object) -> None:
    data = make_outbox_event(event_id=uuid4()).model_dump()
    data[field] = value

    with pytest.raises(ValidationError):
        OutboxEvent.model_validate(data)


def test_outbox_event_is_frozen_and_rejects_extra_fields() -> None:
    event = make_outbox_event(event_id=uuid4())

    with pytest.raises(ValidationError):
        event.revision_number = 2  # type: ignore[misc]
    with pytest.raises(ValidationError):
        OutboxEvent.model_validate({**event.model_dump(), "unexpected": True})


def test_postgres_repository_conforms_to_contract() -> None:
    repository = PostgresOutboxRepository(cast(Connection[Any], _FakeConnection()))

    assert isinstance(repository, OutboxRepository)


def test_outbox_append_builds_complete_parameterized_insert() -> None:
    connection = _FakeConnection()
    repository = PostgresOutboxRepository(cast(Connection[Any], connection))
    event = make_outbox_event(event_id=uuid4(), revision_number=7)

    repository.append(event)

    assert connection.cursor_instance.executed is not None
    query, params = connection.cursor_instance.executed
    assert "%s" not in query
    assert "%(event_id)s" in query
    payload = params.pop("payload")
    assert isinstance(payload, Jsonb)
    assert payload.obj == event.payload
    assert params == {
        "event_id": event.event_id,
        "tenant_id": "tenant-a",
        "revision_number": 7,
        "content_hash": "a" * 64,
        "event_type": "graph.revision.committed",
        "schema_version": 1,
        "idempotency_key": "tenant-a:7",
        "created_at": event.created_at,
        "published_at": None,
    }
    assert connection.commit_calls == 0


def test_idempotency_key_is_passed_through_unchanged() -> None:
    connection = _FakeConnection()
    repository = PostgresOutboxRepository(cast(Connection[Any], connection))
    event = make_outbox_event(event_id=uuid4(), idempotency_key="tenant-a:stable-key")

    repository.append(event)

    assert connection.cursor_instance.executed is not None
    _, params = connection.cursor_instance.executed
    assert params["idempotency_key"] == "tenant-a:stable-key"
