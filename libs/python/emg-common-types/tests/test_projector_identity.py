from __future__ import annotations

import json

import pytest
from emg_common_types import (
    parse_projector_identity_inventory,
    projector_client_allow_list,
    validate_projector_credential_bindings,
)


def _inventory(entries: list[dict[str, str]]) -> str:
    return json.dumps({"version": 1, "projector_identities": entries})


def test_inventory_is_strict_unique_and_deterministically_sorted() -> None:
    identities = parse_projector_identity_inventory(
        _inventory(
            [
                {"tenant_id": "tenant-b", "client_id": "projector-b"},
                {"tenant_id": "tenant-a", "client_id": "projector-a"},
            ]
        )
    )

    assert [(item.tenant_id, item.client_id) for item in identities] == [
        ("tenant-a", "projector-a"),
        ("tenant-b", "projector-b"),
    ]
    assert projector_client_allow_list(identities) == ("projector-a", "projector-b")


@pytest.mark.parametrize(
    "entries, message",
    [
        (
            [
                {"tenant_id": "tenant-a", "client_id": "client-a"},
                {"tenant_id": "tenant-a", "client_id": "client-b"},
            ],
            "duplicate tenant_id",
        ),
        (
            [
                {"tenant_id": "tenant-a", "client_id": "client-a"},
                {"tenant_id": "tenant-b", "client_id": "client-a"},
            ],
            "duplicate client_id",
        ),
        ([{"tenant_id": "", "client_id": "client-a"}], "tenant_id"),
        ([{"tenant_id": "tenant-a", "client_id": "provided-by-environment"}], "placeholder"),
    ],
)
def test_inventory_rejects_invalid_or_unresolved_bindings(
    entries: list[dict[str, str]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_projector_identity_inventory(_inventory(entries))


def test_secret_bindings_must_match_inventory_exactly() -> None:
    identities = parse_projector_identity_inventory(
        _inventory([{"tenant_id": "tenant-a", "client_id": "client-a"}])
    )
    validate_projector_credential_bindings(
        identities,
        [{"tenant_id": "tenant-a", "client_id": "client-a", "client_secret": "secret"}],
    )

    with pytest.raises(ValueError, match="exactly match"):
        validate_projector_credential_bindings(
            identities,
            [{"tenant_id": "tenant-b", "client_id": "client-b", "client_secret": "secret"}],
        )
