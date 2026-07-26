"""EMG Knowledge Graph Query REST API (Sprint 7.4).

A thin HTTP boundary over the existing `emg_knowledge_graph` application
service (Sprint 7.1-7.3 / ADR-022, ADR-023, ADR-024). This package contains
no graph-query business logic: every route validates transport shape,
constructs the existing Phase 1 command objects, calls
`KnowledgeGraphApplication` methods, and maps the returned application DTOs
into typed HTTP response schemas.

**Packaging note — read before restructuring.** This package is a second
`[tool.hatch.build.targets.wheel].packages` entry in
`services/knowledge-graph/pyproject.toml`, alongside `emg_knowledge_graph`.
Every other package in this repository (all of `libs/python/*` plus
`services/audit`, `services/identity`) is exactly one package per
pyproject.toml, so this is a deliberate, reviewed divergence, not an
oversight — recorded here so a future engineer doesn't "fix" it without
reading the rationale first.

An earlier draft of this docstring justified the split by analogy to
`emg_audit_service` living alongside `emg_audit_pipeline`/`emg_audit_client`.
That analogy does not hold: those are separately-versioned libraries under
`libs/python/`, each with its own pyproject.toml, each reusable by more than
one service (`emg_audit_client` is also a direct dependency of
`emg_identity`). The actual justification is narrower:

1. `emg_knowledge_graph_api` has exactly one possible consumer — the
   knowledge-graph service deployment — and no standalone reuse value.
   Nothing else in the platform would ever depend on this HTTP shell the way
   `emg_identity` depends on `emg_audit_client`. Giving it its own
   `libs/python` pyproject.toml, version number, and install-order entry
   would model it as a general-purpose library it is not.
2. It cannot live *inside* `emg_knowledge_graph` as a subpackage: that
   package's `tests/test_dependency_boundary.py` exists specifically to keep
   `emg_knowledge_graph` free of persistence/web dependencies, and Sprint
   7.4's own STRICT RULES forbid modifying that package. A second top-level
   package was the only option that added zero FastAPI/web surface to the
   pure application package while still living inside the one service
   directory (`services/knowledge-graph/`) this sprint was scoped to.
3. The two packages are always deployed together, never independently
   versioned or released — they are one logical service artifact split only
   to keep the *build boundary* (what a graph-query business-logic
   correctness reviewer needs to read) separate from the *transport
   boundary* (what an HTTP/API reviewer needs to read).

If a second HTTP-facing consumer of `emg_knowledge_graph` ever emerges, this
decision should be revisited: extracting `emg_knowledge_graph_api` into its
own `libs/python` (or sibling `services/`) package with its own
pyproject.toml at that point would be the correct move, mirroring the
audit-client/audit-pipeline/audit-service three-package precedent properly
instead of by analogy.
"""

from __future__ import annotations

__version__ = "0.1.0"
