"""Unit tests for check_implicit_dependencies.py.

Every test builds a synthetic, throwaway package under tmp_path (a
pyproject.toml + one or more .py files under src/) rather than depending on
any real libs/python/* package, so these tests stay stable regardless of
future changes to the actual repository. The one exception is
test_real_repository_has_zero_findings, which intentionally validates the
tool against the live repo as a regression guard (see ECP-2 plan, Section 6).
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import check_implicit_dependencies as cid  # noqa: E402


def make_package(
    tmp_path: Path,
    dash_name: str,
    dependencies: list[str],
    files: dict[str, str],
) -> Path:
    """Create tmp_path/<dash_name>/{pyproject.toml, src/<module>/...}."""
    module_name = dash_name.replace("-", "_")
    pkg_dir = tmp_path / dash_name
    src_dir = pkg_dir / "src" / module_name
    src_dir.mkdir(parents=True)

    deps_toml = ", ".join(f'"{d}"' for d in dependencies)
    (pkg_dir / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""
            [project]
            name = "{dash_name}"
            version = "0.1.0"
            dependencies = [{deps_toml}]
            """
        )
    )

    (src_dir / "__init__.py").write_text("")
    for rel_path, content in files.items():
        target = src_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(content))

    return pkg_dir


def component_for(pkg_dir: Path, tmp_path: Path) -> dict:
    return {"path": str(pkg_dir.relative_to(tmp_path))}


def test_clean_package_no_findings(tmp_path, monkeypatch, capsys):
    pkg = make_package(
        tmp_path,
        "emg-clean",
        dependencies=[],
        files={"core.py": "import os\nimport sys\n"},
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("clean", component_for(pkg, tmp_path))

    assert ok is True
    assert "✅" in capsys.readouterr().out


def test_third_party_import_ignored(tmp_path, monkeypatch, capsys):
    pkg = make_package(
        tmp_path,
        "emg-thirdparty",
        dependencies=[],
        files={"core.py": "import psycopg\nfrom neo4j import GraphDatabase\n"},
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("thirdparty", component_for(pkg, tmp_path))

    assert ok is True


def test_declared_dependency_import_passes(tmp_path, monkeypatch):
    pkg = make_package(
        tmp_path,
        "emg-consumer",
        dependencies=["emg-errors"],
        files={"core.py": "from emg_errors import EmgError\n"},
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("consumer", component_for(pkg, tmp_path))

    assert ok is True


def test_undeclared_runtime_import_detected(tmp_path, monkeypatch, capsys):
    pkg = make_package(
        tmp_path,
        "emg-consumer",
        dependencies=[],
        files={"core.py": "from emg_errors import EmgError\n"},
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("consumer", component_for(pkg, tmp_path))
    out = capsys.readouterr().out

    assert ok is False
    assert "emg-errors" in out
    assert "❌" in out


def test_undeclared_import_deferred_in_function_body_is_detected(tmp_path, monkeypatch, capsys):
    # Mirrors emg_persistence/neo4j/lazy.py's real pattern: import statement
    # nested inside a function body, not at module top level.
    pkg = make_package(
        tmp_path,
        "emg-consumer",
        dependencies=[],
        files={
            "core.py": """
                def get():
                    from emg_errors import EmgError
                    return EmgError
            """
        },
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("consumer", component_for(pkg, tmp_path))
    out = capsys.readouterr().out

    assert ok is False
    assert "emg-errors" in out


def test_type_checking_only_import_reported_but_does_not_fail(tmp_path, monkeypatch, capsys):
    pkg = make_package(
        tmp_path,
        "emg-consumer",
        dependencies=[],
        files={
            "core.py": """
                from typing import TYPE_CHECKING

                if TYPE_CHECKING:
                    from emg_errors import EmgError

                def handle(err: "EmgError") -> None:
                    ...
            """
        },
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("consumer", component_for(pkg, tmp_path))
    out = capsys.readouterr().out

    assert ok is True
    assert "emg-errors" in out
    assert "TYPE_CHECKING" in out


def test_type_checking_import_also_used_at_runtime_is_a_hard_failure(tmp_path, monkeypatch, capsys):
    # If the same package is imported both under TYPE_CHECKING and for real
    # at runtime elsewhere, it must be treated as a runtime-missing finding,
    # not silently downgraded to informational.
    pkg = make_package(
        tmp_path,
        "emg-consumer",
        dependencies=[],
        files={
            "core.py": """
                from typing import TYPE_CHECKING

                if TYPE_CHECKING:
                    from emg_errors import EmgError

                from emg_errors import raise_error
            """
        },
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("consumer", component_for(pkg, tmp_path))
    out = capsys.readouterr().out

    assert ok is False
    assert "❌" in out


def test_self_import_excluded(tmp_path, monkeypatch, capsys):
    pkg = make_package(
        tmp_path,
        "emg-selfref",
        dependencies=[],
        files={
            "core.py": "from emg_selfref.helpers import thing\n",
            "helpers.py": "thing = 1\n",
        },
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("selfref", component_for(pkg, tmp_path))

    assert ok is True


def test_relative_intra_package_import_not_flagged(tmp_path, monkeypatch, capsys):
    pkg = make_package(
        tmp_path,
        "emg-relimport",
        dependencies=[],
        files={
            "core.py": "from .helpers import thing\n",
            "helpers.py": "thing = 1\n",
        },
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("relimport", component_for(pkg, tmp_path))

    assert ok is True


def test_malformed_python_file_reported_not_crashed(tmp_path, monkeypatch, capsys):
    pkg = make_package(
        tmp_path,
        "emg-broken",
        dependencies=[],
        files={"core.py": "this is not valid python (((\n"},
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("broken", component_for(pkg, tmp_path))
    out = capsys.readouterr().out

    assert ok is True  # no valid imports found, doesn't crash
    assert "could not parse" in out


def test_missing_pyproject_is_skipped_not_failed(tmp_path, monkeypatch, capsys):
    pkg_dir = tmp_path / "emg-nopyproject"
    (pkg_dir / "src").mkdir(parents=True)
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("nopyproject", {"path": "emg-nopyproject"})
    out = capsys.readouterr().out

    assert ok is True
    assert "no pyproject.toml" in out


def test_missing_src_directory_is_skipped_not_failed(tmp_path, monkeypatch, capsys):
    pkg_dir = tmp_path / "emg-nosrc"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "pyproject.toml").write_text(
        '[project]\nname = "emg-nosrc"\nversion = "0.1.0"\ndependencies = []\n'
    )
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("nosrc", {"path": "emg-nosrc"})
    out = capsys.readouterr().out

    assert ok is True
    assert "no src/" in out


def test_empty_pyproject_toml_is_handled(tmp_path, monkeypatch, capsys):
    # Mirrors the real, known emg-entity-resolution case: a 0-byte
    # pyproject.toml. Must not crash; an emg-* import would legitimately
    # be flagged as undeclared, but a package with no imports at all
    # (also the real entity-resolution case today) passes cleanly.
    pkg_dir = tmp_path / "emg-emptyproj"
    src_dir = pkg_dir / "src" / "emg_emptyproj"
    src_dir.mkdir(parents=True)
    (pkg_dir / "pyproject.toml").write_text("")
    (src_dir / "__init__.py").write_text("")
    monkeypatch.setattr(cid, "ROOT", tmp_path)

    ok = cid.check_component("emptyproj", {"path": "emg-emptyproj"})

    assert ok is True


def test_module_to_package_mapping():
    assert cid.module_to_package("emg_common_types") == "emg-common-types"
    assert cid.module_to_package("psycopg") is None
    assert cid.module_to_package("neo4j") is None


def test_real_repository_has_zero_findings():
    """Regression guard: run the real tool against the live repository and
    confirm it reports the clean, ECP-1-resolved baseline (zero runtime
    findings across all manifest components)."""
    manifest = cid.load_manifest()
    failed = False
    for name, component in manifest["services"].items():
        if not cid.check_component(name, component):
            failed = True
    assert failed is False
