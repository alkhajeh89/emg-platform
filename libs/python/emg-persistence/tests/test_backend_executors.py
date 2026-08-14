"""Backend executor pure surface: kind, Protocol conformance, cypher splitting.

The database-touching methods are integration-tested (CI persistence job); here
we cover only what is testable without a live datastore.
"""

from __future__ import annotations

from pathlib import Path

from emg_persistence.migrations import MigrationExecutor, MigrationKind
from emg_persistence.neo4j import Neo4jMigrationExecutor, split_cypher_statements
from emg_persistence.postgres import PostgresMigrationExecutor

_M001_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "emg_persistence"
    / "migrations"
    / "neo4j"
    / "M001__constraints.cypher"
)


def test_postgres_executor_kind_and_protocol() -> None:
    ex = PostgresMigrationExecutor(connection=object())  # type: ignore[arg-type]
    assert ex.kind is MigrationKind.POSTGRES
    assert isinstance(ex, MigrationExecutor)


def test_postgres_executor_supports_isolated_audit_history_namespace() -> None:
    ex = PostgresMigrationExecutor(
        connection=object(), history_table="audit_schema_migrations"  # type: ignore[arg-type]
    )
    assert ex._history_table == "audit_schema_migrations"
    assert '"audit_schema_migrations"' in ex._history_ddl


def test_postgres_executor_supports_schema_qualified_identity_history_namespace() -> None:
    ex = PostgresMigrationExecutor(
        connection=object(),  # type: ignore[arg-type]
        history_table="emg_identity.identity_schema_migrations",
    )
    assert ex._history_table == "emg_identity.identity_schema_migrations"
    assert '"emg_identity"."identity_schema_migrations"' in ex._history_ddl


def test_postgres_executor_rejects_unsafe_history_identifier() -> None:
    import pytest

    with pytest.raises(ValueError, match="safe identifiers"):
        PostgresMigrationExecutor(
            connection=object(), history_table="schema_migrations; DROP TABLE audit_events"  # type: ignore[arg-type]
        )


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


def test_split_cypher_full_line_comment_containing_a_semicolon() -> None:
    """A full-line comment whose prose contains ';' must not fracture the
    following statement (the exact M001 defect: 'no enterprise-only' leaking
    into the next CREATE CONSTRAINT because the comment was cut in half by a
    naive text.split(';') performed before comment stripping)."""
    text = "// compatible (uniqueness constraints + indexes only; no enterprise-only\nCREATE X;"
    assert split_cypher_statements(text) == ("CREATE X",)


def test_split_cypher_inline_trailing_comment_containing_a_semicolon() -> None:
    """A trailing comment on the same line as real Cypher, itself containing
    a ';', must be dropped entirely rather than leaking into the next
    statement."""
    text = "CREATE X; // note: uses a default value; see ADR-1\nCREATE Y;"
    assert split_cypher_statements(text) == ("CREATE X", "CREATE Y")


def test_split_cypher_multiple_semicolons_inside_comment_prose() -> None:
    """Several ';' characters spread across multiple comment lines must all
    be neutralized before splitting, not just the first one."""
    text = (
        "// first note; second note; third note\n"
        "// more prose; even more prose\n"
        "CREATE X;\n"
        "CREATE Y;"
    )
    assert split_cypher_statements(text) == ("CREATE X", "CREATE Y")


def test_split_cypher_real_m001_migration_produces_exactly_four_statements() -> None:
    """Regression guard against the exact production defect: applying the
    real, unmodified M001__constraints.cypher (whose header comment contains
    a ';' in 'indexes only; no enterprise-only') must yield exactly the four
    intended CREATE CONSTRAINT/CREATE INDEX statements, with no leaked
    comment fragment such as 'no enterprise-only' prefixed onto any of them."""
    text = _M001_PATH.read_text(encoding="utf-8")
    statements = split_cypher_statements(text)

    assert len(statements) == 4
    assert statements[0] == (
        "CREATE CONSTRAINT memory_node_identity IF NOT EXISTS\n"
        "FOR (n:MemoryNode) REQUIRE (n.tenant_id, n.node_id) IS UNIQUE"
    )
    assert statements[1] == (
        "CREATE CONSTRAINT graph_head_tenant IF NOT EXISTS\n"
        "FOR (h:GraphHead) REQUIRE h.tenant_id IS UNIQUE"
    )
    assert statements[2] == (
        "CREATE INDEX memory_node_type IF NOT EXISTS\n"
        "FOR (n:MemoryNode) ON (n.tenant_id, n.node_type)"
    )
    assert statements[3] == (
        "CREATE INDEX memory_edge_identity IF NOT EXISTS\n"
        "FOR ()-[e:MEMORY_EDGE]-() ON (e.tenant_id, e.edge_id)"
    )
    for statement in statements:
        assert "enterprise" not in statement.lower()
