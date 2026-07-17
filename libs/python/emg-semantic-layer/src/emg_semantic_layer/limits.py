"""Bounded-execution limits for the Semantic Layer (FEAT-05-4).

These constants make the query model *bounded by construction*: a traversal can
never request unbounded depth and a page can never request an unbounded slice.
They are part of the storage-independent contract — every conforming executor
(a future Neo4j binding, an in-memory test double, etc.) must honour them — but
this library only *defines* them; it executes nothing.
"""

from __future__ import annotations

# The maximum number of traversal hops a single query may request. Traversal is
# the most expensive graph operation and the classic denial-of-service vector,
# so depth is hard-capped here rather than left to the storage backend.
MAX_TRAVERSAL_DEPTH: int = 10

# Pagination bounds. A query must ask for a bounded window; an unbounded "return
# everything" result is not expressible. `offset` is bounded above as well, so a
# query cannot request an arbitrarily deep page (deep-offset paging is itself a
# denial-of-service vector against any backend; keyset pagination — a later
# concern — is the scalable alternative and is out of scope here).
MIN_PAGE_LIMIT: int = 1
MAX_PAGE_LIMIT: int = 1000
DEFAULT_PAGE_LIMIT: int = 100
MAX_PAGE_OFFSET: int = 1_000_000

# The maximum number of relationship types a single traversal step may name
# (a bounded fan-out; keeps a step's semantics small and explainable).
MAX_RELATIONSHIP_TYPES_PER_STEP: int = 25

# The maximum nesting depth of a boolean filter expression. Bounds the recursion
# a conforming executor must perform when compiling a filter, and keeps a filter
# explainable. Depth 1 = a flat group of conditions.
MAX_FILTER_DEPTH: int = 8

# Width bounds for the remaining user-controlled collections. Nesting depth alone
# does not bound a query: a single flat group could otherwise carry unbounded
# conditions, and a selector could carry unbounded ids. Each collection is capped
# so the whole query is bounded — in size, not just in depth — by construction.
MAX_SELECTOR_IDS: int = 1000
MAX_FILTER_CONDITIONS: int = 100
MAX_FILTER_GROUPS: int = 100
MAX_PROJECTION_FIELDS: int = 200
MAX_ORDERING_KEYS: int = 32
