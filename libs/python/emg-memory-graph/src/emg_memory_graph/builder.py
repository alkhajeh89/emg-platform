"""Deterministic Enterprise Memory Graph builder (FEAT-05-6, Deliverable 2).

Turns knowledge objects — either raw ``NodeInput``/``EdgeInput`` bundles or the
ontology ``Entity``/``Relationship`` objects produced by the ingestion pipeline —
into an immutable `MemoryGraph`. The build is a pure function of its inputs:

  * **Create nodes / edges** from the inputs.
  * **Deduplicate**: inputs that resolve to the same id are merged (evidence,
    aliases and temporal histories are unioned; the earliest ``created_at`` and
    latest ``updated_at`` win). This is how "duplicate observations" collapse.
  * **Preserve provenance**: evidence is carried through unchanged and immutable.
  * **Preserve history**: each input keeps its own temporal validity, so an
    "owner changed" scenario becomes two edges with adjacent valid intervals,
    never an overwrite.
  * **Score confidence** for every node and edge via the `ConfidenceEngine`.
  * **Incremental updates**: ``extend`` merges new inputs into an existing graph
    with identical merge semantics, so the result is independent of whether the
    data arrived in one batch or several.

Complexity: O(N + E) over the inputs plus the confidence scoring per element.
Ingestion logic is NOT duplicated — this consumes the pipeline's output.
"""

from __future__ import annotations

from datetime import datetime

from emg_common_types import Classification
from emg_ontology import Entity, Relationship
from pydantic import BaseModel, ConfigDict, Field

from .confidence import ConfidenceEngine
from .edges import MemoryEdge
from .enums import EdgeDirection, EvidenceSource
from .evidence import EvidenceRef
from .graph import MemoryGraph
from .ids import edge_id_for
from .labels import SafeLabel, SafeText
from .metadata import Metadata, MetadataItem
from .nodes import MemoryNode
from .temporal import TemporalHistory, TemporalValidity


class NodeInput(BaseModel):
    """A knowledge object that produces (or contributes to) one node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: SafeLabel
    node_type: SafeLabel
    label: SafeText
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    created_at: datetime
    updated_at: datetime | None = None
    source: SafeLabel
    classification: Classification = Classification.INTERNAL
    aliases: tuple[SafeText, ...] = ()
    histories: tuple[TemporalHistory, ...] = ()
    ontology_entity_id: SafeLabel | None = None
    conflict_count: int = Field(default=0, ge=0)
    metadata: Metadata = Metadata()


class EdgeInput(BaseModel):
    """A knowledge object that produces (or contributes to) one edge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge_type: SafeLabel
    source_id: SafeLabel
    target_id: SafeLabel
    direction: EdgeDirection = EdgeDirection.DIRECTED
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    validity: TemporalValidity
    created_at: datetime
    updated_at: datetime | None = None
    classification: Classification = Classification.INTERNAL
    conflict_count: int = Field(default=0, ge=0)
    metadata: Metadata = Metadata()

    def edge_id(self) -> str:
        """Deterministic edge id. Undirected edges canonicalize endpoint order so
        both orientations collapse to one id."""
        a, b = self.source_id, self.target_id
        if self.direction is EdgeDirection.UNDIRECTED and b < a:
            a, b = b, a
        return edge_id_for(self.edge_type, a, b)


class BuildResult(BaseModel):
    """The immutable outcome of a build/extend: the graph plus merge statistics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    graph: MemoryGraph
    nodes_created: int = Field(ge=0)
    edges_created: int = Field(ge=0)
    node_inputs_merged: int = Field(ge=0)
    edge_inputs_merged: int = Field(ge=0)


def _merge_evidence(*groups: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    by_id = {e.evidence_id: e for group in groups for e in group}
    return tuple(sorted(by_id.values(), key=lambda e: e.evidence_id))


def _merge_metadata(items: list[MetadataItem]) -> Metadata:
    """Collapse (possibly conflicting) metadata items by key, last-write-wins, so
    a merge never fails on a duplicate key. Deterministic given input order."""
    collapsed = {it.key: it.value for it in items}
    return Metadata.from_mapping(collapsed)


class MemoryGraphBuilder:
    """Deterministic builder. Stateless across calls; construct once and reuse."""

    def __init__(self, confidence_engine: ConfidenceEngine | None = None) -> None:
        self._confidence = confidence_engine or ConfidenceEngine()

    # --- primary API ---------------------------------------------------------
    def build(
        self,
        *,
        nodes: tuple[NodeInput, ...] = (),
        edges: tuple[EdgeInput, ...] = (),
        as_of: datetime,
    ) -> BuildResult:
        """Build a graph from scratch."""
        return self._assemble(base_nodes=(), base_edges=(), nodes=nodes, edges=edges, as_of=as_of)

    def extend(
        self,
        base: MemoryGraph,
        *,
        nodes: tuple[NodeInput, ...] = (),
        edges: tuple[EdgeInput, ...] = (),
        as_of: datetime,
    ) -> BuildResult:
        """Incrementally merge new inputs into an existing graph. The merge is
        order-independent: building A then extending with B yields the same graph
        as building A+B in one pass."""
        return self._assemble(
            base_nodes=base.nodes, base_edges=base.edges, nodes=nodes, edges=edges, as_of=as_of
        )

    # --- ontology integration ------------------------------------------------
    def from_ontology(
        self,
        *,
        entities: tuple[Entity, ...] = (),
        relationships: tuple[Relationship, ...] = (),
        evidence_source: EvidenceSource = EvidenceSource.MANUAL_ENTRY,
        labels: dict[str, str] | None = None,
        as_of: datetime,
        base: MemoryGraph | None = None,
    ) -> BuildResult:
        """Build (or extend) from ontology `Entity`/`Relationship` objects — the
        ingestion pipeline's output. Evidence is synthesized from each object's
        `provenance_reference` (source principal, event id, correlation id) so the
        pipeline's audit trail becomes the graph's evidence, with no re-ingestion.
        """
        labels = labels or {}
        node_inputs: list[NodeInput] = []
        for entity in entities:
            ev = EvidenceRef.from_provenance(
                entity.provenance_reference,
                source=evidence_source,
                locator=entity.entity_id,
                captured_at=as_of,
            )
            node_inputs.append(
                NodeInput(
                    node_id=entity.entity_id,
                    node_type=entity.entity_type,
                    label=labels.get(entity.entity_id, entity.entity_id),
                    evidence=(ev,),
                    created_at=entity.effective_from,
                    updated_at=as_of,
                    source=entity.provenance_reference.source_principal,
                    classification=entity.classification,
                    ontology_entity_id=entity.entity_id,
                )
            )
        edge_inputs: list[EdgeInput] = []
        for rel in relationships:
            ev = EvidenceRef.from_provenance(
                rel.provenance_reference,
                source=evidence_source,
                locator=rel.relationship_id,
                captured_at=as_of,
            )
            edge_inputs.append(
                EdgeInput(
                    edge_type=rel.relationship_type,
                    source_id=rel.from_entity_id,
                    target_id=rel.to_entity_id,
                    evidence=(ev,),
                    validity=TemporalValidity(
                        valid_from=rel.effective_from, valid_until=rel.effective_to
                    ),
                    created_at=rel.effective_from,
                    updated_at=as_of,
                    classification=rel.classification,
                )
            )
        if base is not None:
            return self.extend(
                base, nodes=tuple(node_inputs), edges=tuple(edge_inputs), as_of=as_of
            )
        return self.build(nodes=tuple(node_inputs), edges=tuple(edge_inputs), as_of=as_of)

    # --- internals -----------------------------------------------------------
    def _assemble(
        self,
        *,
        base_nodes: tuple[MemoryNode, ...],
        base_edges: tuple[MemoryEdge, ...],
        nodes: tuple[NodeInput, ...],
        edges: tuple[EdgeInput, ...],
        as_of: datetime,
    ) -> BuildResult:
        # ---- nodes: group by node_id (base first, then inputs) --------------
        node_groups: dict[str, list[NodeInput]] = {}
        base_node_by_id = {n.node_id: n for n in base_nodes}
        for ni in nodes:
            node_groups.setdefault(ni.node_id, []).append(ni)

        merged_node_inputs = sum(len(g) - 1 for g in node_groups.values() if len(g) > 1)
        out_nodes: dict[str, MemoryNode] = dict(base_node_by_id)
        created_nodes = 0
        for node_id, group in node_groups.items():
            existing = base_node_by_id.get(node_id)
            merged = self._merge_node(node_id, group, existing, as_of)
            if existing is None:
                created_nodes += 1
            out_nodes[node_id] = merged

        # ---- edges: group by deterministic edge_id --------------------------
        edge_groups: dict[str, list[EdgeInput]] = {}
        base_edge_by_id = {e.edge_id: e for e in base_edges}
        for ei in edges:
            edge_groups.setdefault(ei.edge_id(), []).append(ei)

        merged_edge_inputs = sum(len(g) - 1 for g in edge_groups.values() if len(g) > 1)
        out_edges: dict[str, MemoryEdge] = dict(base_edge_by_id)
        created_edges = 0
        for edge_id, edge_group in edge_groups.items():
            existing_edge = base_edge_by_id.get(edge_id)
            merged_edge = self._merge_edge(edge_id, edge_group, existing_edge, as_of)
            if existing_edge is None:
                created_edges += 1
            out_edges[edge_id] = merged_edge

        graph = MemoryGraph(nodes=tuple(out_nodes.values()), edges=tuple(out_edges.values()))
        return BuildResult(
            graph=graph,
            nodes_created=created_nodes,
            edges_created=created_edges,
            node_inputs_merged=merged_node_inputs,
            edge_inputs_merged=merged_edge_inputs,
        )

    def _merge_node(
        self,
        node_id: str,
        group: list[NodeInput],
        existing: MemoryNode | None,
        as_of: datetime,
    ) -> MemoryNode:
        evidence_groups: list[tuple[EvidenceRef, ...]] = [g.evidence for g in group]
        aliases: set[str] = set()
        histories: dict[str, TemporalHistory] = {}
        metadata_items: list[MetadataItem] = []
        created_candidates: list[datetime] = []
        updated_candidates: list[datetime] = []
        conflicts = 0
        rep = group[0]
        if existing is not None:
            evidence_groups.append(existing.evidence)
            aliases.update(existing.aliases)
            histories.update({h.attribute: h for h in existing.histories})
            metadata_items.extend(existing.metadata.items)
            created_candidates.append(existing.created_at)
            updated_candidates.append(existing.updated_at)
        for g in group:
            aliases.update(g.aliases)
            for h in g.histories:
                histories[h.attribute] = h  # last write wins per attribute (deterministic order)
            metadata_items.extend(g.metadata.items)
            created_candidates.append(g.created_at)
            updated_candidates.append(g.updated_at or g.created_at)
            conflicts += g.conflict_count
        evidence = _merge_evidence(*evidence_groups)
        assessment = self._confidence.assess(evidence, as_of=as_of, conflict_count=conflicts)
        return MemoryNode(
            node_id=node_id,
            node_type=rep.node_type,
            label=(existing.label if existing is not None else rep.label),
            created_at=min(created_candidates),
            updated_at=max(updated_candidates),
            source=rep.source,
            confidence=assessment.score,
            classification=rep.classification,
            evidence=evidence,
            aliases=tuple(sorted(aliases)),
            histories=tuple(histories.values()),
            ontology_entity_id=rep.ontology_entity_id
            or (existing.ontology_entity_id if existing else None),
            metadata=_merge_metadata(metadata_items),
        )

    def _merge_edge(
        self,
        edge_id: str,
        group: list[EdgeInput],
        existing: MemoryEdge | None,
        as_of: datetime,
    ) -> MemoryEdge:
        evidence_groups: list[tuple[EvidenceRef, ...]] = [g.evidence for g in group]
        metadata_items: list[MetadataItem] = []
        created_candidates: list[datetime] = []
        updated_candidates: list[datetime] = []
        conflicts = 0
        rep = group[0]
        if existing is not None:
            evidence_groups.append(existing.evidence)
            metadata_items.extend(existing.metadata.items)
            created_candidates.append(existing.created_at)
            updated_candidates.append(existing.updated_at)
        for g in group:
            metadata_items.extend(g.metadata.items)
            created_candidates.append(g.created_at)
            updated_candidates.append(g.updated_at or g.created_at)
            conflicts += g.conflict_count
        evidence = _merge_evidence(*evidence_groups)
        assessment = self._confidence.assess(evidence, as_of=as_of, conflict_count=conflicts)
        validity = existing.validity if existing is not None else rep.validity
        return MemoryEdge(
            edge_id=edge_id,
            edge_type=rep.edge_type,
            source_id=rep.source_id,
            target_id=rep.target_id,
            direction=rep.direction,
            evidence=evidence,
            confidence=assessment.score,
            validity=validity,
            created_at=min(created_candidates),
            updated_at=max(updated_candidates),
            classification=rep.classification,
            metadata=_merge_metadata(metadata_items),
        )
