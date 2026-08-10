"""Shared helpers for live persistence integration tests."""

from __future__ import annotations

from typing import Any

from psycopg import Connection

_TRUNCATE_PERSISTENCE_TABLES = """
TRUNCATE TABLE
    mutation_dispatch,
    mutation_ledger_resource,
    mutation_idempotency,
    mutation_ledger,
    projection_checkpoints,
    outbox,
    entity_search_terms,
    entity_search_documents,
    entity_search_representations,
    graph_head,
    graph_revisions,
    evidence_ledger,
    tenants
RESTART IDENTITY
"""


def truncate_persistence_tables(connection: Connection[Any]) -> None:
    """Reset all application-owned PostgreSQL data while preserving the schema."""
    with connection.cursor() as cursor:
        cursor.execute(_TRUNCATE_PERSISTENCE_TABLES)
