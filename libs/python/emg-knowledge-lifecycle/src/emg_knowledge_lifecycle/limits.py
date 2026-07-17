"""Bounded-traversal / bounded-size limits for the lifecycle library (FEAT-05-5).

These make every model bounded by construction: a version chain can never be
unboundedly large or deep, and free-text metadata fields can never be unbounded.
The library only *defines* these bounds; it executes nothing and stores nothing.
"""

from __future__ import annotations

# The maximum number of versions a single `VersionChain` may hold. A chain models
# one entity's version history; an unbounded chain is both implausible and a
# denial-of-service vector against any consumer that traverses it.
MAX_CHAIN_SIZE: int = 10_000

# The maximum lineage depth (parent -> parent -> ...) any traversal will follow.
# Traversal is hard-capped so a malformed or hostile chain can never cause
# unbounded recursion; the cycle check also relies on this bound as a backstop.
MAX_LINEAGE_DEPTH: int = 10_000

# The maximum version number a `VersionIdentifier` may carry (a sane monotonic
# bound; rejects absurd/overflow-style integers cleanly).
MAX_VERSION_NUMBER: int = 1_000_000_000

# Maximum length of a free-text metadata string (author, note/reason). Bounds the
# size of a lifecycle model and keeps it explainable.
MAX_TEXT_LENGTH: int = 2_000

# Maximum length of an identifier/label (entity id, actor id).
MAX_LABEL_LENGTH: int = 512

# Retention windows are expressed in whole days; this caps the configurable
# window so a policy cannot carry an absurd/overflow value.
MAX_RETENTION_DAYS: int = 3_650_000  # ~10,000 years
