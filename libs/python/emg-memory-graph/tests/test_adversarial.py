"""Adversarial / bounds / injection-surface tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from _mg_helpers import ASOF, node_input
from emg_memory_graph import (
    EvidenceRef,
    EvidenceSource,
    MemoryGraphBuilder,
    MemoryNode,
    ensure_safe_label,
)
from emg_memory_graph.limits import MAX_EVIDENCE_REFS
from pydantic import ValidationError

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
EV = (
    EvidenceRef.create(
        source=EvidenceSource.PDF, locator="l", source_principal="s", captured_at=T0
    ),
)


@pytest.mark.parametrize("bad", ["", "   ", "a\x00b", "a\nb", "a\rb", "a‮b"])
def test_control_bidi_labels_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        ensure_safe_label(bad)


def test_legitimate_unicode_preserved() -> None:
    assert ensure_safe_label("محمد المنصوري") == "محمد المنصوري"
    assert ensure_safe_label("Zürich") == "Zürich"


def test_node_id_control_char_rejected() -> None:
    with pytest.raises(ValidationError):
        MemoryNode(
            node_id="bad\x00",
            node_type="person",
            label="A",
            created_at=T0,
            updated_at=T0,
            source="s",
            confidence=0.5,
            evidence=EV,
        )


def test_evidence_bound_enforced() -> None:
    many = tuple(
        EvidenceRef.create(
            source=EvidenceSource.PDF, locator=f"l{i}", source_principal="s", captured_at=T0
        )
        for i in range(MAX_EVIDENCE_REFS + 1)
    )
    with pytest.raises(ValidationError):
        MemoryNode(
            node_id="n",
            node_type="person",
            label="A",
            created_at=T0,
            updated_at=T0,
            source="s",
            confidence=0.5,
            evidence=many,
        )


def test_extra_fields_forbidden() -> None:
    kwargs = dict(
        node_id="n",
        node_type="person",
        label="A",
        created_at=T0,
        updated_at=T0,
        source="s",
        confidence=0.5,
        evidence=EV,
        bogus=1,
    )
    with pytest.raises(ValidationError):
        MemoryNode(**kwargs)  # type: ignore[arg-type]


def test_builder_output_is_deterministic_under_shuffled_input() -> None:
    b = MemoryGraphBuilder()
    nodes = tuple(node_input(f"n{i}", "x", f"L{i}") for i in range(20))
    g1 = b.build(nodes=nodes, as_of=ASOF).graph
    g2 = b.build(nodes=tuple(reversed(nodes)), as_of=ASOF).graph
    assert g1.content_hash() == g2.content_hash()


def test_models_are_frozen() -> None:
    n = node_input("n", "x", "L")
    with pytest.raises(ValidationError):
        n.label = "y"  # type: ignore[misc]
