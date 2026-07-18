"""Bounded-size limits for the connector framework (FEAT-13-1).

Every user-/plugin-supplied collection and string is bounded, so a descriptor,
configuration, or plugin registration can never carry an unbounded payload. The
framework only *defines* these bounds; it executes nothing, stores nothing, and
performs no I/O.
"""

from __future__ import annotations

# Identifier / label lengths.
MAX_LABEL_LENGTH: int = 256
MAX_TEXT_LENGTH: int = 4_000

# Collection sizes on descriptors and registries.
MAX_CAPABILITIES: int = 128
MAX_EXTENSION_CAPABILITIES: int = 256
MAX_ENTITY_TYPES: int = 512
MAX_SYNC_MODES: int = 16
MAX_AUTH_MECHANISMS: int = 32
MAX_CONFIG_FIELDS: int = 256
MAX_TAGS: int = 64
MAX_REGISTERED_CONNECTORS: int = 10_000
MAX_REGISTERED_PLUGINS: int = 10_000
MAX_PROVIDED_CONNECTORS_PER_PLUGIN: int = 256

# Synchronization bounds (contract-level; the framework runs no sync).
MIN_BATCH_SIZE: int = 1
MAX_BATCH_SIZE: int = 100_000
