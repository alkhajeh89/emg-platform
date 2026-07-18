"""Plugin descriptor, validation, compatibility, and in-memory loader (FEAT-13-1)."""

from __future__ import annotations

import pytest
from _helpers import FakePlugin, make_capabilities, make_descriptor
from emg_connectors import (
    ConnectorCapabilities,
    ConnectorCapability,
    ConnectorCompatibilityError,
    ConnectorDescriptor,
    ConnectorNotFoundError,
    ConnectorPlugin,
    ConnectorPluginDescriptor,
    ConnectorPluginLoader,
    ConnectorRegistrationError,
    PluginCompatibility,
    PluginLifecycleState,
    PluginValidation,
    PluginValidationError,
    SynchronizationMode,
    Version,
    VersionRange,
)
from pydantic import ValidationError


def _plugin_descriptor(**overrides: object) -> ConnectorPluginDescriptor:
    base = dict(
        plugin_id="acme",
        name="Acme",
        version=Version(major=1, minor=0, patch=0),
        vendor="acme",
        framework_compatibility=VersionRange(minimum=Version(major=1, minor=0, patch=0)),
        provided_connectors=(make_descriptor(),),
    )
    base.update(overrides)
    return ConnectorPluginDescriptor(**base)  # type: ignore[arg-type]


def test_plugin_is_structural_protocol(plugin: FakePlugin) -> None:
    assert isinstance(plugin, ConnectorPlugin)

    class NotAPlugin:
        pass

    assert not isinstance(NotAPlugin(), ConnectorPlugin)


def test_plugin_descriptor_requires_a_connector() -> None:
    with pytest.raises(ValidationError):
        _plugin_descriptor(provided_connectors=())


def test_plugin_descriptor_rejects_duplicate_connector_ids() -> None:
    with pytest.raises(ValidationError):
        _plugin_descriptor(provided_connectors=(make_descriptor("x"), make_descriptor("x")))


def test_plugin_validation_passes_for_coherent_plugin() -> None:
    assert PluginValidation.validate(_plugin_descriptor()) == ()


def test_plugin_validation_flags_incoherent_capabilities() -> None:
    # Declares incremental_sync capability but omits the INCREMENTAL sync mode.
    caps = ConnectorCapabilities(
        capabilities=(ConnectorCapability.INCREMENTAL_SYNC,),
        supported_sync_modes=(SynchronizationMode.FULL,),
    )
    descriptor = ConnectorDescriptor(
        connector_id="bad",
        name="Bad",
        version=Version(major=1, minor=0, patch=0),
        vendor="acme",
        capabilities=caps,
    )
    issues = PluginValidation.validate(_plugin_descriptor(provided_connectors=(descriptor,)))
    assert any("incremental_sync" in i for i in issues)


def test_compatibility_check() -> None:
    assert PluginCompatibility.is_compatible(_plugin_descriptor())
    incompatible = _plugin_descriptor(
        framework_compatibility=VersionRange(minimum=Version(major=2, minor=0, patch=0))
    )
    assert not PluginCompatibility.is_compatible(incompatible)
    with pytest.raises(ConnectorCompatibilityError):
        PluginCompatibility.assert_compatible(incompatible)


def test_loader_registers_and_enables(plugin: FakePlugin) -> None:
    loader = ConnectorPluginLoader()
    loader.register(plugin)
    assert loader.plugin_ids() == ("acme",)
    assert loader.state_of("acme") is PluginLifecycleState.ENABLED
    assert loader.get("acme") is plugin
    assert len(loader.registered()) == 1
    assert loader.descriptors()[0].plugin_id == "acme"


def test_loader_rejects_duplicate(plugin: FakePlugin) -> None:
    loader = ConnectorPluginLoader()
    loader.register(plugin)
    with pytest.raises(ConnectorRegistrationError):
        loader.register(FakePlugin())


def test_loader_rejects_incompatible() -> None:
    loader = ConnectorPluginLoader()
    with pytest.raises(ConnectorCompatibilityError):
        loader.register(FakePlugin(framework_min=(2, 0, 0)))


def test_loader_unregister_and_unknown(plugin: FakePlugin) -> None:
    loader = ConnectorPluginLoader()
    loader.register(plugin)
    loader.unregister("acme")
    with pytest.raises(ConnectorNotFoundError):
        loader.get("acme")
    with pytest.raises(ConnectorNotFoundError):
        loader.state_of("acme")


def test_loader_state_transitions(plugin: FakePlugin) -> None:
    from emg_connectors import ConnectorLifecycleError

    loader = ConnectorPluginLoader()
    loader.register(plugin)
    loader.set_state("acme", PluginLifecycleState.DISABLED)
    assert loader.state_of("acme") is PluginLifecycleState.DISABLED
    loader.set_state("acme", PluginLifecycleState.RETIRED)
    with pytest.raises(ConnectorLifecycleError):
        loader.set_state("acme", PluginLifecycleState.ENABLED)  # RETIRED is terminal


def test_assert_valid_raises_typed() -> None:
    caps = ConnectorCapabilities(
        capabilities=(ConnectorCapability.INCREMENTAL_SYNC,),
        supported_sync_modes=(SynchronizationMode.FULL,),
    )
    descriptor = ConnectorDescriptor(
        connector_id="bad",
        name="Bad",
        version=Version(major=1, minor=0, patch=0),
        vendor="acme",
        capabilities=caps,
    )
    with pytest.raises(PluginValidationError):
        PluginValidation.assert_valid(_plugin_descriptor(provided_connectors=(descriptor,)))


def test_capabilities_unused_import_guard() -> None:
    # `make_capabilities` is exercised indirectly; assert it builds a valid model.
    assert make_capabilities().supports(ConnectorCapability.READ)


# --- FIX 2: loader is the single source of truth for connectors -------------

from datetime import datetime, timezone  # noqa: E402

from emg_connectors import (  # noqa: E402
    AbstractConnector,
    ConnectorContext,
)

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _desc(cid: str) -> ConnectorDescriptor:
    return ConnectorDescriptor(
        connector_id=cid,
        name=cid,
        version=Version(major=1, minor=0, patch=0),
        vendor="acme",
        capabilities=ConnectorCapabilities(capabilities=(ConnectorCapability.READ,)),
    )


class _MultiPlugin:
    def __init__(self, plugin_id: str, connector_ids: tuple[str, ...]) -> None:
        self._pd = ConnectorPluginDescriptor(
            plugin_id=plugin_id,
            name=plugin_id,
            version=Version(major=1, minor=0, patch=0),
            vendor="acme",
            framework_compatibility=VersionRange(minimum=Version(major=1, minor=0, patch=0)),
            provided_connectors=tuple(_desc(c) for c in connector_ids),
        )

    def plugin_descriptor(self) -> ConnectorPluginDescriptor:
        return self._pd

    def create_connector(self, connector_id: str, context: ConnectorContext) -> AbstractConnector:
        d = self._pd.connector(connector_id)
        assert d is not None
        return AbstractConnector(d, created_at=context.as_of)


def test_registering_a_plugin_auto_publishes_its_connectors() -> None:
    loader = ConnectorPluginLoader()
    loader.register(_MultiPlugin("acme", ("acme-dir", "acme-cal")))
    # No separate registry.register call was needed.
    assert loader.connector_ids() == ("acme-cal", "acme-dir")  # sorted, deterministic
    assert loader.get_connector("acme-dir").connector_id == "acme-dir"
    assert loader.plugin_id_for_connector("acme-dir") == "acme"
    assert [d.connector_id for d in loader.discovery().by_capability(ConnectorCapability.READ)] == [
        "acme-cal",
        "acme-dir",
    ]


def test_unregistering_a_plugin_withdraws_its_connectors() -> None:
    loader = ConnectorPluginLoader()
    loader.register(_MultiPlugin("acme", ("acme-dir", "acme-cal")))
    loader.unregister("acme")
    # No drift: connectors gone with the plugin.
    assert loader.connector_ids() == ()
    assert loader.plugin_ids() == ()
    with pytest.raises(ConnectorNotFoundError):
        loader.get_connector("acme-dir")


def test_cross_plugin_connector_id_collision_is_atomic() -> None:
    loader = ConnectorPluginLoader()
    loader.register(_MultiPlugin("p1", ("shared",)))
    with pytest.raises(ConnectorRegistrationError):
        loader.register(_MultiPlugin("p2", ("other", "shared")))
    # p2 left no partial state (its "other" connector must not have leaked).
    assert "p2" not in loader.plugin_ids()
    assert "other" not in loader.connector_ids()
    assert loader.connector_ids() == ("shared",)


def test_two_loaders_do_not_share_connector_state() -> None:
    a = ConnectorPluginLoader()
    b = ConnectorPluginLoader()
    a.register(_MultiPlugin("acme", ("acme-dir",)))
    assert a.connector_ids() == ("acme-dir",)
    assert b.connector_ids() == ()
