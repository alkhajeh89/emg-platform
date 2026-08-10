from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from emg_memory_graph import EMPTY_GRAPH
from emg_persistence.postgres.search_repository import PostgresSearchRepository


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, query, params=None):
        return None

    def fetchall(self):
        return self._rows


class _MaintenanceCursor:
    def __init__(self):
        self.query = ""
        self.params = None
        self.rowcount = 0

    def execute(self, query, params=None):
        self.query = query
        self.params = params
        self.rowcount = params["limit"]


class _MaintenanceConnection:
    def __init__(self):
        self.recorded = []

    @contextmanager
    def cursor(self):
        cursor = _MaintenanceCursor()
        self.recorded.append(cursor)
        yield cursor


class _Connection:
    def __init__(self, rows):
        self._rows = rows

    @contextmanager
    def cursor(self):
        yield _Cursor(self._rows)


class _RecordingRepository(PostgresSearchRepository):
    def __init__(self, connection):
        super().__init__(connection)
        self.indexed = []

    def index_revision(self, tenant, revision_number, content_hash, graph):
        self.indexed.append((tenant.value, revision_number, content_hash, graph))


def test_current_head_backfill_is_hash_verified_and_deterministic():
    content_hash = EMPTY_GRAPH.content_hash()
    repository = _RecordingRepository(
        _Connection(
            [
                (
                    "tenant-a",
                    7,
                    content_hash,
                    EMPTY_GRAPH.model_dump(mode="json"),
                )
            ]
        )
    )
    assert repository.backfill_current_heads() == 1
    assert repository.indexed == [("tenant-a", 7, content_hash, EMPTY_GRAPH)]


def test_backfill_restart_with_no_missing_heads_is_a_no_op():
    repository = _RecordingRepository(_Connection([]))
    assert repository.backfill_current_heads() == 0
    assert repository.indexed == []


def test_backfill_hash_mismatch_fails_before_partial_publication():
    repository = _RecordingRepository(
        _Connection(
            [
                (
                    "tenant-a",
                    7,
                    "0" * 64,
                    EMPTY_GRAPH.model_dump(mode="json"),
                )
            ]
        )
    )
    with pytest.raises(ValueError, match="hash verification"):
        repository.backfill_current_heads()
    assert repository.indexed == []


def test_retention_maintenance_is_bounded_and_skip_locked():
    connection = _MaintenanceConnection()
    repository = PostgresSearchRepository(connection)
    now = datetime.now(timezone.utc)

    assert repository.expire_unscheduled_previous(now, limit=37) == 37
    assert repository.delete_expired(now, limit=19) == 19

    repair, deletion = connection.recorded
    assert repair.params["limit"] == 37
    assert deletion.params["limit"] == 19
    for cursor in (repair, deletion):
        assert "LIMIT %(limit)s" in cursor.query
        assert "SKIP LOCKED" in cursor.query
