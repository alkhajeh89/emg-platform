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
from emg_knowledge_lifecycle import (
    LIVE_STATES,
    InvalidTransitionError,
    VersionState,
    is_valid_transition,
)
from emg_ontology import Entity, Relationship, classification_rank
from pydantic import BaseModel, ConfigDict, Field

from .confidence import ConfidenceEngine
from .edges import MemoryEdge
from .enums import EdgeDirection, EvidenceSource
from .errors import EdgeNotFoundError, MergeConflictError, NodeNotFoundError
from .evidence import EvidenceRef
from .graph import MemoryGraph
from .ids import edge_id_for
from .labels import SafeLabel, SafeText
from .limits import MAX_SUPERSEDES
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
    relationship_id: SafeLabel | None = None

    def edge_id(self) -> str:
        """Canonical relationship id, or a deterministic fallback for raw input."""
        if self.relationship_id is not None:
            return self.relationship_id
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

    def replace(
        self,
        base: MemoryGraph,
        *,
        node: MemoryNode | None = None,
        edge: MemoryEdge | None = None,
        close_edge_id: str | None = None,
        merge_survivor_id: str | None = None,
        merge_source_ids: tuple[str, ...] = (),
        as_of: datetime,
    ) -> BuildResult:
        """Construct one immutable replacement snapshot.

        Exactly one mode is accepted: replace a node, replace an edge, close an
        edge's validity, or merge one or more live source nodes into a live
        survivor. This path is deliberately separate from ingestion merging.
        """
        merge_requested = merge_survivor_id is not None or bool(merge_source_ids)
        modes = sum(
            (
                node is not None,
                edge is not None,
                close_edge_id is not None,
                merge_requested,
            )
        )
        if modes != 1:
            raise MergeConflictError("replace requires exactly one construction mode")

        if node is not None:
            return self._replace_node(base, node)
        if edge is not None:
            return self._replace_edge(base, edge)
        if close_edge_id is not None:
            return self._close_relationship(base, close_edge_id, as_of)
        if merge_survivor_id is None or not merge_source_ids:
            raise MergeConflictError("merge requires a survivor and at least one source")
        return self._merge_entities(base, merge_survivor_id, merge_source_ids, as_of)

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
                    relationship_id=rel.relationship_id,
                )
            )
        if base is not None:
            result = self.extend(
                base, nodes=tuple(node_inputs), edges=tuple(edge_inputs), as_of=as_of
            )
        else:
            result = self.build(nodes=tuple(node_inputs), edges=tuple(edge_inputs), as_of=as_of)
        owner_by_id = {entity.entity_id: entity.owner for entity in entities}
        nodes = tuple(
            (
                MemoryNode.model_validate(
                    {
                        **node.model_dump(),
                        "owner": owner_by_id[node.node_id],
                    }
                )
                if not node.owner and node.node_id in owner_by_id
                else node
            )
            for node in result.graph.nodes
        )
        graph = MemoryGraph(nodes=nodes, edges=result.graph.edges)
        return BuildResult(
            graph=graph,
            nodes_created=result.nodes_created,
            edges_created=result.edges_created,
            node_inputs_merged=result.node_inputs_merged,
            edge_inputs_merged=result.edge_inputs_merged,
        )

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

    def _replace_node(self, base: MemoryGraph, replacement: MemoryNode) -> BuildResult:
        current = base.node(replacement.node_id)
        if current is None:
            raise NodeNotFoundError(f"node {replacement.node_id!r} is not in the graph")
        self._validate_owner(replacement)
        if current.owner and replacement.owner != current.owner:
            raise MergeConflictError(f"node {replacement.node_id!r} cannot change immutable owner")
        if replacement.supersedes != current.supersedes:
            raise MergeConflictError(
                f"node {replacement.node_id!r} supersedes may only change during merge"
            )
        self._validate_lifecycle_transition(current, replacement)

        nodes = {item.node_id: item for item in base.nodes}
        nodes[replacement.node_id] = replacement
        graph = MemoryGraph(nodes=tuple(nodes.values()), edges=base.edges)
        self._validate_supersession(graph)
        return self._replacement_result(graph)

    def _replace_edge(self, base: MemoryGraph, replacement: MemoryEdge) -> BuildResult:
        current = base.edge(replacement.edge_id)
        if current is None:
            raise EdgeNotFoundError(f"edge {replacement.edge_id!r} is not in the graph")
        if (replacement.source_id, replacement.target_id) != (
            current.source_id,
            current.target_id,
        ):
            raise MergeConflictError(
                f"edge {replacement.edge_id!r} cannot change immutable endpoints"
            )

        edges = {item.edge_id: item for item in base.edges}
        edges[replacement.edge_id] = replacement
        graph = MemoryGraph(nodes=base.nodes, edges=tuple(edges.values()))
        self._validate_supersession(graph)
        return self._replacement_result(graph)

    def _close_relationship(self, base: MemoryGraph, edge_id: str, as_of: datetime) -> BuildResult:
        current = base.edge(edge_id)
        if current is None:
            raise EdgeNotFoundError(f"edge {edge_id!r} is not in the graph")
        closed = self._close_edge(current, as_of)
        return self._replace_edge(base, closed)

    def _merge_entities(
        self,
        base: MemoryGraph,
        survivor_id: str,
        source_ids: tuple[str, ...],
        as_of: datetime,
    ) -> BuildResult:
        unique_source_ids = tuple(sorted(set(source_ids)))
        if len(unique_source_ids) != len(source_ids):
            raise MergeConflictError("merge source node ids must be unique")
        if survivor_id in unique_source_ids:
            raise MergeConflictError("a merge survivor cannot supersede itself")

        survivor = base.node(survivor_id)
        if survivor is None:
            raise NodeNotFoundError(f"survivor node {survivor_id!r} is not in the graph")
        sources: list[MemoryNode] = []
        for source_id in unique_source_ids:
            source = base.node(source_id)
            if source is None:
                raise NodeNotFoundError(f"source node {source_id!r} is not in the graph")
            sources.append(source)

        participants = (survivor, *sources)
        for participant in participants:
            self._validate_owner(participant)
            if participant.lifecycle_status not in LIVE_STATES:
                raise MergeConflictError(
                    f"node {participant.node_id!r} is not live and cannot participate in merge"
                )

        supersedes = tuple(sorted((*survivor.supersedes, *unique_source_ids)))
        if len(supersedes) > MAX_SUPERSEDES:
            raise MergeConflictError(f"merge exceeds supersedes limit (max {MAX_SUPERSEDES})")
        if len(supersedes) != len(set(supersedes)):
            raise MergeConflictError("merge would duplicate a supersedes reference")

        evidence = _merge_evidence(*(item.evidence for item in participants))
        aliases = tuple(
            sorted({alias for participant in participants for alias in participant.aliases})
        )
        histories = {
            history.attribute: history for source in sources for history in source.histories
        }
        histories.update({history.attribute: history for history in survivor.histories})
        metadata_items = list(survivor.metadata.items)
        for source in sources:
            metadata_items.extend(source.metadata.items)
        classification = max(
            (item.classification for item in participants),
            key=classification_rank,
        )
        replacement_survivor = MemoryNode.model_validate(
            {
                **survivor.model_dump(),
                "updated_at": max(survivor.updated_at, as_of),
                "classification": classification,
                "evidence": evidence,
                "aliases": aliases,
                "histories": tuple(histories.values()),
                "metadata": _merge_metadata(metadata_items),
                "supersedes": supersedes,
            }
        )

        replacement_sources: list[MemoryNode] = []
        for source in sources:
            if not is_valid_transition(source.lifecycle_status, VersionState.SUPERSEDED):
                raise InvalidTransitionError(
                    f"invalid lifecycle transition "
                    f"{source.lifecycle_status.value}->{VersionState.SUPERSEDED.value}"
                )
            replacement_sources.append(
                MemoryNode.model_validate(
                    {
                        **source.model_dump(),
                        "lifecycle_status": VersionState.SUPERSEDED,
                    }
                )
            )

        nodes = {item.node_id: item for item in base.nodes}
        nodes[survivor_id] = replacement_survivor
        nodes.update({item.node_id: item for item in replacement_sources})
        edges = {item.edge_id: item for item in base.edges}
        created_edges: dict[str, MemoryEdge] = {}
        source_id_set = set(unique_source_ids)
        for current in base.edges:
            if not ({current.source_id, current.target_id} & source_id_set):
                continue
            if not current.is_active_at(as_of):
                continue
            closed = self._close_edge(current, as_of)
            edges[current.edge_id] = closed
            source_id = survivor_id if current.source_id in source_id_set else current.source_id
            target_id = survivor_id if current.target_id in source_id_set else current.target_id
            if source_id == target_id:
                raise MergeConflictError(
                    f"edge {current.edge_id!r} would become a self-loop after merge"
                )
            new_edge_id = self._edge_id_for_reassignment(
                current.edge_type,
                source_id,
                target_id,
                current.direction,
            )
            if new_edge_id in edges or new_edge_id in created_edges:
                raise MergeConflictError(
                    f"reassigned edge {new_edge_id!r} collides with an existing edge"
                )
            created_edges[new_edge_id] = MemoryEdge.model_validate(
                {
                    **current.model_dump(),
                    "edge_id": new_edge_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "validity": TemporalValidity(
                        valid_from=as_of,
                        valid_until=current.validity.valid_until,
                    ),
                    "created_at": as_of,
                    "updated_at": as_of,
                }
            )
        edges.update(created_edges)

        graph = MemoryGraph(nodes=tuple(nodes.values()), edges=tuple(edges.values()))
        self._validate_supersession(graph)
        return self._replacement_result(graph, edges_created=len(created_edges))

    @staticmethod
    def _validate_owner(node: MemoryNode) -> None:
        if not node.owner or not node.owner.strip():
            raise MergeConflictError(f"node {node.node_id!r} requires an owner")

    @staticmethod
    def _validate_lifecycle_transition(current: MemoryNode, replacement: MemoryNode) -> None:
        if current.lifecycle_status is replacement.lifecycle_status:
            return
        if not is_valid_transition(current.lifecycle_status, replacement.lifecycle_status):
            raise InvalidTransitionError(
                f"invalid lifecycle transition "
                f"{current.lifecycle_status.value}->{replacement.lifecycle_status.value}"
            )

    @staticmethod
    def _validate_supersession(graph: MemoryGraph) -> None:
        claimed_by: dict[str, str] = {}
        for node in graph.nodes:
            if len(node.supersedes) > MAX_SUPERSEDES:
                raise MergeConflictError(
                    f"node {node.node_id!r} exceeds supersedes limit (max {MAX_SUPERSEDES})"
                )
            for source_id in node.supersedes:
                if not graph.has_node(source_id):
                    raise MergeConflictError(
                        f"node {node.node_id!r} supersedes missing node {source_id!r}"
                    )
                prior = claimed_by.get(source_id)
                if prior is not None and prior != node.node_id:
                    raise MergeConflictError(
                        f"node {source_id!r} is superseded by both "
                        f"{prior!r} and {node.node_id!r}"
                    )
                claimed_by[source_id] = node.node_id

    @staticmethod
    def _close_edge(edge: MemoryEdge, as_of: datetime) -> MemoryEdge:
        if not edge.is_active_at(as_of) or as_of == edge.validity.valid_from:
            raise MergeConflictError(f"edge {edge.edge_id!r} is not active at closure time")
        return MemoryEdge.model_validate(
            {
                **edge.model_dump(),
                "validity": TemporalValidity(
                    valid_from=edge.validity.valid_from,
                    valid_until=as_of,
                ),
                "updated_at": max(edge.updated_at, as_of),
            }
        )

    @staticmethod
    def _edge_id_for_reassignment(
        edge_type: str,
        source_id: str,
        target_id: str,
        direction: EdgeDirection,
    ) -> str:
        if direction is EdgeDirection.UNDIRECTED and target_id < source_id:
            source_id, target_id = target_id, source_id
        return edge_id_for(edge_type, source_id, target_id)

    @staticmethod
    def _replacement_result(graph: MemoryGraph, *, edges_created: int = 0) -> BuildResult:
        return BuildResult(
            graph=graph,
            nodes_created=0,
            edges_created=edges_created,
            node_inputs_merged=0,
            edge_inputs_merged=0,
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
        self._validate_edge_group(edge_id, group, existing)
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

    @staticmethod
    def _validate_edge_group(
        edge_id: str,
        group: list[EdgeInput],
        existing: MemoryEdge | None,
    ) -> None:
        candidates: list[EdgeInput | MemoryEdge] = [*group]
        if existing is not None:
            candidates.insert(0, existing)

        expected = _edge_immutable_fields(candidates[0])
        for candidate in candidates[1:]:
            actual = _edge_immutable_fields(candidate)
            conflicts = sorted(name for name in expected if expected[name] != actual[name])
            if conflicts:
                raise MergeConflictError(
                    f"edge {edge_id!r} has conflicting immutable attributes: "
                    f"{', '.join(conflicts)}"
                )


def _edge_immutable_fields(edge: EdgeInput | MemoryEdge) -> dict[str, object]:
    source_id, target_id = edge.source_id, edge.target_id
    if edge.direction is EdgeDirection.UNDIRECTED and target_id < source_id:
        source_id, target_id = target_id, source_id
    return {
        "edge_type": edge.edge_type,
        "endpoints": (source_id, target_id),
        "direction": edge.direction,
        "validity": edge.validity,
        "classification": edge.classification,
    }
