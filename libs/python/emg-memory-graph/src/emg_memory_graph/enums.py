"""Closed vocabularies for the Enterprise Memory Graph (FEAT-05-6).

Node and edge *types* are stored as free-form `SafeLabel` strings so the graph can
be extended with new domain concepts without a breaking change (the sprint's
"support future expansion without breaking compatibility"). These enums are the
**canonical vocabulary** for the concepts this sprint ships — convenient, typo-proof
constants whose `.value` is what gets stored — but a node/edge may legitimately
carry a type outside them. The other enums here (evidence source, match type,
direction, confidence band) are genuinely closed.
"""

from __future__ import annotations

from enum import Enum


class MemoryNodeType(str, Enum):
    """Canonical node concepts. Values are the strings stored on `MemoryNode`."""

    ENTITY = "entity"
    PERSON = "person"
    DEPARTMENT = "department"
    PROJECT = "project"
    MEETING = "meeting"
    DECISION = "decision"
    RISK = "risk"
    ACTION = "action"
    POLICY = "policy"
    DOCUMENT = "document"
    EVIDENCE = "evidence"
    OBSERVATION = "observation"
    VERSION = "version"
    # Decision-lineage stages (Requirement -> Meeting -> Discussion -> Decision
    # -> Approval -> Implementation).
    REQUIREMENT = "requirement"
    DISCUSSION = "discussion"
    APPROVAL = "approval"
    IMPLEMENTATION = "implementation"


class EdgeType(str, Enum):
    """Canonical relationship concepts. Values are stored on `MemoryEdge`."""

    OWNS = "owns"
    OWNED_BY = "owned_by"
    APPROVED = "approved"
    APPROVED_BY = "approved_by"
    PARTICIPATED_IN = "participated_in"
    HAS_PARTICIPANT = "has_participant"
    DISCUSSED_IN = "discussed_in"
    DISCUSSED = "discussed"
    DERIVED_FROM = "derived_from"
    SUPPORTS = "supports"
    AFFECTS = "affects"
    ORIGINATES_FROM = "originates_from"
    MITIGATES = "mitigates"
    PART_OF = "part_of"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    RESULTED_IN = "resulted_in"
    PRECEDES = "precedes"
    EVIDENCED_BY = "evidenced_by"
    RELATES_TO = "relates_to"


class EvidenceSource(str, Enum):
    """The supported provenance sources for a piece of evidence."""

    EMAIL = "email"
    MEETING_MINUTES = "meeting_minutes"
    PDF = "pdf"
    WORD_DOCUMENT = "word_document"
    SHAREPOINT = "sharepoint"
    TEAMS = "teams"
    JIRA = "jira"
    MANUAL_ENTRY = "manual_entry"


class MatchType(str, Enum):
    """How an entity-resolution decision was reached (deterministic strategies)."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    ALIAS = "alias"
    RULE = "rule"


class EdgeDirection(str, Enum):
    """Whether an edge is directed (source -> target) or symmetric."""

    DIRECTED = "directed"
    UNDIRECTED = "undirected"


class ConfidenceBand(str, Enum):
    """A human-readable band derived from a numeric confidence score."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    CONFLICTED = "conflicted"
