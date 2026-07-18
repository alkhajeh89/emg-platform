"""Package import surface and version."""

from __future__ import annotations

import emg_platform_core as pc


def test_version() -> None:
    assert pc.__version__ == "0.1.0"


def test_public_api_exports() -> None:
    expected = {
        "GraphStore",
        "GraphTransaction",
        "InMemoryGraphStore",
        "PlatformCoreError",
        "PrincipalKind",
        "PrincipalRef",
        "TenantId",
        "TransactionStateError",
        "WriteReceipt",
        "SYSTEM_TENANT",
        "SYSTEM_PRINCIPAL",
    }
    assert expected.issubset(set(pc.__all__))
    for name in expected:
        assert hasattr(pc, name), name


def test_submodules_import() -> None:
    from emg_platform_core import adapters, errors, identity, ports

    assert adapters.InMemoryGraphStore is pc.InMemoryGraphStore
    assert errors.PlatformCoreError is pc.PlatformCoreError
    assert identity.TenantId is pc.TenantId
    assert ports.GraphStore is pc.GraphStore
