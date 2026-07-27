"""Composition root for ADR-030's shared PostgreSQL atomic unit."""

from __future__ import annotations

from emg_knowledge_graph import KnowledgeGraphApplication, MutationAuthorizationHook
from emg_persistence import PersistenceSettings
from emg_persistence.postgres import (
    ContextBoundTransactionProvider,
    DirectConnectionProvider,
    PostgresOutboxRepository,
    PostgresRevisionRepository,
)
from emg_persistence.store import PostgresNeo4jGraphStore

from .atomic_mutation import PostgresAtomicMutationExecution


def build_atomic_knowledge_graph_application(
    settings: PersistenceSettings,
    *,
    mutation_authorization_hook: MutationAuthorizationHook | None = None,
) -> KnowledgeGraphApplication:
    """Build GraphStore and ledger adapter over the same transaction provider."""
    connections = DirectConnectionProvider(settings)
    transactions = ContextBoundTransactionProvider(connections)
    store = PostgresNeo4jGraphStore(
        transactions,
        repository_factory=PostgresRevisionRepository,
        outbox_repository_factory=PostgresOutboxRepository,
    )
    atomic_mutations = PostgresAtomicMutationExecution(transactions)
    return KnowledgeGraphApplication(
        store,
        revision_reader=store,
        mutation_authorization_hook=mutation_authorization_hook,
        atomic_mutation_execution=atomic_mutations,
    )
