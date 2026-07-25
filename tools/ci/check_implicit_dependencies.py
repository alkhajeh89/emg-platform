"""Detect emg-* packages that are imported by source code but never declared
as a dependency in that package's own pyproject.toml.

This complements check_dependency_drift.py, which only compares
pyproject.toml against docker/dependencies.yaml (declared vs. declared).
It never looks at what the code actually imports. This script closes that
gap: it parses every .py file under each manifest component's src/
directory with the `ast` module and flags any cross-package emg-* import
that has no matching entry in dependencies = [...] of that component's own
pyproject.toml.

Design notes (see docs/devops/DEPENDENCY_GOVERNANCE.md):
  * AST-based, not regex-based -- avoids false matches inside strings,
    comments, and docstrings, and lets us see *where* an import occurs.
  * Standard library only (ast, pathlib, sys, tomllib/tomli, yaml is the
    only third-party dep, already used by the other two CI scripts).
  * Imports inside `if TYPE_CHECKING:` blocks are reported separately from
    plain runtime imports (see ImportFinding.type_only) rather than being
    silently excluded or silently required -- see the governance doc for
    the reasoning.
  * No handling for optional (try/except ImportError) imports or dynamic
    (importlib.import_module) imports: neither pattern exists anywhere in
    this repository today. Added only if a real case appears.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py < 3.11 fallback
    import tomli as tomllib


ROOT = Path(__file__).parents[2]


def load_manifest() -> dict:
    manifest = ROOT / "docker" / "dependencies.yaml"
    return yaml.safe_load(manifest.read_text())


def load_pyproject(pyproject: Path) -> dict:
    text = pyproject.read_text()
    if not text.strip():
        return {}
    return tomllib.loads(text)


def get_declared_emg_dependencies(pyproject_data: dict) -> set[str]:
    deps = pyproject_data.get("project", {}).get("dependencies", [])
    result = set()
    for dep in deps:
        name = dep.split(">")[0].split("=")[0].split("<")[0].split("[")[0].strip()
        if name.startswith("emg-"):
            result.add(name)
    return result


def get_own_package_name(pyproject_data: dict) -> str | None:
    return pyproject_data.get("project", {}).get("name")


def module_to_package(module_name: str) -> str | None:
    """Map an importable top-level module name to its dash-cased emg-*
    package name, e.g. emg_common_types -> emg-common-types. Returns None
    for anything that isn't an emg_* module (third-party imports)."""
    if not module_name.startswith("emg_"):
        return None
    return module_name.replace("_", "-")


@dataclass(frozen=True)
class ImportFinding:
    package: str
    file: Path
    lineno: int
    type_only: bool


def _is_type_checking_test(test: ast.expr) -> bool:
    """Match `if TYPE_CHECKING:` and `if typing.TYPE_CHECKING:`."""
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


class _ImportVisitor(ast.NodeVisitor):
    """Walks an entire module (not just top-level statements) so that
    imports deferred inside function bodies are still caught, matching
    real patterns found in this repo (e.g. emg_persistence/neo4j/lazy.py)."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.findings: list[ImportFinding] = []
        self._type_checking_depth = 0

    def visit_If(self, node: ast.If) -> None:
        is_type_checking = _is_type_checking_test(node.test)
        if is_type_checking:
            self._type_checking_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        if is_type_checking:
            self._type_checking_depth -= 1
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top_level = alias.name.split(".")[0]
            self._record(top_level, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level and node.module is None:
            # `from . import x` / `from .. import x` -- relative, intra-package.
            return self.generic_visit(node)
        if node.level:
            # `from .config import X` -- relative, intra-package.
            return self.generic_visit(node)
        if node.module:
            top_level = node.module.split(".")[0]
            self._record(top_level, node.lineno)
        self.generic_visit(node)

    def _record(self, module_name: str, lineno: int) -> None:
        package = module_to_package(module_name)
        if package is None:
            return
        self.findings.append(
            ImportFinding(
                package=package,
                file=self.file_path,
                lineno=lineno,
                type_only=self._type_checking_depth > 0,
            )
        )


def scan_imports(src_root: Path, own_module: str | None) -> list[ImportFinding]:
    findings: list[ImportFinding] = []
    for py_file in sorted(src_root.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError as exc:
            print(f"⚠️ could not parse {py_file}: {exc}")
            continue
        visitor = _ImportVisitor(py_file)
        visitor.visit(tree)
        for finding in visitor.findings:
            if own_module and finding.package == module_to_package(own_module):
                continue  # self-import
            findings.append(finding)
    return findings


def check_component(name: str, component: dict) -> bool:
    path = ROOT / component["path"]
    pyproject_path = path / "pyproject.toml"

    if not pyproject_path.exists():
        print(f"⚠️ {name}: no pyproject.toml found, skipping")
        return True

    pyproject_data = load_pyproject(pyproject_path)
    declared = get_declared_emg_dependencies(pyproject_data)
    own_name = get_own_package_name(pyproject_data)
    own_module = own_name.replace("-", "_") if own_name else None

    src_root = path / "src"
    if not src_root.exists():
        print(f"⚠️ {name}: no src/ directory, skipping")
        return True

    findings = scan_imports(src_root, own_module)

    runtime_missing = {f.package for f in findings if not f.type_only} - declared
    type_only_missing = {f.package for f in findings if f.type_only} - declared
    # Don't double-report a package that also has a runtime finding.
    type_only_missing -= runtime_missing

    ok = True

    if runtime_missing:
        print(f"❌ {name}: imported but not declared as a dependency:")
        for pkg in sorted(runtime_missing):
            examples = [f for f in findings if f.package == pkg and not f.type_only]
            loc = examples[0]
            rel = loc.file.relative_to(ROOT)
            print(f"   - {pkg} (e.g. {rel}:{loc.lineno})")
        ok = False

    if type_only_missing:
        print(f"ℹ️  {name}: imported only under TYPE_CHECKING, not declared:")
        for pkg in sorted(type_only_missing):
            examples = [f for f in findings if f.package == pkg and f.type_only]
            loc = examples[0]
            rel = loc.file.relative_to(ROOT)
            print(f"   - {pkg} (e.g. {rel}:{loc.lineno})")

    if ok and not type_only_missing:
        print(f"✅ {name}: all imports declared")

    return ok


def main() -> None:
    manifest = load_manifest()

    if "services" not in manifest:
        print("❌ Invalid dependency manifest: missing services section")
        sys.exit(1)

    failed = False

    for name, component in manifest["services"].items():
        if not check_component(name, component):
            failed = True

    if failed:
        sys.exit(1)

    print("✅ Implicit dependency validation passed")


if __name__ == "__main__":
    main()
