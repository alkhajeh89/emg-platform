"""Import + public-API surface tests (FEAT-05-4)."""

from __future__ import annotations

import emg_semantic_layer as sl


def test_version() -> None:
    assert sl.__version__ == "0.1.0"


def test_public_api_is_exported() -> None:
    required = {
        # the eight abstractions named in the FEAT-05-4 scope
        "SemanticGraph",
        "SemanticNode",
        "SemanticRelationship",
        "SemanticQuery",
        "SemanticFilter",
        "SemanticResult",
        "SemanticTraversal",
        "SemanticProjection",
        # extension point + planner + errors
        "SemanticQueryExecutor",
        "plan",
        "SemanticPlan",
        "SemanticQueryError",
    }
    assert required.issubset(set(sl.__all__))
    for name in sl.__all__:
        assert hasattr(sl, name), name


def test_no_forbidden_runtime_dependencies() -> None:
    """The layer must not pull in any storage/network/AI machinery.

    Checked in a clean subprocess so the result reflects only what importing
    `emg_semantic_layer` itself pulls in — not modules another package (e.g. a
    FastAPI service) may have already loaded into this interpreter's sys.modules.
    """
    import subprocess
    import sys

    forbidden = ("neo4j", "requests", "httpx", "sqlalchemy", "torch", "openai")
    script = (
        "import sys, emg_semantic_layer\n"
        f"bad = [m for m in {forbidden!r} if m in sys.modules]\n"
        "assert not bad, bad\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"forbidden imports pulled in: {proc.stdout}{proc.stderr}"
