from __future__ import annotations

import pytest
from emg_persistence.mutations import LsnPosition


def test_lsn_ordering_uses_wal_position_then_transaction_index() -> None:
    first = LsnPosition("system-a", 4, "0/16B6C50", 0)
    same_transaction_next = LsnPosition("system-a", 4, "0/16B6C50", 1)
    later_commit = LsnPosition("system-a", 4, "0/16B6C60", 0)

    assert first < same_transaction_next < later_commit


def test_lsn_ordering_rejects_cross_timeline_comparison() -> None:
    first = LsnPosition("system-a", 4, "0/16B6C50", 0)
    failover = LsnPosition("system-a", 5, "0/16B6C50", 0)

    with pytest.raises(ValueError, match="different source timelines"):
        _ = first < failover


def test_lsn_rejects_malformed_value() -> None:
    with pytest.raises(ValueError, match="invalid PostgreSQL LSN"):
        _ = LsnPosition("system-a", 4, "not-an-lsn", 0) < LsnPosition("system-a", 4, "0/1", 0)
