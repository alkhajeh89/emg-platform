"""Error hierarchy (Sprint 1)."""

from __future__ import annotations

from emg_errors import EMGError
from emg_persistence import PersistenceConflictError, PersistenceError, ProjectionLagError


def test_base_derives_from_emg_error() -> None:
    assert issubclass(PersistenceError, EMGError)


def test_subclasses_derive_from_persistence_error() -> None:
    assert issubclass(PersistenceConflictError, PersistenceError)
    assert issubclass(ProjectionLagError, PersistenceError)


def test_conflict_is_catchable_as_persistence_and_platform_error() -> None:
    for exc_type in (PersistenceError, EMGError):
        try:
            raise PersistenceConflictError("head advanced")
        except exc_type as exc:
            assert str(exc) == "head advanced"
        else:  # pragma: no cover - defensive
            raise AssertionError(f"not caught as {exc_type!r}")


def test_projection_lag_is_catchable_as_persistence_error() -> None:
    try:
        raise ProjectionLagError("projection behind head")
    except PersistenceError as exc:
        assert str(exc) == "projection behind head"
