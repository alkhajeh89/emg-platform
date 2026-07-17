"""The storage-binding extension point (FEAT-05-4).

This module defines the **only** integration seam of the Semantic Layer: the
`SemanticQueryExecutor` protocol. A future storage binding (a Neo4j adapter, an
in-memory test double, a federated backend) implements this protocol to actually
run a query; the Semantic Layer itself implements nothing, connects to nothing,
and imports no driver or network client.

A conforming executor MUST:
  * treat the `SemanticQuery` as read-only and honour its bounds (traversal depth,
    page limit) exactly — it must never widen them;
  * follow the canonical step order from `plan()` so results are reproducible
    across backends;
  * map the closed-enum operators onto its own *parameterised* query API and never
    string-concatenate query text (no injection surface);
  * return a `SemanticResult` whose page metadata matches the query's pagination.

`plan()` (see `planner.py`) is provided so a binding can obtain the validated,
canonical plan without re-deriving execution order.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .query import SemanticQuery
from .result import SemanticResult


@runtime_checkable
class SemanticQueryExecutor(Protocol):
    """Contract a storage binding implements to execute semantic queries.

    Defined as a `Protocol` (structural) so bindings need not import or subclass
    anything from this library beyond the query/result types — the Semantic Layer
    stays free of any dependency on a concrete backend."""

    def execute(self, query: SemanticQuery) -> SemanticResult:
        """Execute `query` against the backing store and return the result.

        Implementations must not mutate `query`, must honour its bounds, and must
        return a storage-independent `SemanticResult`. This library provides no
        implementation."""
        ...
