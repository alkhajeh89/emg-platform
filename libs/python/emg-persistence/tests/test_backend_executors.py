"""Backend executor pure surface: kind, Protocol conformance, cypher splitting.

The database-touching methods are integration-tested (CI persistence job); here
we cover only what is testable without a live datastore.
"""

from __future__ import annotations

from emg_persistence.migrations import MigrationExecutor, MigrationKind
from emg_persistence.neo4j import Neo4jMigrationExecutor, split_cypher_statements
from emg_persistence.postgres import PostgresMigrationExecutor


def test_postgres_executor_kind_and_protocol() -> None:
    ex = PostgresMigrationExecutor(connection=object())  # type: ignore[arg-type]
    assert ex.kind is MigrationKind.POSTGRES
    assert isinstance(ex, MigrationExecutor)


def test_neo4j_executor_kind_and_protocol() -> None:
    ex = Neo4jMigrationExecutor(driver=object())  # type: ignore[arg-type]
    assert ex.kind is MigrationKind.NEO4J
    assert isinstance(ex, MigrationExecutor)


def test_split_cypher_statements_basic() -> None:
    text = "CREATE CONSTRAINT a IF NOT EXISTS ...;\nCREATE INDEX b IF NOT EXISTS ...;"
    assert split_cypher_statements(text) == (
        "CREATE CONSTRAINT a IF NOT EXISTS ...",
        "CREATE INDEX b IF NOT EXISTS ...",
    )


def test_split_cypher_drops_comments_and_blanks() -> None:
    text = "// a comment\nCREATE X;\n\n  \n// trailing\n;"
    assert split_cypher_statements(text) == ("CREATE X",)


def test_split_cypher_empty() -> None:
    assert split_cypher_statements("// only a comment\n;  ;") == ()
