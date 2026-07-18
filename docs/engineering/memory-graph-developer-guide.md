# Enterprise Memory Graph — Developer Guide (FEAT-05-6)

A practical walk-through. Everything is deterministic and immutable; you build
new snapshots rather than mutating.

## 1. Resolve entity mentions (deduplicate identities)

```python
from emg_memory_graph import EntityResolver, ResolutionConfig, EntityMention

cfg = ResolutionConfig(aliases=(("mohd", "mohammed"), ("m", "mohammed")))
result = EntityResolver(cfg).resolve((
    EntityMention(mention_id="m1", entity_type="person", label="Mohammed Al Mansoori"),
    EntityMention(mention_id="m2", entity_type="person", label="Mohd Al Mansoori"),
    EntityMention(mention_id="m3", entity_type="person", label="M. Al Mansoori"),
))
# → one ResolvedEntity; result.canonical_id_for("m2") == result.canonical_id_for("m1")
```

Strategies: `EXACT`, `NORMALIZED`, `ALIAS` (default), and opt-in `RULE` (initials).
No ML — a future ML resolver can implement the `Resolver` protocol.

## 2. Build the graph

From raw inputs:

```python
from datetime import datetime, timezone
from emg_memory_graph import (
    MemoryGraphBuilder, NodeInput, EdgeInput, EvidenceRef, EvidenceSource, TemporalValidity,
)

now = datetime(2024, 6, 1, tzinfo=timezone.utc)
ev = EvidenceRef.create(source=EvidenceSource.MEETING_MINUTES, locator="mtg-42",
                        source_principal="svc-ingest", captured_at=now)

b = MemoryGraphBuilder()
res = b.build(
    nodes=(
        NodeInput(node_id="sara", node_type="person", label="Sara", evidence=(ev,),
                  created_at=now, source="svc-ingest"),
        NodeInput(node_id="dec-1", node_type="decision", label="Adopt EMG", evidence=(ev,),
                  created_at=now, source="svc-ingest"),
    ),
    edges=(
        EdgeInput(edge_type="approved_by", source_id="dec-1", target_id="sara",
                  evidence=(ev,), validity=TemporalValidity(valid_from=now), created_at=now),
    ),
    as_of=now,
)
graph = res.graph
```

Or from the ingestion pipeline's ontology output (no re-ingestion):

```python
res = b.from_ontology(entities=ontology_entities, relationships=ontology_rels, as_of=now)
```

**Deduplication** is automatic: inputs with the same id merge (evidence, aliases,
histories unioned; confidence recomputed). **Incremental**: `b.extend(graph, nodes=…,
edges=…, as_of=…)` — order-independent (`build(A+B) == build(A).extend(B)`).

## 3. Query the memory

```python
from emg_memory_graph import MemoryQueryEngine
q = MemoryQueryEngine(graph)

q.who_approved("dec-1")            # → [RelatedNode(node=Sara, …)]
q.why_decided("dec-1")            # → LineageTrace (backward antecedents)
q.supporting_evidence("dec-1")    # → tuple[EvidenceRef, …]  (node or edge)
q.meetings_discussing("dec-1")
q.participants("mtg-42")
q.affected_projects("risk-1")
q.risks_from_policy("pol-1")
q.historical_owners("proj-1")     # → TemporalHistory | None
q.shortest_path("req-1", "dec-1") # → PathResult (BFS)
```

## 4. Temporal memory (never overwrite)

```python
from emg_memory_graph import TemporalHistory, subgraph_as_of, attribute_at

owner = (TemporalHistory(attribute="owner")
         .with_change(value="ahmed", effective_from=jan_2024, evidence=(ev,), recorded_at=jan_2024)
         .with_change(value="mohammed", effective_from=feb_2025, evidence=(ev,), recorded_at=feb_2025))
owner.as_of(jun_2024).value   # "ahmed"
owner.as_of(jun_2025).value   # "mohammed"

past = subgraph_as_of(graph, jun_2024)         # the graph as it stood then
attribute_at(graph, "proj-1", "owner", jun_2024)
```

## 5. Version the graph

```python
from emg_memory_graph import GraphHistory
history = GraphHistory().commit(graph, at=now)         # revision 1
history = history.commit(res2.graph, at=later)         # revision 2
history.diff(history.revisions[0].revision_id, history.revisions[1].revision_id)
old_graph = history.reconstruct(history.revisions[0].revision_id)
```

## 6. Confidence

Confidence is computed for you by the builder, but you can score directly:

```python
from emg_memory_graph import ConfidenceEngine
a = ConfidenceEngine().assess((ev1, ev2, ev3), as_of=now, conflict_count=0)
a.score, a.band   # more independent sources ⇒ higher; conflicts ⇒ CONFLICTED
```

## 7. Semantic-layer / visualization bridge

```python
from emg_memory_graph import to_semantic_graph, MemoryGraphExecutor
sg = to_semantic_graph(graph)                # emg_semantic_layer.SemanticGraph
MemoryGraphExecutor(graph).execute(query)    # SemanticQuery selection/filter/paging
```

## Conventions & gotchas

- Every node/edge needs ≥ 1 evidence — construction fails otherwise.
- Ids are content-addressed; don't invent random ids if you want dedup.
- Models are frozen; use builder/`extend`/`with_change` to evolve state.
- All outputs are deterministically ordered — safe to snapshot in tests.
