"""ConnectorRegistry + ConnectorFactory (FEAT-13-1)."""

from __future__ import annotations

import pytest
from _helpers import FakeConnector, FakePlugin, make_descriptor
from emg_connectors import (
    Connector,
    ConnectorContext,
    ConnectorDescriptor,
    ConnectorFactory,
    ConnectorLifecycleState,
    ConnectorNotFoundError,
    ConnectorRegistrationError,
    ConnectorRegistry,
)


def test_register_get_contains() -> None:
    reg = ConnectorRegistry()
    d = make_descriptor()
    reg.register(d, plugin_id="acme")
    assert reg.contains("acme-dir")
    assert reg.get("acme-dir").connector_id == "acme-dir"
    assert reg.entry("acme-dir").plugin_id == "acme"
    assert reg.connector_ids() == ("acme-dir",)
    assert reg.count() == 1


def test_duplicate_registration_rejected() -> None:
    reg = ConnectorRegistry()
    reg.register(make_descriptor())
    with pytest.raises(ConnectorRegistrationError):
        reg.register(make_descriptor())


def test_get_unknown_raises() -> None:
    reg = ConnectorRegistry()
    with pytest.raises(ConnectorNotFoundError):
        reg.get("nope")
    with pytest.raises(ConnectorNotFoundError):
        reg.unregister("nope")


def test_unregister() -> None:
    reg = ConnectorRegistry()
    reg.register(make_descriptor())
    reg.unregister("acme-dir")
    assert not reg.contains("acme-dir")


def test_descriptors_sorted_deterministic() -> None:
    reg = ConnectorRegistry()
    reg.register(make_descriptor("z-conn"))
    reg.register(make_descriptor("a-conn"))
    assert [d.connector_id for d in reg.descriptors()] == ["a-conn", "z-conn"]


def test_factory_creates_connector(context: ConnectorContext, plugin: FakePlugin) -> None:
    connector = ConnectorFactory.create(plugin, "acme-dir", context)
    assert isinstance(connector, Connector)
    assert connector.descriptor().connector_id == "acme-dir"
    assert connector.lifecycle_state is ConnectorLifecycleState.REGISTERED


def test_factory_unknown_connector_raises(context: ConnectorContext, plugin: FakePlugin) -> None:
    with pytest.raises(ConnectorNotFoundError):
        ConnectorFactory.create(plugin, "does-not-exist", context)


def test_factory_incompatible_plugin_raises(context: ConnectorContext) -> None:
    from emg_connectors import ConnectorCompatibilityError

    future_only = FakePlugin(framework_min=(2, 0, 0))
    with pytest.raises(ConnectorCompatibilityError):
        ConnectorFactory.create(future_only, "acme-dir", context)


class _MislabelledPlugin(FakePlugin):
    def create_connector(self, connector_id: str, context: ConnectorContext) -> FakeConnector:
        # Deliberately produce a connector whose id does not match the request.
        return FakeConnector(make_descriptor("other-id"), created_at=context.as_of)


def test_factory_rejects_identity_mismatch(context: ConnectorContext) -> None:
    from emg_connectors import ConnectorValidationError

    bad = _MislabelledPlugin()
    # patch descriptor to also *declare* it provides acme-dir so we reach create
    with pytest.raises(ConnectorValidationError):
        ConnectorFactory.create(bad, "acme-dir", context)


def test_registered_descriptor_is_the_contract(descriptor: ConnectorDescriptor) -> None:
    reg = ConnectorRegistry()
    reg.register(descriptor)
    assert reg.get("acme-dir") == descriptor
