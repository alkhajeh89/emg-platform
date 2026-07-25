from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import get_type_hints

from emg_knowledge_graph import (
    BuildRevisionCommand,
    BuildRevisionResult,
    KnowledgeGraphApplication,
)
from emg_platform_core import InMemoryGraphStore
from emg_platform_core.ports.graph_store import GraphStore

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "emg_knowledge_graph"


def _module_paths() -> tuple[Path, ...]:
    return tuple(sorted(SRC_DIR.glob("*.py")))


def _import_targets(tree: ast.AST) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            targets.add(node.module)
    return targets


def _declared_type_names(tree: ast.AST) -> set[str]:
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def test_application_constructs_with_in_memory_graph_store() -> None:
    app = KnowledgeGraphApplication(graph_store=InMemoryGraphStore())
    assert isinstance(app, KnowledgeGraphApplication)


def test_application_constructor_uses_platform_graph_store_boundary() -> None:
    hints = get_type_hints(KnowledgeGraphApplication.__init__)
    assert hints["graph_store"] is GraphStore
    assert hints["return"] is type(None)
    signature = inspect.signature(KnowledgeGraphApplication.__init__)
    assert "graph_store" in signature.parameters


def test_revision_method_uses_application_contracts() -> None:
    hints = get_type_hints(KnowledgeGraphApplication.build_revision)
    assert hints["command"] is BuildRevisionCommand
    assert hints["return"] is BuildRevisionResult


def test_service_modules_do_not_import_forbidden_store_dependencies() -> None:
    forbidden = ("emg_persistence", "emg_knowledge_pipeline.graph_store")
    offenders: list[str] = []
    for module_path in _module_paths():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported = _import_targets(tree)
        for target in imported:
            if target == forbidden[0] or target.startswith(f"{forbidden[0]}."):
                offenders.append(f"{module_path.name}: {target}")
            if target == forbidden[1] or target.startswith(f"{forbidden[1]}."):
                offenders.append(f"{module_path.name}: {target}")
    assert not offenders, f"forbidden imports found: {offenders}"


def test_service_package_declares_no_forbidden_domain_storage_type_names() -> None:
    forbidden_names = {
        "Node",
        "Edge",
        "Graph",
        "GraphStore",
        "Projection",
        "Version",
        "Evidence",
        "Lineage",
    }
    offenders: list[str] = []
    for module_path in _module_paths():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        declared_names = _declared_type_names(tree)
        overlap = sorted(forbidden_names.intersection(declared_names))
        if overlap:
            offenders.append(f"{module_path.name}: {', '.join(overlap)}")
    assert not offenders, f"forbidden declared type names: {offenders}"
