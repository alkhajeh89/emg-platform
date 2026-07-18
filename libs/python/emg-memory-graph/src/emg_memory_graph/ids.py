"""Deterministic identifier helpers (FEAT-05-6).

All memory-graph ids are content-addressed: the same logical input always yields
the same id, on any machine, with no clocks or counters involved. This is what
makes graph construction reproducible and makes deduplication a pure function of
content. We use SHA-256 (same primitive as `emg_knowledge_pipeline.idempotency`)
truncated to 32 hex chars and namespaced with a short prefix so ids are readable
and collision-resistant for enterprise-scale graphs.
"""

from __future__ import annotations

import hashlib

_HEX_LEN = 32


def _digest(*parts: str) -> str:
    """SHA-256 over a NUL-joined tuple of parts, truncated to `_HEX_LEN` hex
    chars. NUL-joining prevents ("ab","c") and ("a","bc") from colliding."""
    joined = "\x00".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:_HEX_LEN]


def node_id_for(node_type: str, canonical_key: str) -> str:
    """Deterministic node id from its type and canonical (post-resolution) key."""
    return f"mn-{_digest('node', node_type, canonical_key)}"


def edge_id_for(edge_type: str, source_id: str, target_id: str) -> str:
    """Deterministic edge id. Undirected callers should pass endpoints in a fixed
    (e.g. sorted) order so that both orientations map to one id."""
    return f"me-{_digest('edge', edge_type, source_id, target_id)}"


def evidence_id_for(source: str, locator: str) -> str:
    """Deterministic evidence id from its source system and stable locator."""
    return f"ev-{_digest('evidence', source, locator)}"


def revision_id_for(graph_content_hash: str, parent_revision_id: str | None) -> str:
    """Deterministic revision id from the graph content hash and its parent."""
    return f"gr-{_digest('revision', graph_content_hash, parent_revision_id or '')}"
