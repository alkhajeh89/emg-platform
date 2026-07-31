"""Hard bounds for the Enterprise Memory Graph (FEAT-05-6).

Every externally-influenced collection and string is length-capped here so that a
hostile or malformed input cannot cause unbounded memory growth or degrade a
graph operation's documented complexity. These are deliberate, conservative
ceilings — not tuning knobs — and are enforced at model construction.
"""

from __future__ import annotations

# --- Strings -----------------------------------------------------------------
MAX_LABEL_LENGTH: int = 512
MAX_TEXT_LENGTH: int = 8_192

# --- Node / edge collections -------------------------------------------------
MAX_METADATA_ENTRIES: int = 128
MAX_EVIDENCE_REFS: int = 256
MAX_ALIASES: int = 64
MAX_SUPERSEDES: int = 500
MAX_TEMPORAL_INTERVALS: int = 4_096

# --- Graph collections -------------------------------------------------------
MAX_NODES: int = 1_000_000
MAX_EDGES: int = 4_000_000

# --- Query / traversal -------------------------------------------------------
MAX_TRAVERSAL_DEPTH: int = 64
MAX_PATH_RESULTS: int = 1_000
MAX_LINEAGE_DEPTH: int = 256

# --- Versioning --------------------------------------------------------------
MAX_REVISION_NUMBER: int = 1_000_000
