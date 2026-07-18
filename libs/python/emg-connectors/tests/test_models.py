"""Metadata / health / statistics / status / events / mapping / context (FEAT-13-1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from _helpers import make_descriptor
from emg_connectors import (
    AbstractConnector,
    ChangeType,
    ConnectorChange,
    ConnectorEvent,
    ConnectorEventType,
    ConnectorHealth,
    ConnectorHealthStatus,
    ConnectorLifecycleState,
    ConnectorSnapshot,
    ConnectorStatistics,
    ConnectorStatus,
    EntityMapper,
    MappedEntity,
    MetadataMapper,
    SourceRecord,
    SynchronizationMode,
)
from pydantic import ValidationError

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_descriptor_supports_helpers() -> None:
    from emg_connectors import ConnectorCapability

    d = make_descriptor()
    assert d.supports(ConnectorCapability.READ)
    assert d.supports_entity_type("Person")
    assert d.supports_sync_mode(SynchronizationMode.FULL)


def test_health_and_statistics_defaults() -> None:
    h = ConnectorHealth(checked_at=T0)
    assert h.status is ConnectorHealthStatus.UNKNOWN and not h.is_healthy
    s = ConnectorStatistics()
    assert s.entities_seen == 0 and s.errors == 0


def test_statistics_reject_negative() -> None:
    with pytest.raises(ValidationError):
        ConnectorStatistics(errors=-1)


def test_status_snapshot() -> None:
    status = ConnectorStatus(
        connector_id="c",
        lifecycle_state=ConnectorLifecycleState.ACTIVE,
        health=ConnectorHealth(status=ConnectorHealthStatus.HEALTHY, checked_at=T0),
        statistics=ConnectorStatistics(entities_seen=5),
    )
    assert status.health.is_healthy
    with pytest.raises(ValidationError):
        status.lifecycle_state = ConnectorLifecycleState.STOPPED


def test_event_change_snapshot() -> None:
    ev = ConnectorEvent(event_type=ConnectorEventType.ACTIVATED, connector_id="c", occurred_at=T0)
    assert ev.event_type is ConnectorEventType.ACTIVATED
    ch = ConnectorChange(
        change_type=ChangeType.UPDATE,
        entity_type="Person",
        external_id="p1",
        occurred_at=T0,
        attributes={"name": "Ada"},
    )
    assert ch.attributes["name"] == "Ada"
    snap = ConnectorSnapshot(
        snapshot_id="s1",
        connector_id="c",
        taken_at=T0,
        mode=SynchronizationMode.FULL,
        cursor="w-1",
        entity_count=10,
    )
    assert snap.entity_count == 10


def test_change_attributes_are_immutable() -> None:
    ch = ConnectorChange(
        change_type=ChangeType.CREATE,
        entity_type="Person",
        external_id="p1",
        occurred_at=T0,
        attributes={"a": 1},
    )
    with pytest.raises(TypeError):
        ch.attributes["a"] = 2  # type: ignore[index]


def test_abstract_connector_lifecycle_and_status() -> None:
    conn = AbstractConnector(make_descriptor(), created_at=T0)
    assert conn.lifecycle_state is ConnectorLifecycleState.REGISTERED
    conn.transition(ConnectorLifecycleState.CONFIGURED)
    conn.report_health(ConnectorHealth(status=ConnectorHealthStatus.HEALTHY, checked_at=T0))
    conn.report_statistics(ConnectorStatistics(entities_seen=3))
    st = conn.status()
    assert st.health.is_healthy and st.statistics.entities_seen == 3
    assert conn.capabilities().supports_entity_type("Person")


def test_mapper_protocols_are_structural() -> None:
    class MyEntityMapper:
        def map_entity(self, record: SourceRecord) -> MappedEntity:
            return MappedEntity(entity_type=record.record_type, external_id=record.external_id)

    class MyMetaMapper:
        pass

    assert isinstance(MyEntityMapper(), EntityMapper)
    assert not isinstance(MyMetaMapper(), MetadataMapper)
    mapped = MyEntityMapper().map_entity(
        SourceRecord(record_type="Person", external_id="p1", attributes={"k": "v"})
    )
    assert mapped.entity_type == "Person"


def test_mapped_entity_attributes_immutable() -> None:
    m = MappedEntity(entity_type="Person", external_id="p1", attributes={"a": 1})
    with pytest.raises(TypeError):
        m.attributes["a"] = 2  # type: ignore[index]
