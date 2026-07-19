"""PersistenceSettings: defaults, validation, bounds, immutability (Sprint 1)."""

from __future__ import annotations

import pytest
from emg_persistence import PersistenceSettings
from pydantic import SecretStr, ValidationError


def test_defaults_are_in_memory() -> None:
    s = PersistenceSettings()
    assert s.postgres_dsn is None
    assert s.neo4j_uri is None
    assert s.is_persistence_configured is False
    assert s.postgres_pool_min_size == 1
    assert s.postgres_pool_max_size == 10
    assert s.neo4j_max_pool_size == 10
    assert s.connect_timeout_seconds == 10.0


def test_is_persistence_configured_tracks_postgres_dsn() -> None:
    assert PersistenceSettings(postgres_dsn="postgresql://u@h/db").is_persistence_configured is True
    # Neo4j alone (projection only) does NOT make persistence "configured" (ADR-1).
    assert PersistenceSettings(neo4j_uri="neo4j://h").is_persistence_configured is False


@pytest.mark.parametrize("dsn", ["postgresql://u@h/db", "postgres://u:p@h:5432/db"])
def test_valid_postgres_dsn_accepted(dsn: str) -> None:
    assert PersistenceSettings(postgres_dsn=dsn).postgres_dsn == dsn


@pytest.mark.parametrize("dsn", ["mysql://h/db", "http://h", "just-a-string", ""])
def test_invalid_postgres_dsn_rejected(dsn: str) -> None:
    with pytest.raises(ValidationError):
        PersistenceSettings(postgres_dsn=dsn)


@pytest.mark.parametrize("uri", ["neo4j://h", "neo4j+s://h", "bolt://h", "bolt+ssc://h"])
def test_valid_neo4j_uri_accepted(uri: str) -> None:
    assert PersistenceSettings(neo4j_uri=uri).neo4j_uri == uri


@pytest.mark.parametrize("uri", ["http://h", "postgres://h", "bad"])
def test_invalid_neo4j_uri_rejected(uri: str) -> None:
    with pytest.raises(ValidationError):
        PersistenceSettings(neo4j_uri=uri)


def test_pool_bounds_validated() -> None:
    with pytest.raises(ValidationError):
        PersistenceSettings(postgres_pool_min_size=5, postgres_pool_max_size=2)
    # equal bounds are allowed
    s = PersistenceSettings(postgres_pool_min_size=3, postgres_pool_max_size=3)
    assert s.postgres_pool_max_size == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"postgres_pool_min_size": -1},
        {"postgres_pool_max_size": 0},
        {"neo4j_max_pool_size": 0},
        {"connect_timeout_seconds": 0},
        {"connect_timeout_seconds": -5},
    ],
)
def test_out_of_range_values_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PersistenceSettings(**kwargs)


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        PersistenceSettings(unknown_field="x")  # type: ignore[call-arg]


def test_settings_are_frozen() -> None:
    s = PersistenceSettings()
    with pytest.raises(ValidationError):
        s.postgres_dsn = "postgresql://h/db"  # type: ignore[misc]


def test_password_is_secret_and_not_leaked() -> None:
    s = PersistenceSettings(neo4j_password="s3cr3t")
    assert isinstance(s.neo4j_password, SecretStr)
    assert s.neo4j_password.get_secret_value() == "s3cr3t"
    assert "s3cr3t" not in repr(s)
    assert "s3cr3t" not in str(s)


def test_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMG_PERSISTENCE_POSTGRES_DSN", "postgresql://env@h/db")
    monkeypatch.setenv("EMG_PERSISTENCE_POSTGRES_POOL_MAX_SIZE", "25")
    s = PersistenceSettings()
    assert s.postgres_dsn == "postgresql://env@h/db"
    assert s.postgres_pool_max_size == 25
    assert s.is_persistence_configured is True
