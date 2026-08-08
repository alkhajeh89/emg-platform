"""ADR-036 D-10.2/D-10.3/D-10.6: no direct datastore access, no
persistence-internal import, from any module in this application. Mirrors
`services/knowledge-graph/tests/test_dependency_boundary.py`'s AST-scan
pattern exactly."""

from __future__ import annotations

import ast
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "emg_studio_bff"

_FORBIDDEN_IMPORT_PREFIXES = (
    "emg_persistence",
    "emg_memory_graph",
    # the domain/application package itself, not just its HTTP API — the
    # BFF must call Knowledge Graph over HTTP only, never import it.
    "emg_knowledge_graph",
    "psycopg",
    "neo4j",
)


def _module_paths() -> tuple[Path, ...]:
    return tuple(sorted(SRC_DIR.rglob("*.py")))


def _import_targets(tree: ast.AST) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            targets.add(node.module)
    return targets


def test_no_forbidden_persistence_import_anywhere_in_this_application() -> None:
    offenders: list[str] = []
    for module_path in _module_paths():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for target in _import_targets(tree):
            if any(target == p or target.startswith(p + ".") for p in _FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(f"{module_path.relative_to(SRC_DIR)}: {target}")
    assert not offenders, f"forbidden persistence/domain import found: {offenders}"


def test_no_sql_or_cypher_construction_keywords_in_source() -> None:
    """ADR-036 D-10.3: no SQL or Cypher construction in the BFF. A coarse
    but real signal — this application's routers only ever forward HTTP
    requests, so none of these keywords should appear as source text."""
    offenders: list[str] = []
    banned_snippets = ("SELECT ", "INSERT INTO", "MATCH (", "CREATE (n:", "cursor.execute")
    for module_path in _module_paths():
        text = module_path.read_text(encoding="utf-8")
        for snippet in banned_snippets:
            if snippet in text:
                offenders.append(f"{module_path.name}: {snippet!r}")
    assert not offenders, f"SQL/Cypher-shaped construction found: {offenders}"
