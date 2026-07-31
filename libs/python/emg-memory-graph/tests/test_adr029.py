"""ADR-029 lifecycle, supersession, and immutable replacement contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from _mg_helpers import ev
from emg_common_types import Classification
from emg_knowledge_lifecycle import InvalidTransitionError, VersionState
from emg_memory_graph import (
    MAX_SUPERSEDES,
    EdgeDirection,
    MemoryEdge,
    MemoryGraph,
    MemoryGraphBuilder,
    MemoryNode,
    MergeConflictError,
    NodeNotFoundError,
    TemporalHistory,
    TemporalValidity,
    edge_id_for,
)
from emg_memory_graph.metadata import Metadata
from pydantic import ValidationError

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
AS_OF = T0 + timedelta(days=30)


def node(
    node_id: str,
    *,
    owner: str = "owner-1",
    lifecycle_status: VersionState = VersionState.ACTIVE,
    classification: Classification = Classification.INTERNAL,
    aliases: tuple[str, ...] = (),
    histories: tuple[TemporalHistory, ...] = (),
    metadata: Metadata | None = None,
    supersedes: tuple[str, ...] = (),
) -> MemoryNode:
    return MemoryNode(
        node_id=node_id,
        node_type="person",
        label=node_id.title(),
        created_at=T0,
        updated_at=T0,
        source="svc-ingest",
        confidence=0.8,
        classification=classification,
        owner=owner,
        lifecycle_status=lifecycle_status,
        supersedes=supersedes,
        evidence=(ev(node_id),),
        aliases=aliases,
        histories=histories,
        metadata=metadata or Metadata(),
    )


def edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    *,
    edge_type: str = "owns",
    classification: Classification = Classification.INTERNAL,
) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        edge_type=edge_type,
        source_id=source_id,
        target_id=target_id,
        direction=EdgeDirection.DIRECTED,
        evidence=(ev(edge_id),),
        confidence=0.7,
        validity=TemporalValidity(valid_from=T0),
        created_at=T0,
        updated_at=T0,
        classification=classification,
    )


def replace_node(current: MemoryNode, **updates: object) -> MemoryNode:
    return MemoryNode.model_validate({**current.model_dump(), **updates})


def replace_edge(current: MemoryEdge, **updates: object) -> MemoryEdge:
    return MemoryEdge.model_validate({**current.model_dump(), **updates})


def history(attribute: str, value: str) -> TemporalHistory:
    return TemporalHistory(attribute=attribute).with_change(
        value=value,
        effective_from=T0,
        evidence=(ev(f"{attribute}-{value}"),),
        recorded_at=T0,
    )


def test_memory_node_defaults_deserialize_historical_payload() -> None:
    original = node("legacy")
    payload = original.model_dump(exclude={"owner", "lifecycle_status", "supersedes"})

    restored = MemoryNode.model_validate(payload)

    assert restored.owner == ""
    assert restored.lifecycle_status is VersionState.ACTIVE
    assert restored.supersedes == ()
    assert MemoryNode.model_validate_json(restored.model_dump_json()) == restored


def test_supersedes_is_unique_sorted_and_bounded() -> None:
    assert node("survivor", supersedes=("source-b", "source-a")).supersedes == (
        "source-a",
        "source-b",
    )
    with pytest.raises(ValidationError, match="duplicate node_id"):
        node("survivor", supersedes=("source", "source"))
    with pytest.raises(ValidationError, match="too many supersedes"):
        node(
            "survivor",
            supersedes=tuple(f"source-{index}" for index in range(MAX_SUPERSEDES + 1)),
        )


def test_replace_accepts_valid_lifecycle_transition() -> None:
    current = node("entity")
    base = MemoryGraph(nodes=(current,))
    replacement = replace_node(
        current,
        lifecycle_status=VersionState.SUPERSEDED,
        updated_at=AS_OF,
    )

    result = MemoryGraphBuilder().replace(base, node=replacement, as_of=AS_OF)

    assert result.graph.node("entity") is replacement
    assert current.lifecycle_status is VersionState.ACTIVE


def test_replace_rejects_invalid_lifecycle_transition() -> None:
    current = node("entity")
    replacement = replace_node(current, lifecycle_status=VersionState.ARCHIVED)

    with pytest.raises(InvalidTransitionError, match="active->archived"):
        MemoryGraphBuilder().replace(
            MemoryGraph(nodes=(current,)),
            node=replacement,
            as_of=AS_OF,
        )


def test_replace_preserves_owner_and_rejects_empty_historical_owner() -> None:
    current = node("entity")
    changed_owner = replace_node(current, owner="owner-2")

    with pytest.raises(MergeConflictError, match="immutable owner"):
        MemoryGraphBuilder().replace(
            MemoryGraph(nodes=(current,)),
            node=changed_owner,
            as_of=AS_OF,
        )

    historical = MemoryNode.model_validate(current.model_dump(exclude={"owner"}))
    with pytest.raises(MergeConflictError, match="requires an owner"):
        MemoryGraphBuilder().replace(
            MemoryGraph(nodes=(historical,)),
            node=historical,
            as_of=AS_OF,
        )


def test_merge_rejects_orphan_duplicate_self_and_non_live_sources() -> None:
    builder = MemoryGraphBuilder()
    live = MemoryGraph(nodes=(node("survivor"), node("source")))

    with pytest.raises(NodeNotFoundError, match="missing"):
        builder.replace(
            live,
            merge_survivor_id="survivor",
            merge_source_ids=("missing",),
            as_of=AS_OF,
        )
    with pytest.raises(MergeConflictError, match="must be unique"):
        builder.replace(
            live,
            merge_survivor_id="survivor",
            merge_source_ids=("source", "source"),
            as_of=AS_OF,
        )
    with pytest.raises(MergeConflictError, match="cannot supersede itself"):
        builder.replace(
            live,
            merge_survivor_id="survivor",
            merge_source_ids=("survivor",),
            as_of=AS_OF,
        )

    non_live = MemoryGraph(
        nodes=(
            node("survivor"),
            node("source", lifecycle_status=VersionState.SUPERSEDED),
        )
    )
    with pytest.raises(MergeConflictError, match="not live"):
        builder.replace(
            non_live,
            merge_survivor_id="survivor",
            merge_source_ids=("source",),
            as_of=AS_OF,
        )


def test_merge_rejects_source_claimed_by_another_survivor() -> None:
    base = MemoryGraph(
        nodes=(
            node("first", supersedes=("source",)),
            node("second"),
            node("source"),
        )
    )

    with pytest.raises(MergeConflictError, match="superseded by both"):
        MemoryGraphBuilder().replace(
            base,
            merge_survivor_id="second",
            merge_source_ids=("source",),
            as_of=AS_OF,
        )


def test_merge_enforces_accumulated_supersedes_limit() -> None:
    existing_ids = tuple(f"old-{index}" for index in range(MAX_SUPERSEDES))
    base = MemoryGraph(
        nodes=(
            node("survivor", supersedes=existing_ids),
            node("source"),
            *(
                node(source_id, lifecycle_status=VersionState.SUPERSEDED)
                for source_id in existing_ids
            ),
        )
    )

    with pytest.raises(MergeConflictError, match="supersedes limit"):
        MemoryGraphBuilder().replace(
            base,
            merge_survivor_id="survivor",
            merge_source_ids=("source",),
            as_of=AS_OF,
        )


def test_merge_combines_approved_fields_and_preserves_survivor_owner() -> None:
    survivor_history = history("department", "survivor-department")
    source_history = history("department", "source-department")
    source_title = history("title", "source-title")
    survivor = node(
        "survivor",
        owner="survivor-owner",
        aliases=("survivor-alias",),
        histories=(survivor_history,),
        metadata=Metadata.from_mapping({"survivor": "kept", "shared": "survivor"}),
    )
    source = node(
        "source",
        owner="source-owner",
        classification=Classification.SECRET,
        aliases=("source-alias",),
        histories=(source_history, source_title),
        metadata=Metadata.from_mapping({"source": "added", "shared": "source"}),
    )

    result = MemoryGraphBuilder().replace(
        MemoryGraph(nodes=(survivor, source)),
        merge_survivor_id="survivor",
        merge_source_ids=("source",),
        as_of=AS_OF,
    )

    merged = result.graph.node("survivor")
    absorbed = result.graph.node("source")
    assert merged is not None
    assert absorbed is not None
    assert merged.owner == "survivor-owner"
    assert merged.label == survivor.label
    assert merged.classification is Classification.SECRET
    assert merged.supersedes == ("source",)
    assert merged.aliases == ("source-alias", "survivor-alias")
    assert {item.evidence_id for item in merged.evidence} == {
        item.evidence_id for item in (*survivor.evidence, *source.evidence)
    }
    assert merged.history_for("department") == survivor_history
    assert merged.history_for("title") == source_title
    assert merged.metadata.as_dict() == {
        "shared": "source",
        "source": "added",
        "survivor": "kept",
    }
    assert absorbed.lifecycle_status is VersionState.SUPERSEDED
    assert absorbed.owner == source.owner
    assert source.lifecycle_status is VersionState.ACTIVE


def test_relationship_replacement_preserves_identity_and_endpoints() -> None:
    current = edge("rel-1", "a", "b")
    base = MemoryGraph(nodes=(node("a"), node("b")), edges=(current,))
    replacement = replace_edge(
        current,
        classification=Classification.CONFIDENTIAL,
        updated_at=AS_OF,
    )

    result = MemoryGraphBuilder().replace(base, edge=replacement, as_of=AS_OF)

    assert result.graph.edge("rel-1") is replacement
    assert result.graph.edge_count == 1

    changed_endpoint = replace_edge(current, target_id="c")
    with pytest.raises(MergeConflictError, match="immutable endpoints"):
        MemoryGraphBuilder().replace(base, edge=changed_endpoint, as_of=AS_OF)


def test_relationship_closure_constructs_replacement_without_mutation() -> None:
    current = replace_edge(
        edge("rel-1", "a", "b"),
        validity=TemporalValidity(valid_from=T0, valid_until=AS_OF + timedelta(days=30)),
    )
    base = MemoryGraph(nodes=(node("a"), node("b")), edges=(current,))

    result = MemoryGraphBuilder().replace(
        base,
        close_edge_id="rel-1",
        as_of=AS_OF,
    )

    closed = result.graph.edge("rel-1")
    assert closed is not None
    assert closed.edge_id == current.edge_id
    assert closed.endpoints() == current.endpoints()
    assert closed.validity.valid_until == AS_OF
    assert current.validity.valid_until == AS_OF + timedelta(days=30)


def test_merge_closes_incident_edge_and_constructs_reassigned_edge() -> None:
    current = edge("rel-source", "source", "target")
    base = MemoryGraph(
        nodes=(node("survivor"), node("source"), node("target")),
        edges=(current,),
    )

    result = MemoryGraphBuilder().replace(
        base,
        merge_survivor_id="survivor",
        merge_source_ids=("source",),
        as_of=AS_OF,
    )

    closed = result.graph.edge("rel-source")
    new_id = edge_id_for("owns", "survivor", "target")
    reassigned = result.graph.edge(new_id)
    assert closed is not None
    assert reassigned is not None
    assert closed.validity.valid_until == AS_OF
    assert closed.endpoints() == ("source", "target")
    assert reassigned.endpoints() == ("survivor", "target")
    assert reassigned.validity == TemporalValidity(valid_from=AS_OF)
    assert reassigned.evidence == current.evidence
    assert result.edges_created == 1


def test_merge_leaves_inactive_incident_edge_unchanged() -> None:
    historical = replace_edge(
        edge("rel-historical", "source", "target"),
        validity=TemporalValidity(valid_from=T0, valid_until=AS_OF),
    )
    base = MemoryGraph(
        nodes=(node("survivor"), node("source"), node("target")),
        edges=(historical,),
    )

    result = MemoryGraphBuilder().replace(
        base,
        merge_survivor_id="survivor",
        merge_source_ids=("source",),
        as_of=AS_OF,
    )

    assert result.graph.edge("rel-historical") is historical
    assert result.graph.edge_count == 1
    assert result.edges_created == 0


def test_merge_rejects_reassigned_edge_collision() -> None:
    collision_id = edge_id_for("owns", "survivor", "target")
    base = MemoryGraph(
        nodes=(node("survivor"), node("source"), node("target")),
        edges=(
            edge("rel-source", "source", "target"),
            edge(collision_id, "survivor", "target"),
        ),
    )

    with pytest.raises(MergeConflictError, match="collides"):
        MemoryGraphBuilder().replace(
            base,
            merge_survivor_id="survivor",
            merge_source_ids=("source",),
            as_of=AS_OF,
        )
