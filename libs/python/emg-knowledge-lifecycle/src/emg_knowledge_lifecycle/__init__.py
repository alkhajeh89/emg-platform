"""emg_knowledge_lifecycle — storage-independent Knowledge Lifecycle & Versioning
(Module 7 — Knowledge Graph Platform, EPIC-05, FEAT-05-5). Added Sprint 13.

Library-first, the same contract-first pattern as the other Module 7 libraries
(`emg-ontology`, `emg-trust-scoring`, `emg-semantic-layer`): this package defines
the **managed lifecycle state machine** the ontology deferred
(``emg_ontology.LifecycleStatus`` carries a coarse state and notes "the managed
proposed→active→retired state machine is FEAT-05-5"), plus **immutable version
chains**, **deterministic lifecycle transitions**, and **pure retention / archive
/ restore evaluation**.

It defines *lifecycle semantics only* — it **executes nothing and stores
nothing**. Out of scope for Sprint 13 (deliberately): persistence, any scheduler
or execution engine, networking, Neo4j, retrieval, embeddings, AI, LLM, REST, UI,
and any wiring into `emg-knowledge-pipeline`, `emg-trust-scoring`, or
`emg-semantic-layer`. Integration happens only through future extension points.

Security properties: all models are frozen and self-validating (malformed
lifecycle models are rejected at construction), state transitions come from a
fixed closed table (no arbitrary rule, no arbitrary code), chain traversal is
bounded (no unbounded recursion), identifiers are validated against control/bidi
characters (no injection surface), and evaluation is deterministic (an explicit
`as_of`, never a wall-clock read).
"""

from .chain import VersionChain
from .decisions import ArchiveDecision, RestoreDecision, RetentionDecision
from .errors import (
    InvalidChainError,
    InvalidTransitionError,
    LifecycleError,
    MissingReasonError,
)
from .events import LifecycleEvent
from .identifiers import VersionIdentifier
from .labels import ensure_safe_label
from .limits import (
    MAX_CHAIN_SIZE,
    MAX_LABEL_LENGTH,
    MAX_LINEAGE_DEPTH,
    MAX_RETENTION_DAYS,
    MAX_TEXT_LENGTH,
    MAX_VERSION_NUMBER,
)
from .metadata import VersionMetadata
from .policy import (
    DEFAULT_LIFECYCLE_POLICY,
    DEFAULT_RETENTION_POLICY,
    LIFECYCLE_POLICY_VERSION,
    RETENTION_POLICY_VERSION,
    LifecyclePolicy,
    RetentionPolicy,
)
from .retention import evaluate_archive, evaluate_restore, evaluate_retention
from .states import (
    ALL_STATES,
    LIVE_STATES,
    VersionState,
    allowed_transitions,
    is_restore_transition,
    is_valid_transition,
)
from .validation import (
    ChainIssue,
    ChainIssueKind,
    ChainValidationReport,
    LifecycleValidator,
)
from .version import KnowledgeVersion

__version__ = "0.1.0"

__all__ = [
    # states + transitions
    "VersionState",
    "ALL_STATES",
    "LIVE_STATES",
    "is_valid_transition",
    "allowed_transitions",
    "is_restore_transition",
    # identity + version model
    "VersionIdentifier",
    "VersionMetadata",
    "KnowledgeVersion",
    "LifecycleEvent",
    # chain + lineage
    "VersionChain",
    # validation
    "LifecycleValidator",
    "ChainValidationReport",
    "ChainIssue",
    "ChainIssueKind",
    # policy
    "LifecyclePolicy",
    "RetentionPolicy",
    "DEFAULT_LIFECYCLE_POLICY",
    "DEFAULT_RETENTION_POLICY",
    "LIFECYCLE_POLICY_VERSION",
    "RETENTION_POLICY_VERSION",
    # retention / archive / restore evaluation
    "evaluate_retention",
    "evaluate_archive",
    "evaluate_restore",
    "RetentionDecision",
    "ArchiveDecision",
    "RestoreDecision",
    # errors
    "LifecycleError",
    "InvalidTransitionError",
    "InvalidChainError",
    "MissingReasonError",
    # identifier/label validation helper
    "ensure_safe_label",
    # limits
    "MAX_CHAIN_SIZE",
    "MAX_LINEAGE_DEPTH",
    "MAX_VERSION_NUMBER",
    "MAX_TEXT_LENGTH",
    "MAX_LABEL_LENGTH",
    "MAX_RETENTION_DAYS",
    # version
    "__version__",
]
