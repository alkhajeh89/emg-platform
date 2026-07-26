"""`KnowledgeGraphApplication` wiring for the Query API.

Routes never instantiate `KnowledgeGraphApplication` or a `GraphStore`
themselves — they depend on `KnowledgeGraphApplicationDep`, which composes
the already-wired `GraphStoreDep` (see `store.py`). Both constructor
arguments (`graph_store`, `revision_reader`) receive the same object, since
every backend this service supports implements both Protocols (exactly the
existing `emg_knowledge_graph` test convention — see
`test_query_engine_service.py`'s `_app()` helper).
"""

from __future__ import annotations

from typing import Annotated

from emg_knowledge_graph import KnowledgeGraphApplication
from fastapi import Depends

from .store import GraphStoreDep


def knowledge_graph_application_dependency(
    graph_store: GraphStoreDep,
) -> KnowledgeGraphApplication:
    return KnowledgeGraphApplication(graph_store=graph_store, revision_reader=graph_store)


KnowledgeGraphApplicationDep = Annotated[
    KnowledgeGraphApplication, Depends(knowledge_graph_application_dependency)
]
