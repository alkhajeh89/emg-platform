"""Synchronization contracts, policies, plans, and validation (FEAT-13-1)."""

from __future__ import annotations

import pytest
from emg_connectors import (
    ConnectorValidationError,
    ConnectorValidator,
    FullSynchronization,
    IncrementalSynchronization,
    SynchronizationContract,
    SynchronizationMode,
    SynchronizationPolicy,
)
from emg_connectors.limits import MAX_BATCH_SIZE
from pydantic import ValidationError


def test_contract_incremental_requires_cursor() -> None:
    with pytest.raises(ValidationError):
        SynchronizationContract(
            supported_modes=(SynchronizationMode.INCREMENTAL,), supports_cursor=False
        )
    ok = SynchronizationContract(
        supported_modes=(SynchronizationMode.INCREMENTAL,), supports_cursor=True
    )
    assert ok.supports(SynchronizationMode.INCREMENTAL)


def test_contract_requires_a_mode() -> None:
    with pytest.raises(ValidationError):
        SynchronizationContract(supported_modes=())


def test_policy_batch_bounds() -> None:
    assert SynchronizationPolicy(mode=SynchronizationMode.FULL, batch_size=MAX_BATCH_SIZE)
    with pytest.raises(ValidationError):
        SynchronizationPolicy(mode=SynchronizationMode.FULL, batch_size=0)
    with pytest.raises(ValidationError):
        SynchronizationPolicy(mode=SynchronizationMode.FULL, batch_size=MAX_BATCH_SIZE + 1)


def test_full_plan_requires_full_mode() -> None:
    FullSynchronization(
        connector_id="c", policy=SynchronizationPolicy(mode=SynchronizationMode.FULL)
    )
    with pytest.raises(ValidationError):
        FullSynchronization(
            connector_id="c", policy=SynchronizationPolicy(mode=SynchronizationMode.INCREMENTAL)
        )


def test_incremental_plan_requires_incremental_mode() -> None:
    IncrementalSynchronization(
        connector_id="c",
        policy=SynchronizationPolicy(mode=SynchronizationMode.INCREMENTAL),
        since_cursor="cursor-42",
    )
    with pytest.raises(ValidationError):
        IncrementalSynchronization(
            connector_id="c", policy=SynchronizationPolicy(mode=SynchronizationMode.FULL)
        )


def test_validate_synchronization_against_contract() -> None:
    contract = SynchronizationContract(
        supported_modes=(SynchronizationMode.FULL,), supports_cursor=False
    )
    policy = SynchronizationPolicy(mode=SynchronizationMode.INCREMENTAL)
    issues = ConnectorValidator.validate_synchronization(contract, policy)
    assert issues  # incremental not supported by a full-only contract
    with pytest.raises(ConnectorValidationError):
        ConnectorValidator.assert_synchronization(contract, policy)


def test_allow_deletes_requires_delete_detection() -> None:
    contract = SynchronizationContract(
        supported_modes=(SynchronizationMode.FULL,), supports_delete_detection=False
    )
    policy = SynchronizationPolicy(mode=SynchronizationMode.FULL, allow_deletes=True)
    assert any("delete" in i for i in ConnectorValidator.validate_synchronization(contract, policy))


def test_valid_full_sync_has_no_issues() -> None:
    contract = SynchronizationContract(supported_modes=(SynchronizationMode.FULL,))
    policy = SynchronizationPolicy(mode=SynchronizationMode.FULL)
    assert ConnectorValidator.validate_synchronization(contract, policy) == ()
