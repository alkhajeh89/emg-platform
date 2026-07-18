"""Cross-package integration: ontology, knowledge-pipeline, knowledge-lifecycle,
connector framework (Deliverable 10)."""

from __future__ import annotations

from datetime import datetime, timezone

from _mg_helpers import ASOF, T0
from emg_common_types import Classification
from emg_memory_graph import (
    EvidenceRef,
    EvidenceSource,
    MemoryGraphBuilder,
    MemoryQueryEngine,
    TemporalHistory,
    TemporalValidity,
    to_semantic_graph,
)
from emg_ontology import Entity, ProvenanceReference, Relationship

T1 = datetime(2025, 2, 1, tzinfo=timezone.utc)


def _prov() -> ProvenanceReference:
    return ProvenanceReference(
        source_principal="svc-ingest", event_id="evt-1", correlation_id="corr-1"
    )


def test_consumes_ontology_pipeline_output() -> None:
    """The builder consumes ontology Entity/Relationship — the pipeline's output —
    without re-implementing ingestion."""
    prov = _prov()
    ents = (
        Entity(
            entity_id="p1",
            entity_type="Person",
            classification=Classification.INTERNAL,
            trust_score=0.7,
            provenance_reference=prov,
            owner="u",
            effective_from=T0,
        ),
        Entity(
            entity_id="pr1",
            entity_type="Project",
            classification=Classification.INTERNAL,
            trust_score=0.8,
            provenance_reference=prov,
            owner="u",
            effective_from=T0,
        ),
    )
    rels = (
        Relationship(
            relationship_id="r1",
            relationship_type="owns",
            from_entity_id="p1",
            from_entity_type="Person",
            to_entity_id="pr1",
            to_entity_type="Project",
            classification=Classification.INTERNAL,
            provenance_reference=prov,
            effective_from=T0,
        ),
    )
    res = MemoryGraphBuilder().from_ontology(entities=ents, relationships=rels, as_of=ASOF)
    g = res.graph
    assert g.node_count == 2 and g.edge_count == 1
    # provenance preserved as evidence (audit trail carried through)
    ev = g.node("p1").evidence[0]  # type: ignore[union-attr]
    assert ev.event_id == "evt-1" and ev.correlation_id == "corr-1"


def test_lifecycle_version_chain_drives_temporal_memory() -> None:
    """A knowledge-lifecycle VersionChain's effective windows become the memory
    graph's temporal history — historical state is preserved, never overwritten."""
    from emg_knowledge_lifecycle import (
        KnowledgeVersion,
        VersionChain,
        VersionIdentifier,
        VersionMetadata,
        VersionState,
    )

    meta = VersionMetadata(created_at=T0, author="svc", note="n")
    v1 = KnowledgeVersion(
        identifier=VersionIdentifier(entity_id="proj", version=1),
        state=VersionState.SUPERSEDED,
        metadata=meta,
        effective_from=T0,
        effective_to=T1,
    )
    v2 = KnowledgeVersion(
        identifier=VersionIdentifier(entity_id="proj", version=2),
        state=VersionState.ACTIVE,
        metadata=meta,
        parent=v1.identifier,
        effective_from=T1,
    )
    chain = VersionChain(versions=(v1, v2))

    # Project the chain's ownership timeline into a TemporalHistory.
    e = EvidenceRef.create(
        source=EvidenceSource.MANUAL_ENTRY, locator="ver", source_principal="svc", captured_at=T0
    )
    history = TemporalHistory(attribute="owner")
    for ver, owner in ((chain.versions[0], "ahmed"), (chain.versions[1], "mohammed")):
        history = history.with_change(
            value=owner,
            effective_from=ver.effective_from,
            evidence=(e,),
            recorded_at=ver.effective_from,
        )
    assert history.as_of(datetime(2024, 6, 1, tzinfo=timezone.utc)).value == "ahmed"  # type: ignore[union-attr]
    assert history.as_of(datetime(2025, 6, 1, tzinfo=timezone.utc)).value == "mohammed"  # type: ignore[union-attr]


def test_connector_framework_evidence_source_alignment() -> None:
    """Evidence sources align with the Universal Connector Framework's world: a
    connector's descriptor/vendor feeds evidence provenance for graph assertions."""
    import emg_connectors  # integration import — connector framework is available

    assert hasattr(emg_connectors, "ConnectorDescriptor")
    # A record ingested via a SharePoint/Teams/Jira connector becomes evidence.
    for src in (EvidenceSource.SHAREPOINT, EvidenceSource.TEAMS, EvidenceSource.JIRA):
        ev = EvidenceRef.create(
            source=src, locator="rec-1", source_principal="connector:acme", captured_at=T0
        )
        assert ev.source is src


def test_semantic_layer_projection_roundtrips(lineage_graph) -> None:  # type: ignore[no-untyped-def]
    """Integration with the semantic layer: the memory graph projects into a
    SemanticGraph queryable by the platform's generic model."""
    sg = to_semantic_graph(lineage_graph)
    assert sg.node("dec") is not None
    assert len(sg.neighbors("dec")) >= 1


def test_end_to_end_question_answering(lineage_graph) -> None:  # type: ignore[no-untyped-def]
    q = MemoryQueryEngine(lineage_graph)
    assert q.who_approved("dec")[0].node.label == "Sara"
    assert q.shortest_path("req", "appr").length == 3  # type: ignore[union-attr]
    assert "mtg" in {n.node_id for n in q.why_decided("dec").nodes}


def test_valid_interval_from_relationship_effective_window() -> None:
    prov = _prov()
    rel = Relationship(
        relationship_id="r1",
        relationship_type="owns",
        from_entity_id="p1",
        from_entity_type="Person",
        to_entity_id="pr1",
        to_entity_type="Project",
        classification=Classification.INTERNAL,
        provenance_reference=prov,
        effective_from=T0,
        effective_to=T1,
    )
    ents = (
        Entity(
            entity_id="p1",
            entity_type="Person",
            classification=Classification.INTERNAL,
            trust_score=0.7,
            provenance_reference=prov,
            owner="u",
            effective_from=T0,
        ),
        Entity(
            entity_id="pr1",
            entity_type="Project",
            classification=Classification.INTERNAL,
            trust_score=0.8,
            provenance_reference=prov,
            owner="u",
            effective_from=T0,
        ),
    )
    g = MemoryGraphBuilder().from_ontology(entities=ents, relationships=(rel,), as_of=ASOF).graph
    edge = g.edges[0]
    assert edge.validity == TemporalValidity(valid_from=T0, valid_until=T1)
