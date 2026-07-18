"""Adversarial inputs: identifier spoofing / control chars must be rejected."""

from __future__ import annotations

import pytest
from emg_platform_core import PrincipalKind, PrincipalRef, TenantId
from pydantic import ValidationError

# Unicode right-to-left override — the classic identifier-spoofing character.
_RLO = "‮"


@pytest.mark.parametrize(
    "bad",
    ["", "  ", "a\x00b", "a\nb", "a\rb", f"spoof{_RLO}ed", "a\x07b"],
)
def test_tenant_rejects_unsafe_labels(bad: str) -> None:
    with pytest.raises(ValidationError):
        TenantId.of(bad)


@pytest.mark.parametrize("bad", ["", "svc\x00", f"a{_RLO}b", "a\nb"])
def test_principal_rejects_unsafe_ids(bad: str) -> None:
    with pytest.raises(ValidationError):
        PrincipalRef(principal_id=bad, kind=PrincipalKind.SERVICE)


def test_tenant_accepts_legitimate_unicode() -> None:
    # Non-control, non-bidi Unicode is legitimate and must be preserved.
    t = TenantId.of("عميل-١")
    assert t.value == "عميل-١"


def test_overlong_label_rejected() -> None:
    with pytest.raises(ValidationError):
        TenantId.of("x" * 10_000)
