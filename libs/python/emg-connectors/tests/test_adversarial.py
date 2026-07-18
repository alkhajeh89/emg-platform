"""Adversarial tests (FEAT-13-1): identifier hardening, nested immutability,
bounds, unknown-field rejection, determinism."""

from __future__ import annotations

from datetime import datetime, timezone

import emg_connectors as c
import pytest
from emg_connectors import (
    ChangeType,
    ConnectorCapabilities,
    ConnectorCapability,
    ConnectorChange,
    ConnectorConfiguration,
    ConnectorDescriptor,
    ConnectorMetadata,
    Version,
)
from emg_connectors.limits import MAX_CAPABILITIES, MAX_ENTITY_TYPES
from pydantic import ValidationError

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

_UNSAFE = {
    "NUL": "a\x00b",
    "control": "a\x01b",
    "newline": "a\nb",
    "carriage-return": "a\rb",
    "bidi-RLO": "a‮b",
    "whitespace-only": "   ",
    "empty": "",
}


@pytest.mark.parametrize("bad", list(_UNSAFE.values()), ids=list(_UNSAFE))
def test_connector_id_rejects_unsafe(bad: str) -> None:
    with pytest.raises(ValidationError):
        ConnectorDescriptor(
            connector_id=bad,
            name="X",
            version=Version(major=1, minor=0, patch=0),
            vendor="acme",
            capabilities=ConnectorCapabilities(),
        )


@pytest.mark.parametrize("bad", list(_UNSAFE.values()), ids=list(_UNSAFE))
def test_entity_type_rejects_unsafe(bad: str) -> None:
    with pytest.raises(ValidationError):
        ConnectorCapabilities(supported_entity_types=(bad,))


def test_legit_unicode_preserved() -> None:
    caps = ConnectorCapabilities(supported_entity_types=("Persoană", "组织"))
    assert "组织" in caps.supported_entity_types


def test_ensure_safe_label_exported() -> None:
    assert c.ensure_safe_label("ok-1") == "ok-1"
    with pytest.raises(ValueError):
        c.ensure_safe_label("x\x00")


def test_change_attribute_keys_validated() -> None:
    with pytest.raises(ValidationError):
        ConnectorChange(
            change_type=ChangeType.CREATE,
            entity_type="Person",
            external_id="p1",
            occurred_at=T0,
            attributes={"bad\x00key": 1},
        )


def test_config_input_dict_not_aliased() -> None:
    src: dict[str, object] = {"a": 1}
    cfg = ConnectorConfiguration(connector_id="c", values=src)  # type: ignore[arg-type]
    src["a"] = 999
    src["b"] = 2
    assert cfg.values["a"] == 1
    assert "b" not in cfg.values


def test_capabilities_bounded() -> None:
    # Oversized entity-type collection is rejected.
    with pytest.raises(ValidationError):
        ConnectorCapabilities(
            supported_entity_types=tuple(f"E{i}" for i in range(MAX_ENTITY_TYPES + 1))
        )


def test_extreme_version_rejected() -> None:
    with pytest.raises(ValidationError):
        Version(major=10**9 + 1, minor=0, patch=0)


def test_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ConnectorMetadata(rogue="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Version(major=1, minor=0, patch=0, rogue="x")  # type: ignore[call-arg]


def test_capabilities_capacity_within_max() -> None:
    caps = ConnectorCapabilities(capabilities=tuple(ConnectorCapability))
    assert len(caps.capabilities) <= MAX_CAPABILITIES


def test_descriptor_is_deterministic() -> None:
    from _helpers import make_descriptor

    assert make_descriptor().model_dump() == make_descriptor().model_dump()
