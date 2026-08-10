from datetime import datetime, timezone

from emg_common_types import Classification
from emg_knowledge_graph import GraphQueryScope, KnowledgeGraphApplication, SearchEntitiesQuery
from emg_memory_graph import EvidenceRef, EvidenceSource, MemoryGraph, MemoryNode
from emg_platform_core import InMemoryGraphStore, PrincipalRef, TenantId


def _node(node_id, label, aliases=()):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    evidence = (
        EvidenceRef.create(
            source=EvidenceSource.MANUAL_ENTRY,
            locator=node_id,
            source_principal="test",
            captured_at=now,
        ),
    )
    return MemoryNode(
        node_id=node_id,
        node_type="person",
        label=label,
        created_at=now,
        updated_at=now,
        source="test",
        confidence=0.9,
        classification=Classification.INTERNAL,
        evidence=evidence,
        aliases=aliases,
    )


def test_all_tiers_are_deterministic_and_duplicates_collapse():
    tenant = TenantId.of("tenant-a")
    store = InMemoryGraphStore()
    store.write(
        tenant,
        MemoryGraph(
            nodes=(
                _node("alpha", "Other"),
                _node("id-2", "Alpha"),
                _node("id-3", "Other", ("Alpha",)),
                _node("alphabet", "Alpha"),
                _node("id-5", "Alphabet"),
                _node("id-6", "Other", ("Alphabet",)),
            )
        ),
        principal=PrincipalRef.service("test"),
    )
    app = KnowledgeGraphApplication(store, revision_reader=store)
    result = app.search_entities(SearchEntitiesQuery(GraphQueryScope(tenant), " ALPHA "))
    assert [(item.entity.node_id, item.match_kind.value) for item in result.items] == [
        ("alpha", "ID_EXACT"),
        ("alphabet", "LABEL_EXACT"),
        ("id-2", "LABEL_EXACT"),
        ("id-3", "ALIAS_EXACT"),
        ("id-5", "LABEL_PREFIX"),
        ("id-6", "ALIAS_PREFIX"),
    ]


def test_metadata_and_substrings_are_not_searched():
    tenant = TenantId.of("tenant-a")
    store = InMemoryGraphStore()
    store.write(
        tenant,
        MemoryGraph(nodes=(_node("entity-1", "Northwind"),)),
        principal=PrincipalRef.service("test"),
    )
    app = KnowledgeGraphApplication(store, revision_reader=store)
    assert not app.search_entities(SearchEntitiesQuery(GraphQueryScope(tenant), "wind")).items
