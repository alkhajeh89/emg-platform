from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from emg_common_types import Classification
from emg_memory_graph import (
    EdgeDirection,
    EvidenceRef,
    EvidenceSource,
    MemoryEdge,
    MemoryGraph,
    MemoryNode,
    TemporalValidity,
)
from tools.scripts.detect_temporal_edge_identity_drift import (
    EXIT_CLEAN,
    EXIT_CONFIRMED_DRIFT,
    EXIT_INSUFFICIENT_EVIDENCE,
    EXIT_OPERATIONAL_ERROR,
    RelationshipInventoryItem,
    analyze_revision,
    exit_code_for,
    logical_shape,
    render_human,
    render_json,
)

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=30)
T2 = T1 + timedelta(days=30)


def evidence(locator: str) -> EvidenceRef:
    return EvidenceRef.create(
        source=EvidenceSource.MANUAL_ENTRY,
        locator=locator,
        source_principal="tester",
        captured_at=T0,
    )


def node(node_id: str) -> MemoryNode:
    return MemoryNode(
        node_id=node_id,
        node_type="entity",
        label=node_id,
        created_at=T0,
        updated_at=T0,
        source="test",
        confidence=1.0,
        evidence=(evidence(f"node-{node_id}"),),
    )


def edge(
    edge_id: str,
    *,
    edge_type: str = "owns",
    source_id: str = "a",
    target_id: str = "b",
    direction: EdgeDirection = EdgeDirection.DIRECTED,
    valid_from: datetime = T0,
    valid_until: datetime | None = None,
    locators: tuple[str, ...] = ("rel-1",),
    classification: Classification = Classification.INTERNAL,
) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        edge_type=edge_type,
        source_id=source_id,
        target_id=target_id,
        direction=direction,
        evidence=tuple(evidence(locator) for locator in locators),
        confidence=1.0,
        validity=TemporalValidity(valid_from=valid_from, valid_until=valid_until),
        created_at=valid_from,
        updated_at=valid_from,
        classification=classification,
    )


def relationship(
    relationship_id: str,
    *,
    relationship_type: str = "owns",
    source_id: str = "a",
    target_id: str = "b",
    direction: EdgeDirection = EdgeDirection.DIRECTED,
    effective_from: datetime = T0,
    effective_to: datetime | None = None,
    evidence_identities: tuple[str, ...] | None = None,
    supersedes: str | None = None,
    classification: Classification = Classification.INTERNAL,
) -> RelationshipInventoryItem:
    return RelationshipInventoryItem(
        relationship_id=relationship_id,
        relationship_type=relationship_type,
        from_entity_id=source_id,
        to_entity_id=target_id,
        direction=direction,
        effective_from=effective_from,
        effective_to=effective_to,
        classification=classification,
        evidence_identities=evidence_identities or (relationship_id,),
        supersedes=supersedes,
    )


def export(tmp_path: Path, graph: MemoryGraph, **updates: object) -> Path:
    payload: dict[str, object] = {
        "tenant_id": "tenant-a",
        "revision_number": 7,
        "content_hash": graph.content_hash(),
        "graph_json": graph.model_dump(mode="json"),
    }
    payload.update(updates)
    path = tmp_path / f"revision-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def classes(result: object) -> set[str]:
    return {finding.classification for finding in result.findings}  # type: ignore[attr-defined]


def test_clean_canonical_graph(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-1"),))
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1"),))
    assert classes(result) == {"clean"}
    assert exit_code_for((result,)) == EXIT_CLEAN


def test_legacy_graph_without_inventory_is_unverifiable(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("me-legacy"),))
    result = analyze_revision(export(tmp_path, graph))
    assert classes(result) == {"legacy_id_without_source_inventory"}
    assert exit_code_for((result,)) == EXIT_INSUFFICIENT_EVIDENCE


def test_mixed_identity_for_one_shape_is_confirmed(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("me-legacy"), edge("rel-1")))
    result = analyze_revision(export(tmp_path, graph))
    assert "confirmed_mixed_identity" in classes(result)
    assert exit_code_for((result,)) == EXIT_CONFIRMED_DRIFT


def test_canonical_relationship_missing_from_graph(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")))
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1"),))
    assert "confirmed_missing_relationship_edge" in classes(result)


def test_graph_canonical_edge_absent_from_inventory(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-extra"),))
    result = analyze_revision(export(tmp_path, graph), ())
    assert classes(result) == {"graph_edge_absent_from_source"}


def test_adjacent_canonical_versions_are_valid(tmp_path: Path) -> None:
    graph = MemoryGraph(
        nodes=(node("a"), node("b")),
        edges=(
            edge("rel-1", valid_until=T1, locators=("evidence-1",)),
            edge("rel-1-v2", valid_from=T1, valid_until=T2, locators=("evidence-2",)),
        ),
    )
    inventory = (
        relationship("rel-1", effective_to=T1, evidence_identities=("evidence-1",)),
        relationship(
            "rel-1-v2",
            effective_from=T1,
            effective_to=T2,
            evidence_identities=("evidence-2",),
            supersedes="rel-1",
        ),
    )
    assert classes(analyze_revision(export(tmp_path, graph), inventory)) == {"clean"}


def test_legacy_multi_version_evidence_is_suspected(tmp_path: Path) -> None:
    graph = MemoryGraph(
        nodes=(node("a"), node("b")),
        edges=(edge("me-legacy", valid_until=T1, locators=("evidence-1", "evidence-2")),),
    )
    inventory = (
        relationship("rel-1", effective_to=T1, evidence_identities=("evidence-1",)),
        relationship(
            "rel-1-v2",
            effective_from=T1,
            effective_to=T2,
            evidence_identities=("evidence-2",),
        ),
    )
    result = analyze_revision(export(tmp_path, graph), inventory)
    assert "suspected_collapsed_evidence" in classes(result)
    assert exit_code_for((result,)) == EXIT_CONFIRMED_DRIFT


def test_validity_only_mismatch_is_interval_mismatch(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-1", valid_until=T1),))
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1", effective_to=T2),))
    assert classes(result) == {"confirmed_interval_mismatch"}
    assert result.findings[0].evidence == ("validity",)


def test_edge_type_mismatch_is_definition_mismatch(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-1", edge_type="supports"),))
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1"),))
    assert classes(result) == {"confirmed_relationship_definition_mismatch"}
    assert result.findings[0].evidence == ("edge_type",)


def test_direction_mismatch_is_definition_mismatch(tmp_path: Path) -> None:
    graph = MemoryGraph(
        nodes=(node("a"), node("b")),
        edges=(edge("rel-1", direction=EdgeDirection.UNDIRECTED),),
    )
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1"),))
    assert classes(result) == {"confirmed_relationship_definition_mismatch"}
    assert result.findings[0].evidence == ("direction",)


def test_endpoints_mismatch_is_definition_mismatch(tmp_path: Path) -> None:
    graph = MemoryGraph(
        nodes=(node("a"), node("b"), node("c")),
        edges=(edge("rel-1", target_id="c"),),
    )
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1"),))
    assert classes(result) == {"confirmed_relationship_definition_mismatch"}
    assert result.findings[0].evidence == ("endpoints",)


def test_classification_mismatch_is_definition_mismatch(tmp_path: Path) -> None:
    graph = MemoryGraph(
        nodes=(node("a"), node("b")),
        edges=(edge("rel-1", classification=Classification.CONFIDENTIAL),),
    )
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1"),))
    assert classes(result) == {"confirmed_relationship_definition_mismatch"}
    assert result.findings[0].evidence == ("classification",)


def test_validity_and_classification_mismatches_are_separate(tmp_path: Path) -> None:
    graph = MemoryGraph(
        nodes=(node("a"), node("b")),
        edges=(
            edge(
                "rel-1",
                valid_until=T1,
                classification=Classification.CONFIDENTIAL,
            ),
        ),
    )
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1", effective_to=T2),))
    assert classes(result) == {
        "confirmed_interval_mismatch",
        "confirmed_relationship_definition_mismatch",
    }
    evidence_by_class = {finding.classification: finding.evidence for finding in result.findings}
    assert evidence_by_class["confirmed_interval_mismatch"] == ("validity",)
    assert evidence_by_class["confirmed_relationship_definition_mismatch"] == ("classification",)


def test_foreign_version_evidence_is_association_mismatch(tmp_path: Path) -> None:
    graph = MemoryGraph(
        nodes=(node("a"), node("b")),
        edges=(edge("rel-1", locators=("evidence-v2",)),),
    )
    inventory = (
        relationship("rel-1", evidence_identities=("evidence-v1",)),
        relationship("rel-1-v2", evidence_identities=("evidence-v2",)),
    )
    result = analyze_revision(export(tmp_path, graph), inventory)
    association = [
        finding
        for finding in result.findings
        if finding.classification == "confirmed_evidence_association_mismatch"
    ]
    assert association and association[0].confirmed
    assert "confirmed_interval_mismatch" not in classes(result)
    assert exit_code_for((result,)) == EXIT_CONFIRMED_DRIFT


def test_unknown_evidence_is_not_falsely_confirmed(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-1", locators=("unknown",)),))
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1"),))
    findings = [
        finding for finding in result.findings if finding.classification == "insufficient_evidence"
    ]
    assert findings and not any(finding.confirmed for finding in findings)


def test_invalid_content_hash_has_operational_exit(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-1"),))
    result = analyze_revision(export(tmp_path, graph, content_hash="0" * 64))
    assert "content_hash_mismatch" in classes(result)
    assert exit_code_for((result,)) == EXIT_OPERATIONAL_ERROR


def test_undirected_shape_canonicalizes_endpoint_order() -> None:
    assert logical_shape("owns", EdgeDirection.UNDIRECTED, "a", "b") == logical_shape(
        "owns", EdgeDirection.UNDIRECTED, "b", "a"
    )


def test_multiple_canonical_versions_are_not_mixed(tmp_path: Path) -> None:
    graph = MemoryGraph(
        nodes=(node("a"), node("b")),
        edges=(edge("rel-1"), edge("rel-1-v2", valid_from=T1)),
    )
    assert "confirmed_mixed_identity" not in classes(analyze_revision(export(tmp_path, graph)))


def test_human_output_is_deterministic(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("me-legacy"),))
    result = analyze_revision(export(tmp_path, graph))
    assert render_human((result,)) == render_human((result,))


def test_human_output_preserves_zero_revision_and_empty_tenant(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-1"),))
    result = analyze_revision(
        export(tmp_path, graph),
        (relationship("rel-1"),),
    )
    result = replace(result, tenant_id="", revision_identifier=0)
    rendered = render_human((result,))
    assert "Tenant: \n" in rendered
    assert "Revision: 0" in rendered


def test_json_output_has_stable_schema(tmp_path: Path) -> None:
    graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-1"),))
    result = analyze_revision(export(tmp_path, graph), (relationship("rel-1"),))
    payload = json.loads(render_json((result,)))
    assert list(payload) == ["exit_code", "revisions", "schema_version"]
    assert payload["schema_version"] == 1
    assert set(payload["revisions"][0]) == {
        "calculated_content_hash",
        "findings",
        "revision_identifier",
        "source",
        "stored_content_hash",
        "tenant_id",
    }


def test_exit_code_precedence(tmp_path: Path) -> None:
    legacy_graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("me-legacy"),))
    mismatch_graph = MemoryGraph(nodes=(node("a"), node("b")), edges=(edge("rel-1"),))
    legacy = analyze_revision(export(tmp_path, legacy_graph))
    mismatch = analyze_revision(export(tmp_path, mismatch_graph, content_hash="f" * 64))
    assert exit_code_for((legacy, mismatch)) == EXIT_OPERATIONAL_ERROR


def test_malformed_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"graph_json": {"nodes": "bad", "edges": []}}', encoding="utf-8")
    result = analyze_revision(path)
    assert classes(result) == {"malformed_snapshot"}
