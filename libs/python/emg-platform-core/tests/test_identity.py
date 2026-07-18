"""TenantId / PrincipalRef value types (Freeze §9, §12)."""

from __future__ import annotations

import pytest
from emg_platform_core import (
    SYSTEM_PRINCIPAL,
    SYSTEM_TENANT,
    PrincipalKind,
    PrincipalRef,
    TenantId,
)
from pydantic import ValidationError


def test_tenant_of_and_str() -> None:
    t = TenantId.of("acme")
    assert t.value == "acme"
    assert str(t) == "acme"
    assert TenantId(value="acme") == t  # value equality


def test_tenant_is_frozen() -> None:
    t = TenantId.of("acme")
    with pytest.raises(ValidationError):
        t.value = "other"  # type: ignore[misc]


def test_tenant_rejects_empty_and_control_chars() -> None:
    with pytest.raises(ValidationError):
        TenantId.of("")
    with pytest.raises(ValidationError):
        TenantId.of("   ")
    with pytest.raises(ValidationError):
        TenantId.of("bad\x00id")
    with pytest.raises(ValidationError):
        TenantId.of("line\nbreak")


def test_system_tenant() -> None:
    assert SYSTEM_TENANT.value == "__system__"


def test_principal_constructors_and_str() -> None:
    assert PrincipalRef.user("u1").kind is PrincipalKind.USER
    assert PrincipalRef.service("svc-1").kind is PrincipalKind.SERVICE
    assert PrincipalRef.connector("c1").kind is PrincipalKind.CONNECTOR
    assert str(PrincipalRef.service("svc-1")) == "service:svc-1"


def test_principal_is_frozen_and_validated() -> None:
    p = PrincipalRef.user("u1")
    with pytest.raises(ValidationError):
        p.principal_id = "u2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        PrincipalRef(principal_id="bad\x00", kind=PrincipalKind.USER)


def test_system_principal() -> None:
    assert SYSTEM_PRINCIPAL.kind is PrincipalKind.SYSTEM
    assert SYSTEM_PRINCIPAL.principal_id == "__system__"


def test_principal_kind_values() -> None:
    assert {k.value for k in PrincipalKind} == {"user", "service", "connector", "system"}
