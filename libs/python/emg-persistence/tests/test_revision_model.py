"""Revision / RevisionHead value types (Sprint 3)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from _rev_helpers import PRINCIPAL, TENANT, make_revision
from emg_persistence.revisions import Revision, RevisionHead
from pydantic import ValidationError

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _good_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant": TENANT,
        "revision_number": 1,
        "content_hash": "a" * 64,
        "parent_hash": None,
        "principal": PRINCIPAL,
        "node_count": 1,
        "edge_count": 0,
        "graph_json": {},
        "created_at": _T0,
    }
    base.update(overrides)
    return base


def test_head_derivation() -> None:
    r = make_revision(3, content_seed="x", parent_hash="a" * 64)
    head = r.head()
    assert head.tenant == TENANT
    assert head.revision_number == 3
    assert head.content_hash == r.content_hash


def test_revision_is_frozen() -> None:
    r = make_revision(1)
    with pytest.raises(ValidationError):
        r.revision_number = 2  # type: ignore[misc]


def test_revision_rejects_bad_version() -> None:
    with pytest.raises(ValidationError):
        make_revision(0)


def test_revision_rejects_bad_content_hash() -> None:
    with pytest.raises(ValidationError):
        Revision(**_good_kwargs(content_hash="nothex"))


def test_revision_rejects_bad_parent_hash() -> None:
    with pytest.raises(ValidationError):
        Revision(**_good_kwargs(parent_hash="short"))


def test_revision_rejects_negative_count() -> None:
    with pytest.raises(ValidationError):
        Revision(**_good_kwargs(node_count=-1))


def test_head_requires_hex_hash() -> None:
    with pytest.raises(ValidationError):
        RevisionHead(tenant=TENANT, revision_number=1, content_hash="short")
