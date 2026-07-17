"""Import + public-API surface tests (FEAT-05-5)."""

from __future__ import annotations

import subprocess
import sys

import emg_knowledge_lifecycle as kl


def test_version() -> None:
    assert kl.__version__ == "0.1.0"


def test_public_api_is_exported() -> None:
    required = {
        # the abstractions named in the FEAT-05-5 scope
        "KnowledgeVersion",
        "VersionIdentifier",
        "VersionChain",
        "VersionMetadata",
        "VersionState",
        "LifecycleEvent",
        "LifecyclePolicy",
        "RetentionPolicy",
        "RetentionDecision",
        "ArchiveDecision",
        "RestoreDecision",
        "LifecycleValidator",
        # evaluators + errors
        "evaluate_retention",
        "evaluate_archive",
        "evaluate_restore",
        "LifecycleError",
        "InvalidTransitionError",
        "InvalidChainError",
    }
    assert required.issubset(set(kl.__all__))
    for name in kl.__all__:
        assert hasattr(kl, name), name


def test_no_forbidden_runtime_dependencies() -> None:
    """Checked in a clean subprocess: importing the library must not pull in any
    storage/network/AI machinery or any sibling Module-7 package (clean
    dependency direction)."""
    forbidden = (
        "neo4j",
        "requests",
        "httpx",
        "sqlalchemy",
        "torch",
        "openai",
        "emg_knowledge_pipeline",
        "emg_trust_scoring",
        "emg_semantic_layer",
        "emg_ontology",
    )
    script = (
        "import sys, emg_knowledge_lifecycle\n"
        f"bad = [m for m in {forbidden!r} if m in sys.modules]\n"
        "assert not bad, bad\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"forbidden imports pulled in: {proc.stdout}{proc.stderr}"
