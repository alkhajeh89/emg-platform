"""Import, public-API surface, dependency-direction, and no-vendor-branching (FEAT-13-1)."""

from __future__ import annotations

import io
import pathlib
import subprocess
import sys
import tokenize

import emg_connectors as c


def test_version() -> None:
    assert c.__version__ == "0.1.0"


def test_public_api_surface() -> None:
    required = {
        "Connector",
        "ConnectorRegistry",
        "ConnectorDescriptor",
        "ConnectorCapabilities",
        "ConnectorHealth",
        "ConnectorConfiguration",
        "ConnectorAuthentication",
        "ConnectorSession",
        "ConnectorDiscovery",
        "ConnectorLifecycle",
        "ConnectorFactory",
        "ConnectorContext",
        "ConnectorMetadata",
        "ConnectorMapper",
        "EntityMapper",
        "RelationshipMapper",
        "MetadataMapper",
        "ConnectorEvent",
        "ConnectorEventType",
        "ConnectorChange",
        "ConnectorSnapshot",
        "SynchronizationContract",
        "SynchronizationMode",
        "SynchronizationPolicy",
        "IncrementalSynchronization",
        "FullSynchronization",
        "ConnectorStatus",
        "ConnectorStatistics",
        "ConnectorValidator",
        # plugin architecture
        "ConnectorPlugin",
        "ConnectorPluginDescriptor",
        "ConnectorPluginLoader",
        "CapabilityRegistry",
        "PluginValidation",
        "PluginCompatibility",
        "PluginLifecycle",
        # errors
        "ConnectorError",
    }
    assert required.issubset(set(c.__all__))
    for name in c.__all__:
        assert hasattr(c, name), name


def test_no_forbidden_runtime_dependencies() -> None:
    """Importing the framework must pull in no networking / SDK / persistence
    module and no sibling Module-7 package (clean dependency direction)."""
    # Third-party network/SDK client libraries + sibling packages the framework
    # must never import. Stdlib modules such as `socket` are intentionally excluded:
    # pydantic (a legitimate dependency) imports them transitively; the framework
    # itself opens no socket and calls no network API.
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "sqlalchemy",
        "neo4j",
        "boto3",
        "azure",
        "msal",
        "office365",
        "simple_salesforce",
        "jira",
        "emg_ontology",
        "emg_semantic_layer",
        "emg_knowledge_pipeline",
    )
    script = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "import emg_connectors\n"
        "added = set(sys.modules) - before\n"
        f"bad = [m for m in {forbidden!r} if m in added]\n"
        "assert not bad, bad\nprint('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"forbidden imports: {proc.stdout}{proc.stderr}"


def _code_without_strings_and_comments(path: pathlib.Path) -> str:
    """Return the source of `path` with all string literals and comments removed,
    so only executable code tokens remain."""
    src = path.read_text(encoding="utf-8")
    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.STRING, tokenize.COMMENT):
            continue
        if tok.type == tokenize.NAME or tok.type == tokenize.OP:
            out.append(tok.string)
    return " ".join(out).lower()


def test_core_has_no_vendor_branching() -> None:
    """The core must contain no vendor name in executable code (no `if SAP`,
    `== "oracle"`, etc.). Vendor names may appear only in docstrings/comments
    (e.g. the "no SAP/Oracle/..." disclaimers)."""
    vendors = (
        "sap",
        "oracle",
        "sharepoint",
        "teams",
        "outlook",
        "copilot",
        "dynamics",
        "salesforce",
        "servicenow",
        "jira",
        "confluence",
        "github",
        "workspace",
    )
    src_dir = pathlib.Path(c.__file__).parent
    offenders: list[str] = []
    for py in sorted(src_dir.glob("*.py")):
        code = _code_without_strings_and_comments(py)
        for vendor in vendors:
            if vendor in code:
                offenders.append(f"{py.name}: {vendor}")
    assert not offenders, f"vendor tokens in executable code: {offenders}"
