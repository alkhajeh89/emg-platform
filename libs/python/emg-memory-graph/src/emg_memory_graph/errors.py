"""Typed error hierarchy for the Enterprise Memory Graph (FEAT-05-6).

All failures raised by this package derive from `MemoryGraphError`, which in turn
derives from the platform-wide `emg_errors.EMGError`, so callers can catch memory
graph problems specifically or platform problems generally. Malformed *models*
still raise `pydantic.ValidationError` at construction; these typed errors cover
*operational* failures (unknown nodes, conflicting merges, traversal bounds).
"""

from __future__ import annotations

from emg_errors import EMGError


class MemoryGraphError(EMGError):
    """Base class for every Enterprise Memory Graph error."""


class NodeNotFoundError(MemoryGraphError):
    """A referenced node id is not present in the graph."""


class EdgeNotFoundError(MemoryGraphError):
    """A referenced edge id is not present in the graph."""


class EvidenceRequiredError(MemoryGraphError):
    """A node or edge assertion was created without traceable evidence."""


class MergeConflictError(MemoryGraphError):
    """Two knowledge objects resolved to the same logical entity but carry
    irreconcilable, conflicting immutable attributes."""


class TemporalConsistencyError(MemoryGraphError):
    """A temporal interval is invalid (e.g. valid_until precedes valid_from) or a
    set of intervals for one fact overlaps in a disallowed way."""


class ResolutionError(MemoryGraphError):
    """Entity resolution could not proceed (e.g. malformed rule configuration)."""


class TraversalLimitError(MemoryGraphError):
    """A traversal exceeded a configured depth/result bound."""


class RevisionError(MemoryGraphError):
    """An invalid graph revision operation (e.g. non-monotonic revision chain)."""
